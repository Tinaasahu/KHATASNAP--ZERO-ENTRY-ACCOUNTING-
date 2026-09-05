"""
KhataSnap — Confidence Engine
Combines three parallel signals (Calculator, ASR, Inventory) into a single
confidence score that determines how to persist a transaction.

Thresholds:
  >= 0.75  → HIGH   → auto-commit to permanent DB
  0.50-0.74 → MEDIUM → auto-commit + show review card
  < 0.50   → LOW    → flag for night reconciliation

Signal weights:
  ASR exact price match   0.40
  ASR fuzzy name match    0.25
  Inventory availability  0.20
  Price pattern learning  0.15
"""

from __future__ import annotations
import math
import os
import re
from datetime import datetime
from dataclasses import dataclass, field
from typing import Any

# ──────────────────────────────────────────────────────────────────────────────
# Thresholds (Configurable per Section 8 of Master Spec)
# High: >= 0.85 (Auto-commit)
# Medium: 0.60 - 0.85 (Pending/Review)
# Low: < 0.60 (Buffer for Night SRE)
# ──────────────────────────────────────────────────────────────────────────────
DEFAULT_THRESHOLD_HIGH   = float(os.getenv("CONFIDENCE_THRESHOLD_HIGH", 0.85))
DEFAULT_THRESHOLD_MEDIUM = float(os.getenv("CONFIDENCE_THRESHOLD_MEDIUM", 0.60))

# Signal weights (must sum to 1.0)
W_ASR_PRICE   = 0.40
W_ASR_NAME    = 0.25
W_INVENTORY   = 0.20
W_PATTERN     = 0.15

# Fuzzy match minimum similarity to count as a name match
FUZZY_MIN_SIM = 0.65


# ──────────────────────────────────────────────────────────────────────────────
# Data classes
# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class SignalBreakdown:
    asr_price_score: float = 0.0
    asr_name_score: float  = 0.0
    inventory_score: float = 0.0
    pattern_score: float   = 0.0

    @property
    def weighted_total(self) -> float:
        return (
            self.asr_price_score * W_ASR_PRICE
            + self.asr_name_score * W_ASR_NAME
            + self.inventory_score * W_INVENTORY
            + self.pattern_score * W_PATTERN
        )


@dataclass
class MatchedItem:
    item_id:       Any
    item_name:     str
    price:         float
    qty:           int     = 1
    confidence:    float   = 0.0
    source:        str     = "unknown"   # asr_price | asr_name | pattern | unmatched
    asr_matched_alias: str | None = None
    in_stock:      bool    = True
    current_qty:   int     = 0
    signals:       SignalBreakdown = field(default_factory=SignalBreakdown)


@dataclass
class ConfidenceResult:
    score:        float
    decision:     str            # high | medium | low
    matched_items: list[MatchedItem]
    unmatched_amounts: list[float]   # calculator amounts with no ASR/pattern match
    summary:      str
    signals:      SignalBreakdown


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────
def _edit_distance(s1: str, s2: str) -> int:
    s1, s2 = s1.lower(), s2.lower()
    rows = len(s1) + 1
    cols = len(s2) + 1
    dp = [[0] * cols for _ in range(rows)]
    for i in range(rows):
        dp[i][0] = i
    for j in range(cols):
        dp[0][j] = j
    for i in range(1, rows):
        for j in range(1, cols):
            cost = 0 if s1[i - 1] == s2[j - 1] else 1
            dp[i][j] = min(dp[i-1][j]+1, dp[i][j-1]+1, dp[i-1][j-1]+cost)
    return dp[rows-1][cols-1]


def _similarity(s1: str, s2: str) -> float:
    if not s1 or not s2:
        return 0.0
    longer = max(len(s1), len(s2))
    return (longer - _edit_distance(s1, s2)) / longer


def _normalize(text: str) -> str:
    """Lowercase, remove punctuation, collapse whitespace."""
    if not text:
        return ""
    text = text.lower()
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    # Unit normalizations
    text = re.sub(r"\b(grams?|gm)\b", "g", text)
    text = re.sub(r"\b(kilograms?|kilo|kgs?)\b", "kg", text)
    text = re.sub(r"\b(milliliters?|millilitres?)\b", "ml", text)
    text = re.sub(r"\b(liters?|litres?)\b", "l", text)
    return text


