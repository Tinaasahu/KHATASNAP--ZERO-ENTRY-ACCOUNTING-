"""
KhataSnap — Pattern Recognition Engine
Learns multidimensional patterns from shopkeeper transactions:
1. Time-of-Day & Day-of-Week probability (Hour windows, Weekdays vs Weekends)
2. Frequency & Recency weighting
3. Market Basket Co-occurrence (Items frequently bought together)
4. ASR Speech + Pattern Fusion (Speech cues boost pattern predictions)
5. Stock-aware prioritization
"""

from __future__ import annotations
import math
import re
from datetime import datetime
from typing import Any
from database import get_conn


def _normalize(text: str) -> str:
    if not text:
        return ""
    text = text.lower()
    text = re.sub(r"[^\w\s]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _speech_keyword_match_score(name_norm: str, norm_speech: str) -> tuple[float, str]:
    if not name_norm or not norm_speech:
        return 0.0, ""

    if name_norm in norm_speech:
        return 1.0, f'Voice: "{name_norm}" heard'

    words = [w for w in name_norm.split() if len(w) > 2 and w not in {"packet", "bottle", "piece", "gm", "kg", "ml", "l"}]
    if not words:
        return 0.0, ""

    matching_words = [w for w in words if w in norm_speech]
    if len(matching_words) == len(words):
        return 1.0, f'Voice: "{name_norm}" heard'
    elif len(matching_words) > 0:
        matched_str = " ".join(matching_words)
        return 0.85, f'Voice: "{matched_str}" heard'

    return 0.0, ""


class PatternRecognitionEngine:
    def __init__(self):
        self._ensure_tables()

    def _ensure_tables(self):
        """Ensure co-occurrence and enhanced pattern tables exist."""
        conn = get_conn()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS item_co_occurrences (
                    id                INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_a_id         INTEGER NOT NULL,
                    item_b_id         INTEGER NOT NULL,
                    co_count          INTEGER DEFAULT 1,
                    last_seen_at      TEXT DEFAULT (datetime('now')),
                    UNIQUE(item_a_id, item_b_id)
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_co_item_a ON item_co_occurrences(item_a_id);")
            conn.commit()
        finally:
            conn.close()

    def record_transaction_patterns(self, entries: list[dict], hour: int | None = None, day: int | None = None):
        """
        Learns from every confirmed transaction:
        - Updates price_item_patterns (price -> item_id frequency with hour & day)
        - Updates item_co_occurrences for all pairs in the cart
        """
        now = datetime.now()
        h = hour if hour is not None else now.hour
        d = day if day is not None else now.weekday()

        resolved_items = []
        conn = get_conn()
        try:
            for e in entries:
                pid = e.get("item_id")
                name = (e.get("item_name") or e.get("name") or "").strip()
                price = int(float(e.get("price") or e.get("value") or 0))

                if pid and price > 0:
                    resolved_items.append((pid, name, price))

                    # Update price_item_patterns
                    row = conn.execute("""
                        SELECT id, selection_count FROM price_item_patterns
                        WHERE price=? AND item_id=? AND hour_of_day=? AND day_of_week=?
                    """, (price, pid, h, d)).fetchone()

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
                        """, (price, pid, name, h, d))

            # Record co-occurrences for multi-item baskets
            n = len(resolved_items)
            for i in range(n):
                for j in range(i + 1, n):
                    id_a, _, _ = resolved_items[i]
                    id_b, _, _ = resolved_items[j]
                    if id_a == id_b:
                        continue
                    # Canonical order
                    first, second = (id_a, id_b) if id_a < id_b else (id_b, id_a)
                    conn.execute("""
                        INSERT INTO item_co_occurrences (item_a_id, item_b_id, co_count, last_seen_at)
                        VALUES (?, ?, 1, datetime('now'))
                        ON CONFLICT(item_a_id, item_b_id) DO UPDATE SET
                            co_count = co_count + 1,
                            last_seen_at = datetime('now')
                    """, (first, second))

            conn.commit()
        except Exception as ex:
            try:
                conn.rollback()
            except Exception:
                pass
        finally:
            conn.close()

    def predict_item(
        self,
        price: float | int,
        hour: int | None = None,
        day: int | None = None,
        active_cart_item_ids: list[int] | None = None,
        asr_transcript: str = "",
        inventory_items: list[dict] | None = None,
    ) -> dict[str, Any]:
        """
        Multimodal prediction for a given price operand.
        Returns the top predicted item, confidence score (0-1), and human-readable explanation.
        """
        price = int(float(price))
        now = datetime.now()
        h = hour if hour is not None else now.hour
        d = day if day is not None else now.weekday()
        cart_ids = set(active_cart_item_ids or [])
        norm_speech = _normalize(asr_transcript or "")

        conn = get_conn()
        try:
            # 1. Fetch matching inventory items for this price
            inv_rows = conn.execute("""
                SELECT p.id, p.name, p.selling_price as price, p.current_qty, p.emoji,
                       GROUP_CONCAT(pa.alias_price, ',') AS alias_prices
                FROM products p
                LEFT JOIN price_aliases pa ON pa.item_id = p.id
                WHERE p.is_active = 1
                GROUP BY p.id
            """).fetchall()

            # 2. Fetch historical pattern records for this price
            pattern_rows = conn.execute("""
                SELECT item_id, item_name, hour_of_day, day_of_week, selection_count, last_selected_at
                FROM price_item_patterns
                WHERE price=?
            """, (price,)).fetchall()

            # 3. Fetch co-occurrence matrix
            co_rows = []
            if cart_ids:
                placeholders = ",".join("?" * len(cart_ids))
                co_rows = conn.execute(f"""
                    SELECT item_a_id, item_b_id, co_count
                    FROM item_co_occurrences
                    WHERE item_a_id IN ({placeholders}) OR item_b_id IN ({placeholders})
                """, list(cart_ids) + list(cart_ids)).fetchall()
        finally:
            conn.close()

        # Build eligible candidate list for this price & speech transcript
        candidates: dict[int, dict] = {}
        for r in inv_rows:
            d_item = dict(r)
            aliases = [int(a.strip()) for a in (d_item.get("alias_prices") or "").split(",") if a.strip().isdigit()]
            name_norm = _normalize(d_item["name"])
            
            # Keyword match check in speech transcript
            s_score, s_reason = _speech_keyword_match_score(name_norm, norm_speech)
            is_speech_keyword_match = s_score >= 0.70

            # Include if price matches OR price alias matches OR spoken keyword matches
            if d_item["price"] == price or price in aliases or is_speech_keyword_match:
                candidates[d_item["id"]] = {
                    "id": d_item["id"],
                    "name": d_item["name"],
                    "price": d_item["price"],
                    "current_qty": d_item["current_qty"] or 0,
                    "emoji": d_item["emoji"] or "📦",
                    "alias_used": price in aliases and d_item["price"] != price,
                    "speech_keyword_match": is_speech_keyword_match,
                }

        # If no direct inventory candidate, check historical items
        for p in pattern_rows:
            pid = p["item_id"]
            if pid and pid not in candidates:
                candidates[pid] = {
                    "id": pid,
                    "name": p["item_name"],
                    "price": price,
                    "current_qty": 0,
                    "emoji": "📦",
                    "alias_used": False,
                    "speech_keyword_match": False,
                }

        if not candidates:
            return {"status": "not_found", "price": price, "candidates": []}

        # Score each candidate using the Prioritized Pipeline:
        # ASR Input Accepted + Entered Price + Keyword Matching + Price Matching = Final Result
        total_patterns = sum(p["selection_count"] for p in pattern_rows) or 1
        scored_candidates = []

        for cid, cand in candidates.items():
            name_norm = _normalize(cand["name"])
            
            # --- 1. ASR Keyword Matching Score ---
            speech_score, speech_reason = _speech_keyword_match_score(name_norm, norm_speech)

            # --- 2. Price Matching Score ---
            price_score = 0.0
            if cand["price"] == price:
                price_score = 1.0
            elif cand.get("alias_used"):
                price_score = 0.90
            elif cand["price"] > 0 and price % cand["price"] == 0:
                price_score = 0.85  # Composite price match (e.g. 2 x 10 = 20)
            elif any(p["item_id"] == cid for p in pattern_rows):
                price_score = 0.70  # Historical pattern for this price
            else:
                price_score = 0.50  # Custom entered price override

            # --- 3. Sub-Signals: Pattern Frequency, Time-of-Day, Co-occurrence ---
            item_pats = [p for p in pattern_rows if p["item_id"] == cid]
            item_total_selections = sum(p["selection_count"] for p in item_pats)
            freq_score = item_total_selections / total_patterns if total_patterns > 0 else 0.0

            time_score = 0.0
            time_matches = 0
            for p in item_pats:
                h_diff = min(abs(p["hour_of_day"] - h), 24 - abs(p["hour_of_day"] - h))
                if h_diff <= 2:
                    day_mult = 1.2 if p["day_of_week"] == d else 0.9
                    time_matches += p["selection_count"] * day_mult
            if item_total_selections > 0:
                time_score = min(1.0, time_matches / item_total_selections)

            affinity_score = 0.0
            if cart_ids:
                aff_count = 0
                for c_row in co_rows:
                    if (c_row["item_a_id"] == cid and c_row["item_b_id"] in cart_ids) or \
                       (c_row["item_b_id"] == cid and c_row["item_a_id"] in cart_ids):
                        aff_count += c_row["co_count"]
                affinity_score = min(1.0, math.log1p(aff_count) / 3.0)

            # Stock availability
            in_stock = cand["current_qty"] > 0
            stock_mult = 1.0 if in_stock else 0.85

            # --- 4. Prioritized Pipeline Fusion Formula ---
            if speech_score >= 0.75 and price_score >= 0.85:
                # Tier 1: ASR Keyword Match + Price Match (Top Priority: 0.95 - 1.0)
                final_score = max(0.95, 0.90 + 0.08 * speech_score + 0.02 * price_score) * stock_mult
                pipeline_stage = "asr_keyword_and_price_match"
            elif speech_score >= 0.75:
                # Tier 2: ASR Keyword Match with Custom Entered Price (High Priority: 0.85 - 0.90)
                final_score = max(0.85, 0.80 + 0.10 * speech_score) * stock_mult
                pipeline_stage = "asr_keyword_match_custom_price"
            elif price_score >= 0.85:
                # Tier 3: Direct Price Match (0.75 - 0.85)
                final_score = (
                    0.50 * price_score
                    + 0.25 * freq_score
                    + 0.15 * time_score
                    + 0.10 * affinity_score
                ) * stock_mult
                if len(candidates) == 1:
                    final_score = max(final_score, 0.95 if in_stock else 0.85)
                pipeline_stage = "direct_price_match"
            else:
                # Tier 4: Pattern & Co-occurrence Match (0.60 - 0.75)
                final_score = (
                    0.45 * freq_score
                    + 0.30 * time_score
                    + 0.25 * affinity_score
                ) * stock_mult
                pipeline_stage = "pattern_match"

            final_score = round(min(1.0, max(0.05, final_score)), 3)

            # Natural language reason matching the prioritized pipeline
            reasons = []
            if speech_reason and price_score >= 0.85:
                reasons.append(f'{speech_reason} (₹{price})')
            elif speech_reason:
                reasons.append(f'{speech_reason} @ entered ₹{price}')
            elif len(candidates) == 1:
                reasons.append("Unique price match")
            elif freq_score >= 0.5:
                reasons.append(f"{int(freq_score * 100)}% historical choice")
            elif time_score >= 0.6:
                reasons.append(f"Frequent at {h % 12 or 12} {'PM' if h >= 12 else 'AM'}")
            elif affinity_score > 0.3:
                reasons.append("Frequently bought together")
            else:
                reasons.append(f"Price match ₹{price}")

            if in_stock:
                reasons.append(f"In Stock ({cand['current_qty']})")

            cand_result = {
                **cand,
                "confidence": final_score,
                "reason": " • ".join(reasons),
                "pipeline_stage": pipeline_stage,
                "scores": {
                    "speech": round(speech_score, 2),
                    "price": round(price_score, 2),
                    "frequency": round(freq_score, 2),
                    "time": round(time_score, 2),
                    "affinity": round(affinity_score, 2),
                }
            }
            scored_candidates.append(cand_result)

        scored_candidates.sort(key=lambda x: x["confidence"], reverse=True)
        top = scored_candidates[0]

        return {
            "status": "auto" if top["confidence"] >= 0.75 else "ambiguous",
            "price": price,
            "best_match": top,
            "candidates": scored_candidates,
            "confidence": top["confidence"],
        }
