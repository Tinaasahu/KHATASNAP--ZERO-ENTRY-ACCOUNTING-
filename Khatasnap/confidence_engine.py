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