def _find_qty_near(words: list[str], anchor_idx: int) -> int:
    """Look for a number word adjacent to the anchor word index."""
    qty_words = {
        "ek": 1, "do": 2, "teen": 3, "char": 4, "paanch": 5,
        "chhe": 6, "saat": 7, "aath": 8, "nau": 9, "das": 10,
        "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
        "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
        "couple": 2, "half": 1,
    }
    for offset in (-1, 1, -2, 2):
        idx = anchor_idx + offset
        if 0 <= idx < len(words):
            w = words[idx]
            if w in qty_words:
                return qty_words[w]
            try:
                n = int(w)
                if 1 <= n <= 99:
                    return n
            except ValueError:
                pass
    return 1


# ──────────────────────────────────────────────────────────────────────────────
# Confidence Engine
# ──────────────────────────────────────────────────────────────────────────────
class ConfidenceEngine:
    """
    Scores a transaction using three parallel signals.

    Parameters
    ----------
    calculator_amounts : list[float | int]
        All operands entered on the calculator (e.g. [10, 20, 12]).
    asr_transcript : str
        Raw accumulated speech transcript for this session.
    inventory_snapshot : list[dict]
        All active inventory products:
          {id, name, selling_price, current_qty, aliases?: [str]}
    price_patterns : list[dict]  (optional)
        Historical pattern records from `price_item_patterns` table:
          {price, item_id, item_name, selection_count}
    """

    def score(
        self,
        calculator_amounts: list,
        asr_transcript: str,
        inventory_snapshot: list[dict],
        price_patterns: list[dict] | None = None,
    ) -> ConfidenceResult:
        if not calculator_amounts:
            return ConfidenceResult(
                score=0.0,
                decision="low",
                matched_items=[],
                unmatched_amounts=[],
                summary="No calculator amounts provided.",
                signals=SignalBreakdown(),
            )

        amounts = [float(a) for a in calculator_amounts]
        norm_transcript = _normalize(asr_transcript or "")
        trans_words = norm_transcript.split() if norm_transcript else []

        patterns = price_patterns or []

        # Build inventory index: price → items
        price_index: dict[float, list[dict]] = {}
        for item in inventory_snapshot:
            p = float(item.get("selling_price") or item.get("price") or 0)
            price_index.setdefault(p, []).append(item)

        # Build pattern index: price → best item
        pattern_index: dict[float, dict] = {}
        for pat in patterns:
            p = float(pat.get("price", 0))
            existing = pattern_index.get(p)
            if not existing or pat.get("selection_count", 0) > existing.get("selection_count", 0):
                pattern_index[p] = pat

        matched_items: list[MatchedItem] = []
        unmatched_amounts: list[float] = []
        all_signal_scores: list[SignalBreakdown] = []

        for amount in amounts:
            sig = SignalBreakdown()
            match = self._match_amount(
                amount, trans_words, norm_transcript, inventory_snapshot,
                price_index, pattern_index, sig
            )
            all_signal_scores.append(sig)
            if match:
                match.signals = sig
                matched_items.append(match)
            else:
                unmatched_amounts.append(amount)

        # ── Aggregate signal scores across all operands ──
        n = len(amounts)
        agg = SignalBreakdown(
            asr_price_score=sum(s.asr_price_score for s in all_signal_scores) / n,
            asr_name_score=sum(s.asr_name_score for s in all_signal_scores) / n,
            inventory_score=sum(s.inventory_score for s in all_signal_scores) / n,
            pattern_score=sum(s.pattern_score for s in all_signal_scores) / n,
        )

        # ── Penalty for unmatched amounts ──
        unmatched_ratio = len(unmatched_amounts) / n
        raw_score = agg.weighted_total * (1.0 - 0.5 * unmatched_ratio)
        final_score = round(min(1.0, max(0.0, raw_score)), 4)

        # ── Decision ──
        th_high = getattr(self, 'threshold_high', DEFAULT_THRESHOLD_HIGH)
        th_med  = getattr(self, 'threshold_medium', DEFAULT_THRESHOLD_MEDIUM)
        if final_score >= th_high:
            decision = "high"
        elif final_score >= th_med:
            decision = "medium"
        else:
            decision = "low"

        # ── Summary text ──
        matched_names = [m.item_name for m in matched_items]
        if matched_names:
            summary = f"{len(matched_items)}/{n} items matched ({', '.join(matched_names[:3])}{'…' if len(matched_names) > 3 else ''}). Confidence: {int(final_score*100)}%"
        else:
            summary = f"No items matched from ASR/patterns. Confidence: {int(final_score*100)}%"

        return ConfidenceResult(
            score=final_score,
            decision=decision,
            matched_items=matched_items,
            unmatched_amounts=unmatched_amounts,
            summary=summary,
            signals=agg,
        )

    # ──────────────────────────────────────────────────────────────────────────
    def _match_amount(
        self,
        amount: float,
        trans_words: list[str],
        norm_transcript: str,
        inventory_snapshot: list[dict],
        price_index: dict,
        pattern_index: dict,
        sig: SignalBreakdown,
    ) -> MatchedItem | None:
        """Attempt to match a single calculator amount using all signals."""

        # ── Signal 1: ASR exact price match ──────────────────────────────────
        exact_inv_matches = price_index.get(amount, [])
        if exact_inv_matches:
            # Check if any of these items are mentioned by name in transcript
            name_matched = []
            for item in exact_inv_matches:
                score = self._asr_name_match_score(item, trans_words, norm_transcript)
                if score > 0:
                    name_matched.append((score, item))

            if name_matched:
                name_matched.sort(key=lambda x: x[0], reverse=True)
                best_score, best_item = name_matched[0]
                sig.asr_price_score = 1.0
                sig.asr_name_score = best_score

                # ── Signal 3: Inventory availability ──
                qty = self._detect_qty(best_item, trans_words, norm_transcript)
                in_stock = (best_item.get("current_qty") or 0) >= qty
                sig.inventory_score = 1.0 if in_stock else 0.3

                # ── Signal 4: Pattern (bonus if history confirms) ──
                pat = pattern_index.get(amount)
                if pat and str(pat.get("item_id")) == str(best_item.get("id")):
                    sig.pattern_score = min(1.0, 0.5 + 0.1 * math.log1p(pat.get("selection_count", 0)))
                else:
                    sig.pattern_score = 0.4  # neutral

                return MatchedItem(
                    item_id=best_item.get("id"),
                    item_name=best_item.get("name", ""),
                    price=amount,
                    qty=qty,
                    confidence=sig.weighted_total,
                    source="asr_price",
                    in_stock=in_stock,
                    current_qty=best_item.get("current_qty", 0),
                )
            else:
                # Price match but no name in ASR
                sig.asr_price_score = 0.7   # partial credit (price matched)
                sig.asr_name_score = 0.0

        # ── Signal 1b: Composite match (qty * price = amount) ──────────────
        for inv_price, items_at_price in price_index.items():
            if inv_price > 0 and inv_price != amount and amount % inv_price == 0:
                inferred_qty = int(amount / inv_price)
                if 2 <= inferred_qty <= 20:
                    for item in items_at_price:
                        score = self._asr_name_match_score(item, trans_words, norm_transcript)
                        if score >= 0.5:
                            sig.asr_price_score = 0.85
                            sig.asr_name_score = score
                            in_stock = (item.get("current_qty") or 0) >= inferred_qty
                            sig.inventory_score = 1.0 if in_stock else 0.3
                            sig.pattern_score = 0.4
                            return MatchedItem(
                                item_id=item.get("id"),
                                item_name=item.get("name", ""),
                                price=inv_price,
                                qty=inferred_qty,
                                confidence=sig.weighted_total,
                                source="asr_price_composite",
                                in_stock=in_stock,
                                current_qty=item.get("current_qty", 0),
                            )

        # ── Signal 2: ASR name match (even without price match) ──────────────
        if norm_transcript:
            best_name_score = 0.0
            best_name_item = None
            for item in inventory_snapshot:
                s = self._asr_name_match_score(item, trans_words, norm_transcript)
                if s > best_name_score:
                    best_name_score = s
                    best_name_item = item

            if best_name_item and best_name_score >= FUZZY_MIN_SIM:
                sig.asr_name_score = best_name_score
                sig.asr_price_score = 0.0  # no price match
                qty = self._detect_qty(best_name_item, trans_words, norm_transcript)
                in_stock = (best_name_item.get("current_qty") or 0) >= qty
                sig.inventory_score = 0.6 if in_stock else 0.2
                sig.pattern_score = 0.3
                return MatchedItem(
                    item_id=best_name_item.get("id"),
                    item_name=best_name_item.get("name", ""),
                    price=amount,
                    qty=qty,
                    confidence=sig.weighted_total,
                    source="asr_name",
                    in_stock=in_stock,
                    current_qty=best_name_item.get("current_qty", 0),
                )

        # ── Signal 4: Pattern-only (no ASR) ──────────────────────────────────
        pat = pattern_index.get(amount)
        if pat and pat.get("selection_count", 0) >= 3:
            pat_count = pat.get("selection_count", 0)
            sig.pattern_score = min(1.0, 0.4 + 0.08 * math.log1p(pat_count))
            sig.asr_price_score = 0.0
            sig.asr_name_score = 0.0

            pid = pat.get("item_id")
            inv_item = next((x for x in inventory_snapshot if str(x.get("id")) == str(pid)), None)
            if inv_item:
                in_stock = (inv_item.get("current_qty") or 0) >= 1
                sig.inventory_score = 0.8 if in_stock else 0.2
                return MatchedItem(
                    item_id=pid,
                    item_name=pat.get("item_name", ""),
                    price=amount,
                    qty=1,
                    confidence=sig.weighted_total,
                    source="pattern",
                    in_stock=in_stock,
                    current_qty=inv_item.get("current_qty", 0),
                )

        # ── Unmatched ─────────────────────────────────────────────────────────
        return None

    def _asr_name_match_score(
        self, item: dict, trans_words: list[str], norm_transcript: str
    ) -> float:
        """Return best name similarity score for an item against the transcript."""
        item_norm = _normalize(item.get("name") or "")
        if not item_norm or not norm_transcript:
            return 0.0

        # Direct substring match
        if item_norm in norm_transcript:
            return 1.0

        # Alias check
        aliases = item.get("aliases") or []
        for alias in aliases:
            alias_norm = _normalize(str(alias))
            if alias_norm and alias_norm in norm_transcript:
                return 0.90

        # First-word match (e.g. "Parle" matches "Parle G")
        first_word = item_norm.split()[0]
        if len(first_word) > 3 and first_word in norm_transcript:
            return 0.70

        # Fuzzy word-level match
        best = 0.0
        for w in trans_words:
            if len(w) > 3:
                s = _similarity(w, item_norm.split()[0])
                if s > best:
                    best = s
        if best >= FUZZY_MIN_SIM:
            return best * 0.85  # discount fuzzy

        return 0.0

    def _detect_qty(
        self, item: dict, trans_words: list[str], norm_transcript: str
    ) -> int:
        """Detect quantity from adjacent words in transcript."""
        item_norm = _normalize(item.get("name") or "").split()
        if not item_norm or not trans_words:
            return 1
        anchor = item_norm[0]
        for idx, w in enumerate(trans_words):
            if w == anchor or _similarity(w, anchor) >= 0.80:
                return _find_qty_near(trans_words, idx)
        return 1


