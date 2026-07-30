import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any


# Hardcoded catalog (source of truth for mapping)
CATALOG = [
    {"standard_name": "Salt",  "brand": "Tata",       "variants": ["1kg", "500g"]},
    {"standard_name": "Atta",  "brand": "Aashirvaad", "variants": ["5kg", "10kg"]},
    {"standard_name": "Milk",  "brand": "Amul",       "variants": ["500ml", "1L"]},
    {"standard_name": "Oil",   "brand": "Fortune",    "variants": ["1L", "5L"]},
    {"standard_name": "Sugar", "brand": "",           "variants": ["1kg", "loose"]},
]


_SPACE_RE = re.compile(r"\s+")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9\s]+")


def _norm(s: str) -> str:
    s = (s or "").lower()
    # Hinglish normalization
    s = s.replace("namak", "salt").replace("namk", "salt").replace("namkeen", "salt")
    s = s.replace("chini", "sugar").replace("shugar", "sugar").replace("suger", "sugar").replace("sugr", "sugar")
    s = s.replace("doodh", "milk").replace("dudh", "milk")
    s = s.replace("tel", "oil").replace("teel", "oil")
    # Light cleanup
    s = _NON_ALNUM_RE.sub(" ", s)
    s = _SPACE_RE.sub(" ", s).strip()
    return s


def _skeleton(s: str) -> str:
    """Cheap phonetic-ish key: remove vowels and spaces."""
    s = _norm(s)
    return re.sub(r"[aeiou\s]", "", s)


def _ratio(a: str, b: str) -> float:
    a = a.strip()
    b = b.strip()
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _extract_variant(raw: str) -> str:
    t = _norm(raw)
    # Prefer explicit pack sizes
    m = re.search(r"\b(\d+(?:\.\d+)?)\s*(kg|g|l|ml)\b", t)
    if m:
        num = m.group(1)
        unit = m.group(2)
        # normalize case
        if unit == "kg":
            return f"{num}kg" if num.endswith(".0") is False else f"{int(float(num))}kg"
        if unit == "g":
            return f"{int(float(num))}g"
        if unit == "l":
            return f"{num}L" if num.endswith(".0") is False else f"{int(float(num))}L"
        if unit == "ml":
            return f"{int(float(num))}ml"

    # Common keywords
    if "loose" in t or "khula" in t:
        return "loose"
    return ""


@dataclass
class CatalogMatch:
    standard_name: str = ""
    brand: str = ""
    variant: str = ""
    confidence: float = 0.0
    needs_user_selection: bool = False
    is_unmapped: bool = False


def map_to_catalog(raw_text: str) -> CatalogMatch:
    raw_text = raw_text or ""
    n = _norm(raw_text)
    sk = _skeleton(raw_text)
    detected_variant = _extract_variant(raw_text)

    best: dict[str, Any] | None = None
    best_score = 0.0

    for entry in CATALOG:
        std = entry["standard_name"]
        brand = entry["brand"]

        target = _norm(" ".join([brand, std]).strip())
        score = max(_ratio(n, target), _ratio(sk, _skeleton(target)))

        # Boost if we see strong brand token
        if brand and _norm(brand) in n:
            score = max(score, 0.85)

        # Boost if we see the standard_name token
        if _norm(std) and _norm(std) in n:
            score = max(score, 0.85)

        if score > best_score:
            best_score = score
            best = entry

    # Require >= 0.80 match
    if not best or best_score < 0.80:
        return CatalogMatch(is_unmapped=True, confidence=min(0.69, best_score))

    variants = best.get("variants") or []
    chosen_variant = ""
    needs_sel = False

    if detected_variant:
        # map casing/format to catalog variants if compatible
        dv = detected_variant
        # special: 1l vs 1L
        if dv.lower().endswith("l"):
            dv = dv[:-1] + "L"
        # exact or close match
        if dv in variants:
            chosen_variant = dv
        else:
            # allow "1000ml" -> "1L" style mapping
            if dv == "1000ml" and "1L" in variants:
                chosen_variant = "1L"
            elif dv == "500ml" and "500ml" in variants:
                chosen_variant = "500ml"
            else:
                # Detected a variant, but not in allowed variants — ask user
                needs_sel = True
    else:
        # No variant detected: only safe if exactly one variant exists
        if len(variants) == 1:
            chosen_variant = variants[0]
        elif len(variants) > 1:
            needs_sel = True

    return CatalogMatch(
        standard_name=best["standard_name"],
        brand=best["brand"],
        variant=chosen_variant,
        confidence=round(best_score, 3),
        needs_user_selection=needs_sel,
        is_unmapped=False,
    )

