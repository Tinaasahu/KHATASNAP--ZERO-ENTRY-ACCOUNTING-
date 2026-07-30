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