# ──────────────────────────────────────────────────────────────────────────────
# Convenience serializers
# ──────────────────────────────────────────────────────────────────────────────
def matched_item_to_dict(m: MatchedItem) -> dict:
    return {
        "item_id": m.item_id,
        "item_name": m.item_name,
        "price": m.price,
        "qty": m.qty,
        "confidence": m.confidence,
        "source": m.source,
        "in_stock": m.in_stock,
        "current_qty": m.current_qty,
        "signals": {
            "asr_price": round(m.signals.asr_price_score, 3),
            "asr_name": round(m.signals.asr_name_score, 3),
            "inventory": round(m.signals.inventory_score, 3),
            "pattern": round(m.signals.pattern_score, 3),
        },
    }


def confidence_result_to_dict(r: ConfidenceResult) -> dict:
    return {
        "score": r.score,
        "decision": r.decision,
        "summary": r.summary,
        "matched_items": [matched_item_to_dict(m) for m in r.matched_items],
        "unmatched_amounts": r.unmatched_amounts,
        "signals": {
            "asr_price": round(r.signals.asr_price_score, 3),
            "asr_name": round(r.signals.asr_name_score, 3),
            "inventory": round(r.signals.inventory_score, 3),
            "pattern": round(r.signals.pattern_score, 3),
            "weighted_total": round(r.signals.weighted_total, 3),
        },
        "thresholds": {
            "high": DEFAULT_THRESHOLD_HIGH,
            "medium": DEFAULT_THRESHOLD_MEDIUM,
        },
    }


