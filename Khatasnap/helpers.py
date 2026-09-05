"""
KhataSnap — Helper Utilities
SKU generation, fuzzy matching, transaction ID, profit margin.
"""
import re
import uuid
from datetime import datetime


def generate_sku(name, brand=''):
    base = (brand[:2] if brand else name[:2]).upper()
    slug = re.sub(r'[^A-Z0-9]', '', name.upper())[:4]
    ts   = datetime.now().strftime('%m%d%H%M')
    return f"{base}-{slug}-{ts}"


def generate_txn_id(source='SYS'):
    return f"{source.upper()}-{uuid.uuid4().hex[:10].upper()}"


def generate_bill_no():
    return f"BILL-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"


def calc_profit_margin(purchase_price, selling_price):
    if not purchase_price or purchase_price == 0:
        return 0
    return round(((selling_price - purchase_price) / purchase_price) * 100, 2)


import difflib

def normalize(text):
    if text is None:
        return ""
    q = re.sub(r'[,.!?;:()\[\]\"\']', '', str(text).lower().strip())
    q = re.sub(r'\b(grams|gram|gm)\b', 'g', q)
    q = re.sub(r'\b(kilograms|kilo|kilogram|kgs)\b', 'kg', q)
    q = re.sub(r'\b(milliliters|milliliter)\b', 'ml', q)
    q = re.sub(r'\b(liters|liter|litres|litre)\b', 'l', q)
    q = re.sub(r'(\d+)\s+(g|kg|ml|l)\b', r'\1\2', q)
    return q


def fuzzy_match(query, candidates, min_confidence=0.0):
    """
    4-level fuzzy matching.
    candidates = list of dicts with 'id', 'name', 'aliases' (list of strings)
    Returns (matched_item, confidence) or (None, 0)
    """
    q = normalize(query)
    if not q:
        return None, 0

    # Level 1: exact match → 1.0
    for c in candidates:
        names = [normalize(c['name'])] + [normalize(a) for a in (c.get('aliases') or [])]
        if q in names:
            if 1.0 >= min_confidence: return c, 1.0

    # Level 2: query contained in candidate → 0.85
    for c in candidates:
        names = [normalize(c['name'])] + [normalize(a) for a in (c.get('aliases') or [])]
        if any(q in n for n in names):
            if 0.85 >= min_confidence: return c, 0.85

    # Level 3: candidate contained in query → 0.70
    for c in candidates:
        names = [normalize(c['name'])] + [normalize(a) for a in (c.get('aliases') or [])]
        if any(n in q for n in names):
            if 0.70 >= min_confidence: return c, 0.70

    # Level 4: word overlap ≥ 50% or difflib similarity ≥ 0.75 → 0.55
    q_words = set(q.split())
    for c in candidates:
        names = [normalize(c['name'])] + [normalize(a) for a in (c.get('aliases') or [])]
        for n in names:
            n_words = set(n.split())
            overlap  = q_words & n_words
            if len(overlap) >= 1 and len(overlap) / max(len(q_words), len(n_words)) >= 0.5:
                if 0.55 >= min_confidence: return c, 0.55
            
            # Sub-word fuzzy matching for typos like "maggie" vs "maggi"
            for qw in q_words:
                for nw in n_words:
                    if len(qw) > 3 and len(nw) > 3:
                        sim = difflib.SequenceMatcher(None, qw, nw).ratio()
                        if sim >= 0.8:
                            if 0.55 >= min_confidence: 
                                c['matched_alias'] = nw
                                return c, 0.55

    # Level 5: prefix match — handles OCR typos like "parleg" → "Parle G" → 0.45
    for c in candidates:
        names = [normalize(c['name'])] + [normalize(a) for a in (c.get('aliases') or [])]
        for n in names:
            first_word = n.split()[0] if n.split() else ''
            if len(first_word) >= 4 and (q.startswith(first_word) or first_word.startswith(q)):
                if 0.45 >= min_confidence: return c, 0.45
            for nw in n.split():
                if len(nw) >= 4 and q.startswith(nw):
                    if 0.45 >= min_confidence: return c, 0.45

    return None, 0


# ── Inventory Voice Command Parser ───────────────────────────────────────────

