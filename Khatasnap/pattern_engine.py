"""
KhataSnap — Pattern Recognition Engine

Determines item prediction based on FOUR (4) Core Constraints:
1. ASR Keyword Matching (Highest Priority) — Matches spoken words like “milk”, “Parle G” with inventory names & aliases.
2. Price + Inventory Validation — Finds products whose price matches AND are currently in stock.
3. Sales Pattern Analysis — Prioritizes items that are historically sold more frequently.
4. Time-based Behavior — Uses hour-of-day trends (e.g. milk: 8–10 AM, bread: morning, cold drinks: evening).
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


import difflib


def _phonetic_norm(text: str) -> str:
    if not text:
        return ""
    t = text.lower()
    # Normalize common Indian phonetic variations: w <-> v, aa <-> a, ee <-> i, oo <-> u, z <-> j
    t = t.replace("w", "v").replace("ee", "i").replace("oo", "u").replace("aa", "a").replace("z", "j")
    t = re.sub(r"[^\w\s]", "", t)
    return re.sub(r"\s+", " ", t).strip()


HINGLISH_SYNONYMS = {
    "doodh": "milk", "dudh": "milk", "milk": "milk",
    "dahi": "curd", "curd": "curd",
    "chini": "sugar", "suger": "sugar", "sugar": "sugar",
    "namak": "salt", "salt": "salt",
    "tel": "oil", "oil": "oil",
    "makhan": "butter", "butter": "butter",
    "chai": "tea", "tea": "tea",
    "paani": "water", "water": "water",
    "sabun": "soap", "soap": "soap",
    "biscut": "biscuit", "biskut": "biscuit", "biscuit": "biscuit",
    "colddrink": "cold drink", "coke": "cold drink", "pepsi": "cold drink", "sprite": "cold drink", "thumsup": "cold drink"
}


def _speech_keyword_match_score(name_norm: str, norm_speech: str) -> tuple[float, str]:
    """
    Constraint 1: ASR Keyword Matching (Highest Priority)
    Supports phonetic normalization (e.g. Aashirvaad <-> aashirwaad), brand priority, and word coverage ratios.
    """
    if not name_norm or not norm_speech:
        return 0.0, ""

    p_norm = _phonetic_norm(name_norm)
    p_speech = _phonetic_norm(norm_speech)

    # 1. Exact string or exact phonetic match
    if p_norm == p_speech:
        return 1.0, f'Voice: "{name_norm}" matched'

    # 2. Hinglish Synonym match
    for syn_key, syn_val in HINGLISH_SYNONYMS.items():
        syn_p = _phonetic_norm(syn_key)
        if syn_p == p_speech and syn_val in p_norm:
            return 0.95, f'Voice: "{syn_key}" ({syn_val}) matched'

    # 3. Token-based phonetic & fuzzy word coverage
    ignore_words = {"packet", "bottle", "piece", "gm", "kg", "ml", "l", "pkt", "pcs"}
    prod_words = [w for w in p_norm.split() if len(w) > 2 and w not in ignore_words]
    speech_words = [w for w in p_speech.split() if len(w) > 2 and w not in ignore_words]

    if not prod_words or not speech_words:
        return 0.0, ""

    matched_prod_words = []
    matched_speech_words = set()

    for pw in prod_words:
        for sw in speech_words:
            if pw == sw or difflib.SequenceMatcher(None, pw, sw).ratio() >= 0.80:
                matched_prod_words.append(pw)
                matched_speech_words.add(sw)
                break

    if not matched_prod_words:
        return 0.0, ""

    # Coverage ratio of spoken query words matched by this product
    speech_coverage = len(matched_speech_words) / len(speech_words)
    product_coverage = len(matched_prod_words) / len(prod_words)

    # Full speech coverage match (e.g. spoken "aashirwaad atta" -> product "Aashirvaad Atta" matches 100% of spoken words!)
    if speech_coverage >= 0.90:
        if product_coverage >= 0.80:
            return 1.0, f'Voice: "{name_norm}" matched'
        else:
            return 0.90, f'Voice: "{name_norm}" matched'

    # Partial speech coverage (e.g. spoken "aashirwaad atta" -> generic product "Atta" only matches 1 of 2 spoken words)
    score = round(0.40 * product_coverage + 0.60 * speech_coverage, 2)
    matched_str = " ".join(matched_prod_words)
    return score, f'Voice: "{matched_str}" matched'




def _get_time_of_day_info(hour: int, name_norm: str) -> tuple[float, str]:
    """
    Constraint 4: Time-based Behavior Domain Rules
    """
    time_window_label = "General Hours"
    domain_boost = 0.0
    
    if 6 <= hour <= 10:
        time_window_label = "Morning Peak (6-11 AM)"
        morning_items = {"milk", "doodh", "curd", "dahi", "bread", "butter", "tea", "chai", "coffee", "egg", "biscuit", "rusk"}
        if any(item_kw in name_norm for item_kw in morning_items):
            domain_boost = 0.85
    elif 11 <= hour <= 15:
        time_window_label = "Afternoon Staples (11 AM-4 PM)"
        afternoon_items = {"rice", "atta", "dal", "oil", "ghee", "salt", "sugar", "spice", "masala"}
        if any(item_kw in name_norm for item_kw in afternoon_items):
            domain_boost = 0.80
    elif 16 <= hour <= 20:
        time_window_label = "Evening Snacks & Drinks (4-9 PM)"
        evening_items = {"drink", "pepsi", "coke", "soda", "chip", "namkeen", "kurkure", "maggi", "chocolate", "biscuit", "snack"}
        if any(item_kw in name_norm for item_kw in evening_items):
            domain_boost = 0.85
    elif 21 <= hour or hour <= 5:
        time_window_label = "Night Session (9 PM-6 AM)"
        night_items = {"milk", "water", "medicine"}
        if any(item_kw in name_norm for item_kw in night_items):
            domain_boost = 0.75
            
    return domain_boost, time_window_label


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
        Multimodal prediction based strictly on 4 core constraints:
        1. ASR Keyword Matching (Highest Priority)
        2. Price + Inventory Validation
        3. Sales Pattern Analysis
        4. Time-based Behavior
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

        # Build candidate list
        candidates: dict[int, dict] = {}
        for r in inv_rows:
            d_item = dict(r)
            aliases = [int(a.strip()) for a in (d_item.get("alias_prices") or "").split(",") if a.strip().isdigit()]
            name_norm = _normalize(d_item["name"])
            
            s_score, s_reason = _speech_keyword_match_score(name_norm, norm_speech)
            is_speech_keyword_match = s_score >= 0.70

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

        # Check historical items
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

        total_patterns = sum(p["selection_count"] for p in pattern_rows) or 1
        scored_candidates = []

        for cid, cand in candidates.items():
            name_norm = _normalize(cand["name"])
            
            # --- CONSTRAINT 1: ASR Keyword Matching (Highest Priority) ---
            speech_score, speech_reason = _speech_keyword_match_score(name_norm, norm_speech)
            is_asr_matched = speech_score >= 0.70

            # --- CONSTRAINT 2: Price + Inventory Validation ---
            price_score = 0.0
            if cand["price"] == price:
                price_score = 1.0
            elif cand.get("alias_used"):
                price_score = 0.90
            elif cand["price"] > 0 and price % cand["price"] == 0:
                price_score = 0.85
            elif any(p["item_id"] == cid for p in pattern_rows):
                price_score = 0.70
            else:
                price_score = 0.50

            in_stock = cand["current_qty"] > 0
            stock_mult = 1.0 if in_stock else 0.15
            price_inv_score = price_score * stock_mult

            # --- CONSTRAINT 3: Sales Pattern Analysis ---
            item_pats = [p for p in pattern_rows if p["item_id"] == cid]
            item_total_selections = sum(p["selection_count"] for p in item_pats)
            freq_score = item_total_selections / total_patterns if total_patterns > 0 else 0.0

            # --- CONSTRAINT 4: Time-based Behavior ---
            time_matches = 0
            for p in item_pats:
                h_diff = min(abs(p["hour_of_day"] - h), 24 - abs(p["hour_of_day"] - h))
                if h_diff <= 2:
                    day_mult = 1.2 if p["day_of_week"] == d else 0.9
                    time_matches += p["selection_count"] * day_mult
            
            hist_time_score = min(1.0, time_matches / item_total_selections) if item_total_selections > 0 else 0.0
            domain_boost, time_window_label = _get_time_of_day_info(h, name_norm)
            time_score = max(hist_time_score, domain_boost)

            # Affinity co-occurrence
            affinity_score = 0.0
            if cart_ids:
                aff_count = 0
                for c_row in co_rows:
                    if (c_row["item_a_id"] == cid and c_row["item_b_id"] in cart_ids) or \
                       (c_row["item_b_id"] == cid and c_row["item_a_id"] in cart_ids):
                        aff_count += c_row["co_count"]
                affinity_score = min(1.0, math.log1p(aff_count) / 3.0)

            # --- PRIORITIZED FUSION FORMULA ---
            if is_asr_matched and price_score >= 0.85:
                # Priority Tier 1: ASR Keyword Match + Price Match (0.95 - 1.0)
                final_score = max(0.95, 0.90 + 0.08 * speech_score + 0.02 * price_score) * (1.0 if in_stock else 0.85)
                pipeline_stage = "asr_keyword_and_price_match"
            elif is_asr_matched:
                # Priority Tier 2: ASR Keyword Match with Custom Price (0.85 - 0.90)
                final_score = max(0.85, 0.80 + 0.10 * speech_score) * (1.0 if in_stock else 0.85)
                pipeline_stage = "asr_keyword_match_custom_price"
            elif price_score >= 0.85:
                # Priority Tier 3: Price + Inventory + Sales & Time Patterns (0.75 - 0.85)
                final_score = (
                    0.45 * price_score
                    + 0.25 * freq_score
                    + 0.20 * time_score
                    + 0.10 * affinity_score
                ) * stock_mult
                if len(candidates) == 1:
                    final_score = max(final_score, 0.95 if in_stock else 0.70)
                pipeline_stage = "direct_price_match"
            else:
                # Priority Tier 4: Pattern & Time Behavior Match (0.50 - 0.75)
                final_score = (
                    0.40 * freq_score
                    + 0.35 * time_score
                    + 0.25 * affinity_score
                ) * stock_mult
                pipeline_stage = "pattern_match"

            final_score = round(min(1.0, max(0.05, final_score)), 3)

            # Build human-readable breakdown explanation
            reasons = []
            if speech_reason:
                reasons.append(speech_reason)
            if price_score >= 0.85:
                reasons.append(f"Price Match ₹{price}")
            if in_stock:
                reasons.append(f"In Stock ({cand['current_qty']})")
            else:
                reasons.append("Out of Stock")
            if freq_score >= 0.4:
                reasons.append(f"{int(freq_score * 100)}% frequent choice")
            if time_score >= 0.6:
                reasons.append(time_window_label)

            constraints_breakdown = {
                "1_asr_keyword_matching": {
                    "constraint": "ASR Keyword Matching",
                    "priority": 1,
                    "status": "Highest Priority",
                    "score": round(speech_score, 2),
                    "matched": is_asr_matched,
                    "reason": speech_reason or "No speech keyword match"
                },
                "2_price_inventory_validation": {
                    "constraint": "Price + Inventory Validation",
                    "priority": 2,
                    "score": round(price_inv_score, 2),
                    "price_matched": price_score >= 0.85,
                    "in_stock": in_stock,
                    "current_qty": cand["current_qty"],
                    "reason": f"Price ₹{price} match • In Stock ({cand['current_qty']})" if in_stock else f"Price ₹{price} match • Out of Stock"
                },
                "3_sales_pattern_analysis": {
                    "constraint": "Sales Pattern Analysis",
                    "priority": 3,
                    "score": round(freq_score, 2),
                    "historical_count": item_total_selections,
                    "reason": f"{item_total_selections} historical sales" if item_total_selections > 0 else "New product"
                },
                "4_time_based_behavior": {
                    "constraint": "Time-based Behavior",
                    "priority": 4,
                    "score": round(time_score, 2),
                    "current_hour": h,
                    "time_window": time_window_label,
                    "reason": f"Trend active for {time_window_label}" if time_score >= 0.5 else f"Hour {h}:00 trend"
                }
            }

            cand_result = {
                **cand,
                "confidence": final_score,
                "reason": " • ".join(reasons),
                "pipeline_stage": pipeline_stage,
                "constraints": constraints_breakdown,
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
            "prediction_constraints": top["constraints"]
        }