# ──────────────────────────────────────────────────────────────────────────────
# Explainable Confidence Engine (Smart Reconciliation)
# ──────────────────────────────────────────────────────────────────────────────

EXPLAINABLE_WEIGHTS = {
    "asr": 40,
    "price": 25,
    "inventory": 15,
    "sales": 10,
    "time": 10
}

HINGLISH_SYNONYMS = {
    "doodh": "milk", "dudh": "milk", "malk": "milk", "milak": "milk",
    "biskut": "biscuit", "biscut": "biscuit", "biskit": "biscuit",
    "cheeni": "sugar", "chini": "sugar", "sakkar": "sugar",
    "tel": "oil", "tael": "oil", "tail": "oil",
    "paani": "water", "pani": "water",
    "dahi": "curd", "dahee": "curd", "yogurt": "curd",
    "makhan": "butter", "makkhan": "butter",
    "sabun": "soap", "saboon": "soap",
    "namak": "salt", "nammak": "salt",
    "atta": "flour", "aata": "flour",
    "chai": "tea", "chaaye": "tea", "chaye": "tea",
    "chawal": "rice",
    "anda": "egg", "ande": "egg",
    "dal": "pulses", "daal": "pulses",
    "haldi": "turmeric",
    "mirch": "chilli", "mirchi": "chilli",
    "ghee": "ghee", "ghi": "ghee",
}

