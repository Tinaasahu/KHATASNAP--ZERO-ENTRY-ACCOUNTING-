"""
Step 7 — Confidence Scoring
Implements ALL techniques:
- GSTIN checksum validation feedback
- Per-item qty×rate cross-check with feedback loop signal
- Total cross-check
- Flags for re-processing
"""
import re
import logging

logger = logging.getLogger(__name__)

GSTIN_RE = re.compile(r'^\d{2}[A-Z]{5}\d{4}[A-Z]{1}[A-Z\d]{1}Z[A-Z\d]{1}$')


def _validate_gstin_checksum(gstin: str) -> bool:
    if len(gstin) != 15: return False
    chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    total = 0
    for i, ch in enumerate(gstin[:14]):
        if ch not in chars: return False
        v = chars.index(ch)
        if i % 2 == 1: v *= 2
        total += v // len(chars) + v % len(chars)
    check_idx = (len(chars) - total % len(chars)) % len(chars)
    return gstin[14] == chars[check_idx]


def score_result(result: dict, ocr_blocks: list) -> dict:
    scores   = {}
    warnings = []
    reprocess_flags = []  # Fields that should trigger re-OCR if confidence is low

    avg_ocr_conf = (
        sum(b["confidence"] for b in ocr_blocks) / len(ocr_blocks)
        if ocr_blocks else 0.0
    )
    scores["ocr_avg_confidence"] = round(avg_ocr_conf, 3)

    # ── Vendor ─────────────────────────────────────────────────────────
    vendor = result.get("vendor_name", "")
    scores["vendor_name"] = 0.9 if len(vendor) > 3 else 0.2
    if not vendor:
        warnings.append("Vendor name not detected")

    # ── GSTIN with checksum ────────────────────────────────────────────
    gstin = result.get("gstin", "")
    if GSTIN_RE.match(gstin):
        if _validate_gstin_checksum(gstin):
            scores["gstin"] = 1.0
        else:
            scores["gstin"] = 0.4
            warnings.append(f"GSTIN checksum failed — OCR likely misread a character: {gstin}")
            reprocess_flags.append("gstin")
    elif gstin:
        scores["gstin"] = 0.3
        warnings.append(f"GSTIN format invalid: {gstin}")
        reprocess_flags.append("gstin")
    else:
        scores["gstin"] = 0.0
        warnings.append("GSTIN not detected")

    # ── Invoice number ─────────────────────────────────────────────────
    inv_no = result.get("invoice_no", "")
    scores["invoice_no"] = 0.9 if inv_no else 0.0
    if not inv_no:
        warnings.append("Invoice number not detected")

    # ── Date ──────────────────────────────────────────────────────────
    date = result.get("invoice_date", "")
    scores["invoice_date"] = 0.9 if date else 0.0
    if not date:
        warnings.append("Invoice date not detected")

    # ── Line items ────────────────────────────────────────────────────
    items = result.get("items", [])
    item_scores = []
    for i, item in enumerate(items):
        item_conf, item_flags = _score_item(item, i, warnings)
        item_scores.append(item_conf)
        item["confidence"] = round(item_conf, 3)
        if item_flags:
            reprocess_flags.extend(item_flags)

    scores["items_avg"] = round(
        sum(item_scores) / len(item_scores) if item_scores else 0.0, 3
    )
    if not items:
        warnings.append("No line items detected")

    # ── Totals cross-check ─────────────────────────────────────────────
    total   = result.get("total", 0)
    taxable = result.get("taxable_amount", 0)
    cgst    = result.get("cgst", 0)
    sgst    = result.get("sgst", 0)
    igst    = result.get("igst", 0)

    if total > 0:
        computed = taxable + cgst + sgst + igst
        if computed > 0:
            diff_pct = abs(total - computed) / total * 100
            if diff_pct < 1:
                scores["total_cross_check"] = 1.0
            elif diff_pct < 5:
                scores["total_cross_check"] = 0.7
                warnings.append(f"Total discrepancy: {diff_pct:.1f}%")
            else:
                scores["total_cross_check"] = 0.3
                warnings.append(
                    f"Total mismatch: extracted ₹{total:.2f}, "
                    f"computed ₹{computed:.2f} ({diff_pct:.1f}% off)"
                )
                reprocess_flags.append("total")
        else:
            scores["total_cross_check"] = 0.5
    else:
        scores["total_cross_check"] = 0.0
        warnings.append("Total amount not detected")
        reprocess_flags.append("total")

    # ── Items sum vs taxable ──────────────────────────────────────────
    if items and taxable > 0:
        items_sum = sum(item.get("amount", 0) for item in items)
        if items_sum > 0:
            diff_pct = abs(items_sum - taxable) / max(taxable, 1) * 100
            if diff_pct > 10:
                warnings.append(
                    f"Items sum (₹{items_sum:.2f}) vs taxable (₹{taxable:.2f}) — "
                    f"{diff_pct:.1f}% gap"
                )

    # ── Overall confidence ─────────────────────────────────────────────
    key_weights = {
        "vendor_name":       0.15,
        "gstin":             0.10,
        "invoice_no":        0.10,
        "invoice_date":      0.10,
        "items_avg":         0.35,
        "total_cross_check": 0.20,
    }
    overall = sum(scores.get(k, 0) * w for k, w in key_weights.items())
    scores["overall"] = round(overall, 3)

    grade = (
        "high"   if overall > 0.8 else
        "medium" if overall > 0.55 else
        "low"
    )

    result["confidence"] = {
        "scores":           scores,
        "grade":            grade,
        "warnings":         warnings,
        "reprocess_fields": list(set(reprocess_flags)),
        "ocr_blocks_count": len(ocr_blocks),
    }

    logger.info(f"Confidence: {grade} ({overall:.2f}) — {len(warnings)} warnings, "
                f"{len(reprocess_flags)} reprocess flags")
    return result


def _score_item(item: dict, idx: int, warnings: list) -> tuple[float, list]:
    score = 0.0
    flags = []

    name = item.get("name", "")
    if len(name) > 2:
        score += 0.4
    else:
        warnings.append(f"Item {idx+1}: name too short or missing")

    qty = item.get("qty", 0)
    if qty > 0:
        score += 0.2
    else:
        warnings.append(f"Item {idx+1} ({name}): quantity not detected")
        flags.append(f"item_{idx+1}_qty")

    rate = item.get("rate", 0)
    if rate > 0:
        score += 0.2

    amount = item.get("amount", 0)
    if amount > 0:
        score += 0.2
        if qty > 0 and rate > 0:
            computed = qty * rate
            if computed > 0:
                diff_pct = abs(amount - computed) / computed * 100
                if diff_pct > 15:
                    warnings.append(
                        f"Item {idx+1} ({name}): "
                        f"qty×rate=₹{computed:.2f} but amount=₹{amount:.2f}"
                    )
                    flags.append(f"item_{idx+1}_amount")
    else:
        flags.append(f"item_{idx+1}_amount")

    return score, flags