HINGLISH_INVENTORY_SYNONYMS = {
    "doodh": "milk", "dudh": "milk", "malk": "milk",
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

ADD_KEYWORDS = [
    "add", "stock in", "restock", "received", "purchase", "plus", "put", "increase",
    "added", "buy", "bought", "in", "incoming", "fill", "refill", "jodo", "daalo",
    "laya", "aaya", "banao", "rakho", "aagaya", "badhao", "aaya hai", "khareeda"
]

DEDUCT_KEYWORDS = [
    "deduct", "remove", "sell", "sold", "reduce", "minus", "hatao", "kam karo",
    "nikalo", "gaya", "bika", "take out", "substract", "sub", "less", "spent",
    "use", "used", "out", "nikal do", "kam", "becha", "bech diya", "de diya", "diya"
]

QUANTITY_WORDS = {
    "ek": 1, "do": 2, "teen": 3, "char": 4, "paanch": 5, "panch": 5,
    "chhe": 6, "che": 6, "saat": 7, "aath": 8, "nau": 9, "das": 10,
    "gyarah": 11, "barah": 12, "pandrah": 15, "bees": 20, "pachis": 25,
    "tees": 30, "chalis": 40, "pachas": 50, "so": 100, "sau": 100,
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20,
    "thirty": 30, "forty": 40, "fifty": 50, "hundred": 100,
    "half": 0.5, "couple": 2, "dozen": 12,
}

def parse_inventory_voice_command(raw_transcript: str, products: list[dict]) -> list[dict]:
    """
    Parses an inventory voice command transcript into a list of structured item actions.
    Supports Hinglish synonyms, action keyword detection, quantity extraction, and multi-item phrases.
    """
    if not raw_transcript:
        return []

    norm_full = normalize(raw_transcript)
    if not norm_full:
        return []

    sub_phrases = re.split(r'\b(and|aur|comma|;\n)\b', norm_full)
    sub_phrases = [sp.strip() for sp in sub_phrases if sp and sp not in {'and', 'aur', 'comma', ';'}]
    if not sub_phrases:
        sub_phrases = [norm_full]

    results = []

    for phrase in sub_phrases:
        words = phrase.split()
        if not words:
            continue

        expanded_words = []
        for w in words:
            expanded_words.append(w)
            if w in HINGLISH_INVENTORY_SYNONYMS:
                expanded_words.append(HINGLISH_INVENTORY_SYNONYMS[w])
        expanded_phrase = " ".join(expanded_words)

        action = None
        for kw in ADD_KEYWORDS:
            if re.search(r'\b' + re.escape(kw) + r'\b', phrase) or re.search(r'\b' + re.escape(kw) + r'\b', expanded_phrase):
                action = "add"
                break
        if action is None:
            for kw in DEDUCT_KEYWORDS:
                if re.search(r'\b' + re.escape(kw) + r'\b', phrase) or re.search(r'\b' + re.escape(kw) + r'\b', expanded_phrase):
                    action = "deduct"
                    break
        if action is None:
            action = "add"

        qty = 1
        numbers = re.findall(r'\b\d+\b', phrase)
        if numbers:
            qty = int(numbers[0])
        else:
            for w in words:
                if w in QUANTITY_WORDS:
                    qty = QUANTITY_WORDS[w]
                    break

        clean_words = []
        for w in words:
            if w in ADD_KEYWORDS or w in DEDUCT_KEYWORDS or w in QUANTITY_WORDS or w.isdigit() or w in {"packet", "packets", "box", "boxes", "piece", "pieces", "kg", "kgs", "g", "gm", "ml", "l", "litre", "litres", "bottle", "bottles", "item", "items"}:
                continue
            clean_words.append(w)

        search_query = " ".join(clean_words) if clean_words else phrase

        sq_words = search_query.split()
        for w in list(sq_words):
            if w in HINGLISH_INVENTORY_SYNONYMS:
                sq_words.append(HINGLISH_INVENTORY_SYNONYMS[w])
        search_query_expanded = " ".join(sq_words)

        best_match = None
        best_conf = 0.0

        for p in products:
            m1, c1 = fuzzy_match(search_query_expanded, [p], min_confidence=0.30)
            m2, c2 = fuzzy_match(expanded_phrase, [p], min_confidence=0.30)
            m3, c3 = fuzzy_match(search_query, [p], min_confidence=0.30)

            m = m1 or m2 or m3
            c = max(c1, c2, c3)
            if m and c > best_conf:
                best_match = m
                best_conf = c

        if best_match:
            curr_qty = int(best_match.get("current_qty") or 0)
            new_qty = (curr_qty + qty) if action == "add" else max(0, curr_qty - qty)
            results.append({
                "action": action,
                "product_id": best_match["id"],
                "product_name": best_match["name"],
                "qty": qty,
                "current_qty": curr_qty,
                "new_qty": new_qty,
                "confidence": round(best_conf, 3)
            })

    return results