class PredictionResult(dict):
    """Hybrid object for prediction that functions as string product name AND dictionary for legacy code."""
    def __init__(self, name: str, confidence: int, status: str, p_id: Any, price: float, emoji: str):
        super().__init__({
            "name": name,
            "confidence": confidence,
            "status": status,
            "id": p_id,
            "price": price,
            "emoji": emoji
        })
        self.name = str(name)

    def __str__(self):
        return self.name

    def __repr__(self):
        return repr(self.name)

    def __eq__(self, other):
        if isinstance(other, str):
            return self.name == other
        return super().__eq__(other)


class ExplainableConfidenceEngine:
    """
    Production-ready Explainable Confidence Score Engine for KhataSnap Calculator AI.
    
    4-Stage Filter -> Score Pipeline:
      Stage 1 — Hard Elimination: current_qty <= 0 products eliminated completely.
      Stage 2 — Price Validation: abs(selling_price - entered_price) <= price_tolerance (default 2.0).
      Stage 3 — ASR Semantic Matching: RapidFuzz, phonetic, Hinglish dictionary matching.
      Stage 4 — Context Scoring: ASR (40) + Price (25) + Inventory (15) + Sales (10) + Time (10) = 100 max.
    """


    def __init__(self, weights: dict[str, int] | None = None):
        self.weights = dict(EXPLAINABLE_WEIGHTS)
        if weights:
            self.weights.update(weights)

    def _normalize_text(self, text: str) -> str:
        if not text:
            return ""
        text = text.lower()
        text = re.sub(r"[^\w\s]", "", text)
        return re.sub(r"\s+", " ", text).strip()

    def calculate_asr_score(self, item_name: str, aliases: list[str], asr_transcript: str) -> tuple[int, list[str]]:
        max_weight = self.weights.get("asr", 40)
        norm_trans = self._normalize_text(asr_transcript)
        norm_name  = self._normalize_text(item_name)

        if not norm_trans or not norm_name:
            return 0, []

        explanations = []
        best_ratio = 0.0
        detected_keyword = ""

        # 1. Expand Hinglish synonyms in transcript
        trans_words = norm_trans.split()
        expanded_words = []
        for w in trans_words:
            expanded_words.append(w)
            if w in HINGLISH_SYNONYMS:
                expanded_words.append(HINGLISH_SYNONYMS[w])
                detected_keyword = w
        expanded_trans = " ".join(expanded_words)

        all_names = [norm_name] + [self._normalize_text(str(a)) for a in (aliases or []) if a]

        for target_name in all_names:
            if not target_name:
                continue

            # Exact name or alias in transcript
            if target_name in norm_trans or target_name in expanded_trans:
                best_ratio = 1.0
                if detected_keyword:
                    explanations.append(f"Detected keyword '{detected_keyword}'")
                else:
                    explanations.append(f"Matched keyword '{target_name}' in voice")
                break

            # Word level matching
            name_words = [w for w in target_name.split() if len(w) > 2]
            if name_words:
                matches = sum(1 for w in name_words if w in norm_trans or w in expanded_trans)
                ratio = matches / len(name_words)
                if ratio > best_ratio:
                    best_ratio = ratio

            # Fuzzy Levenshtein
            for tw in trans_words:
                if len(tw) > 2:
                    for nw in target_name.split():
                        if len(nw) > 2:
                            sim = _similarity(tw, nw)
                            if tw in HINGLISH_SYNONYMS and HINGLISH_SYNONYMS[tw] in target_name:
                                sim = 1.0
                                detected_keyword = tw
                            if sim > best_ratio:
                                best_ratio = sim

        score = int(round(best_ratio * max_weight))
        if score > 0 and not explanations:
            if detected_keyword:
                explanations.append(f"Detected keyword '{detected_keyword}'")
            else:
                explanations.append(f"Speech transcript matches '{item_name}'")

        return min(max_weight, max(0, score)), explanations

    def calculate_price_score(self, entered_price: float, product_price: float) -> tuple[int, list[str]]:
        max_weight = self.weights.get("price", 25)
        diff = abs(entered_price - product_price)
        # Decay formula: max(0, 25 - 5 * abs_diff)
        raw_score = max_weight - (5.0 * diff)
        score = int(round(max(0.0, min(float(max_weight), raw_score))))

        explanations = []
        if diff == 0:
            explanations.append(f"₹{int(entered_price) if entered_price == int(entered_price) else entered_price} exactly matches the product price")
        elif diff <= 1.0:
            explanations.append(f"₹{entered_price} is within ₹1 of product price ₹{product_price}")
        elif score > 0:
            explanations.append(f"₹{entered_price} matches near product price ₹{product_price}")

        return score, explanations

    def calculate_inventory_score(self, current_qty: int) -> tuple[int, bool, list[str]]:
        max_weight = self.weights.get("inventory", 15)
        if current_qty <= 0:
            return 0, False, ["Product out of stock"]
        return max_weight, True, ["Item is available in inventory"]

    def calculate_sales_score(self, sales_count: int, max_sales_count: int) -> tuple[int, list[str]]:
        max_weight = self.weights.get("sales", 10)
        if max_sales_count <= 0 or sales_count <= 0:
            return 0, []

        ratio = min(1.0, sales_count / max_sales_count)
        score = int(round(ratio * max_weight))

        explanations = []
        if score >= 7:
            explanations.append("Frequently sold product in shop history")
        elif score >= 3:
            explanations.append("Regularly purchased product")

        return score, explanations

    def calculate_time_score(self, hourly_sales: int, max_hourly_sales: int, current_hour: int) -> tuple[int, list[str]]:
        max_weight = self.weights.get("time", 10)
        if max_hourly_sales <= 0 or hourly_sales <= 0:
            return 0, []

        ratio = min(1.0, hourly_sales / max_hourly_sales)
        score = int(round(ratio * max_weight))

        explanations = []
        if score >= 7:
            if 6 <= current_hour <= 11:
                explanations.append("Frequently sold in morning hours")
            elif 12 <= current_hour <= 16:
                explanations.append("Frequently sold in afternoon hours")
            elif 17 <= current_hour <= 22:
                explanations.append("Frequently sold in evening hours")
            else:
                explanations.append(f"High purchasing pattern at {current_hour}:00")
        elif score >= 3:
            explanations.append(f"Popular purchase around {current_hour}:00")

        return score, explanations

    def predict(
        self,
        entered_price: float,
        asr_transcript: str = "",
        inventory_items: list[dict] | None = None,
        historical_sales_data: dict | None = None,
        current_hour: int | None = None,
        price_tolerance: float = 2.0,
    ) -> dict[str, Any]:
        """
        4-Stage Filter -> Score Pipeline for KhataSnap Calculator AI:
        Stage 1 — Hard Elimination: Remove every product where current_qty <= 0.
        Stage 2 — Price Validation: Keep products whose selling_price is within tolerance abs(p - price) <= 2.
        Stage 3 — ASR Semantic Matching: RapidFuzz / Phonetic / Hinglish category matching.
        Stage 4 — Context Scoring: ASR (40) + Price (25) + Inventory (15) + Sales (10) + Time (10) = 100.
        """
        if current_hour is None:
            current_hour = datetime.now().hour

        items = inventory_items
        sales_data = historical_sales_data or {}

        if items is None:
            # Load active products directly from DB if available
            try:
                from database import get_conn
                conn = get_conn()
                try:
                    cur = conn.cursor()
                    cur.execute("""
                        SELECT p.id, p.name, p.selling_price, p.current_qty, p.emoji,
                               group_concat(pa.alias, '|||') AS alias_blob
                        FROM products p
                        LEFT JOIN product_aliases pa ON pa.product_id = p.id
                        WHERE p.is_active = 1
                        GROUP BY p.id
                    """)
                    items = []
                    for row in cur.fetchall():
                        d = dict(row)
                        blob = d.pop('alias_blob', '') or ''
                        d['aliases'] = [a for a in blob.split('|||') if a] if blob else []
                        items.append(d)

                    # Fetch sales history stats per item
                    cur.execute("""
                        SELECT item_id, SUM(selection_count) as total_sales,
                               SUM(CASE WHEN hour_of_day = ? THEN selection_count ELSE 0 END) as hour_sales
                        FROM price_item_patterns
                        GROUP BY item_id
                    """, (current_hour,))
                    for r in cur.fetchall():
                        sales_data[str(r['item_id'])] = {
                            'total_sales': r['total_sales'] or 0,
                            'hour_sales': r['hour_sales'] or 0,
                        }
                finally:
                    conn.close()
            except Exception:
                items = []

        items = items or []

        # ── Stage 1: Hard Elimination ──────────────────────────────────────────────
        # Remove every product where current_qty <= 0. Out-of-stock items NEVER participate in scoring.
        stage1_items = [it for it in items if int(it.get("current_qty") or 0) > 0]

        if not stage1_items:
            return {
                "prediction": "No matching product in stock",
                "confidence": 0,
                "status": "LOW",
                "reasons": {"asr": 0, "price": 0, "inventory": 0, "sales": 0, "time": 0},
                "explanation": ["No in-stock products available in inventory."],
                "alternatives": []
            }

        entered_price_f = float(entered_price or 0)

        # ── Stage 2: Price Validation & Filtering ──────────────────────────────────
        # Keep products within tolerance abs(selling_price - entered_price) <= price_tolerance
        stage2_items = stage1_items
        if entered_price_f > 0:
            tol_matches = [
                it for it in stage1_items
                if abs(float(it.get("selling_price") or it.get("price") or 0) - entered_price_f) <= price_tolerance
            ]
            if tol_matches:
                stage2_items = tol_matches

        # ── Stage 3 & 4: ASR Semantic Matching & Context Scoring ───────────────────
        max_sales_count = max([sales_data.get(str(it.get('id')), {}).get('total_sales', 0) for it in stage2_items] + [0])
        max_hourly_sales = max([sales_data.get(str(it.get('id')), {}).get('hour_sales', 0) for it in stage2_items] + [0])

        candidates = []

        for item in stage2_items:
            p_id = item.get("id")
            name = item.get("name", "Unknown Item")
            price = float(item.get("selling_price") or item.get("price") or 0)
            stock = int(item.get("current_qty") or 0)
            aliases = item.get("aliases") or []
            emoji = item.get("emoji", "📦")

            inv_score, is_avail, inv_expl = self.calculate_inventory_score(stock)
            asr_score, asr_expl = self.calculate_asr_score(name, aliases, asr_transcript)
            price_score, price_expl = self.calculate_price_score(entered_price_f, price)

            item_sales_info = sales_data.get(str(p_id), {})
            s_count = item_sales_info.get("total_sales", 0)
            sales_score, sales_expl = self.calculate_sales_score(s_count, max_sales_count)

            h_count = item_sales_info.get("hour_sales", 0)
            time_score, time_expl = self.calculate_time_score(h_count, max_hourly_sales, current_hour)

            total_confidence = min(100, max(0, asr_score + price_score + inv_score + sales_score + time_score))

            explanations = []
            explanations.extend(asr_expl)
            explanations.extend(price_expl)
            explanations.extend(inv_expl)
            explanations.extend(sales_expl)
            explanations.extend(time_expl)

            candidates.append({
                "id": p_id,
                "name": name,
                "price": price,
                "emoji": emoji,
                "confidence": total_confidence,
                "reasons": {
                    "asr": asr_score,
                    "price": price_score,
                    "inventory": inv_score,
                    "sales": sales_score,
                    "time": time_score,
                    "salesPattern": sales_score,
                    "timePattern": time_score
                },
                "explanation": explanations,
            })

        # Rank candidates by confidence descending
        candidates.sort(key=lambda x: x["confidence"], reverse=True)

        top_match = candidates[0]
        conf = top_match["confidence"]

        if conf >= 90:
            status = "AUTO_SELECT"
        elif conf >= 75:
            status = "ONE_TAP_CONFIRM"
        else:
            status = "LOW"


        prediction_obj = PredictionResult(
            name=top_match["name"],
            confidence=conf,
            status=status,
            p_id=top_match["id"],
            price=top_match["price"],
            emoji=top_match["emoji"]
        )

        reasons = {
            "asr": top_match["reasons"]["asr"],
            "price": top_match["reasons"]["price"],
            "inventory": top_match["reasons"]["inventory"],
            "sales": top_match["reasons"]["sales"],
            "time": top_match["reasons"]["time"],
            "salesPattern": top_match["reasons"]["sales"],
            "timePattern": top_match["reasons"]["time"]
        }

        return {
            "prediction": prediction_obj,
            "confidence": conf,
            "status": status,
            "reasons": reasons,
            "explanation": top_match["explanation"],
            "alternatives": [
                {
                    "name": alt["name"],
                    "confidence": alt["confidence"],
                    "id": alt["id"],
                    "price": alt["price"]
                }
                for alt in candidates[1:3]
            ],
            "candidates": candidates
        }



    def record_feedback(
        self,
        product_id: int | str,
        product_name: str,
        price: float | int,
        hour: int | None = None,
        day: int | None = None
    ) -> bool:
        """
        Learning feedback: Updates historical sales/time statistics silently when user confirms
        or selects a product.
        """
        try:
            from database import get_conn
            now = datetime.now()
            h = hour if hour is not None else now.hour
            d = day if day is not None else now.weekday()
            p = int(round(float(price))) if price else 0

            conn = get_conn()
            try:
                row = conn.execute("""
                    SELECT id FROM price_item_patterns
                    WHERE item_id=? AND hour_of_day=? AND day_of_week=?
                """, (product_id, h, d)).fetchone()

                if row:
                    conn.execute("""
                        UPDATE price_item_patterns
                        SET selection_count = selection_count + 1, last_selected_at = datetime('now')
                        WHERE id=?
                    """, (row[0],))
                else:
                    conn.execute("""
                        INSERT INTO price_item_patterns
                        (price, item_id, item_name, hour_of_day, day_of_week, selection_count, last_selected_at)
                        VALUES (?, ?, ?, ?, ?, 1, datetime('now'))
                    """, (p, product_id, product_name, h, d))

                conn.commit()
                return True
            finally:
                conn.close()
        except Exception:
            return False


