"""
KhataSnap - Helper Utilities
SKU generation, fuzzy matching, transaction ID, profit margin etc.
"""

import re
import uuid
from datetime import datetime


def generate_sku(name, brand=''):
    """Auto-generate a unique SKU from product name + brand + timestamp."""
    base = (brand[:2] if brand else name[:2]).upper()
    slug = re.sub(r'[^A-Z0-9]', '', name.upper())[:4]
    ts   = datetime.now().strftime('%m%d%H%M')
    return f"{base}-{slug}-{ts}"


def generate_txn_id(source='SYS'):
    """Generate a unique transaction ID."""
    return f"{source.upper()}-{uuid.uuid4().hex[:10].upper()}"


def calc_profit_margin(purchase_price, selling_price):
    """Calculate profit margin percentage."""
    if not purchase_price or purchase_price == 0:
        return 0
    return round(((selling_price - purchase_price) / purchase_price) * 100, 2)


def normalize(text):
    """Normalize text for fuzzy matching."""
    return re.sub(r'[^a-z0-9 ]', '', str(text).lower().strip())


def fuzzy_match(query, candidates):
    """
    Smart 3-level fuzzy matching.
    Returns (matched_item, confidence) or (None, 0)
    candidates = list of dicts with 'id', 'name', 'aliases'
    """
    q = normalize(query)

    # Level 1: exact match → confidence 1.0
    for c in candidates:
        names = [normalize(c['name'])] + [normalize(a) for a in (c.get('aliases') or [])]
        if q in names:
            return c, 1.0

    # Level 2: candidate contains query → confidence 0.85
    for c in candidates:
        names = [normalize(c['name'])] + [normalize(a) for a in (c.get('aliases') or [])]
        if any(q in n for n in names):
            return c, 0.85

    # Level 3: query contains candidate → confidence 0.70
    for c in candidates:
        names = [normalize(c['name'])] + [normalize(a) for a in (c.get('aliases') or [])]
        if any(n in q for n in names):
            return c, 0.70

    # Level 4: word overlap → confidence 0.55
    q_words = set(q.split())
    for c in candidates:
        names = [normalize(c['name'])] + [normalize(a) for a in (c.get('aliases') or [])]
        for n in names:
            n_words = set(n.split())
            overlap = q_words & n_words
            if len(overlap) >= 1 and len(overlap) / max(len(q_words), len(n_words)) >= 0.5:
                return c, 0.55

    return None, 0