# ──────────────────────────────────────────────────────────────────────────────
# Quick smoke-test
# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    engine = ConfidenceEngine()
    inv = [
        {"id": 1, "name": "Parle G", "selling_price": 10, "current_qty": 50},
        {"id": 2, "name": "Maggi",   "selling_price": 12, "current_qty": 30},
        {"id": 3, "name": "Lays",    "selling_price": 20, "current_qty": 0},
    ]
    r = engine.score(
        calculator_amounts=[10, 12, 20],
        asr_transcript="parle g aur maggi do packet aur lays",
        inventory_snapshot=inv,
    )
    import json
    print(json.dumps(confidence_result_to_dict(r), indent=2))

    # Explainable engine smoke test
    exp_engine = ExplainableConfidenceEngine()
    exp_inv = [
        {"id": 101, "name": "Amul Taaza 500ml", "selling_price": 32, "current_qty": 40},
        {"id": 102, "name": "Mother Dairy",     "selling_price": 30, "current_qty": 25},
        {"id": 103, "name": "Toned Milk",       "selling_price": 32, "current_qty": 0}, # Stock = 0 eliminated
    ]
    pred = exp_engine.predict(entered_price=32, asr_transcript="doodh", inventory_items=exp_inv)
    print("\nExplainable Engine Prediction:")
    print(json.dumps(pred, indent=2))

