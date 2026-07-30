"""
KhataSnap — Pipeline Orchestrator

MODE A — VLM mode (Ollama + GLM-OCR running):
  Image → Enhance → Correct → GLM-OCR (full invoice understanding)
       → Use VLM's structured JSON directly → Confidence scoring
  No regex, no column detection, no layout analysis needed.
  The VLM reads the invoice like a human does.

MODE B — Standard mode (Ollama not running):
  Image → Enhance → Correct → PaddleOCR → Layout → Regex extraction
       → Confidence scoring
"""
import logging
import time
import numpy as np

from pipeline.step8_input    import load_input
from pipeline.step1_quality  import analyze_quality
from pipeline.step2_enhance  import enhance
from pipeline.step3_document import detect_and_correct, auto_crop_margins
from pipeline.step4_ocr      import run_ocr, _check_ollama
from pipeline.step5_layout   import group_into_rows, row_to_text
from pipeline.step6_extract  import (
    extract_vendor_info, extract_invoice_meta,
    extract_line_items, extract_gst_summary,
    find_header_and_col_map, SUMMARY_KW,
)
from pipeline.step7_confidence import score_result

logger = logging.getLogger(__name__)


def process_invoice(file_bytes: bytes, filename: str) -> dict:
    t0 = time.time()
    logger.info(f"=== Processing: {filename} ===")

    images = load_input(file_bytes, filename)
    logger.info(f"Loaded {len(images)} image(s)")

    vlm_mode = _check_ollama()
    logger.info(f"Mode: {'GLM-OCR via Ollama (VLM)' if vlm_mode else 'Standard PaddleOCR'}")

    all_blocks, quality_reports, vlm_data_list = [], [], []

    for page_num, image in enumerate(images):
        logger.info(f"--- Page {page_num+1}/{len(images)} ---")
        blocks, quality = _process_page(image, page_num)
        all_blocks.extend(blocks)
        quality_reports.append(quality)

        # If VLM mode — extract the raw structured data attached to first block
        if blocks and "_vlm_data" in blocks[0]:
            vlm_data_list.append(blocks[0]["_vlm_data"])

    if not all_blocks:
        return {
            "error": "No text could be extracted. Please ensure the image is clear.",
            "quality": quality_reports[0] if quality_reports else {},
            "items": [],
            "confidence": {"grade":"low","scores":{},"warnings":["No OCR output"]},
            "ocr_engine": "none",
        }

    # ── VLM mode: use structured output directly ──────────────────────────
    if vlm_mode and vlm_data_list:
        result = _assemble_from_vlm(vlm_data_list, all_blocks)

        # Quality gate: if VLM returned items but ALL rates are 0,
        # the model failed to read the columns — fall back to rule-based
        items = result.get("items", [])
        all_rates_zero = items and all(i.get("rate", 0) == 0 for i in items)
        all_amounts_zero = items and all(i.get("amount", 0) == 0 for i in items)

        if all_rates_zero and all_amounts_zero:
            logger.warning(
                "VLM returned all-zero rates and amounts — "
                "falling back to rule-based extraction for this bill"
            )
            result = _extract_and_score(all_blocks, filename)
            result["ocr_engine"] = "GLM-OCR + rule-based fallback"
    else:
        result = _extract_and_score(all_blocks, filename)

    result["processing_time_sec"] = round(time.time() - t0, 2)
    result["source_file"]         = filename
    result["pages_processed"]     = len(images)
    result["ocr_engine"]          = "GLM-OCR (Ollama)" if vlm_mode else "PaddleOCR"
    result["quality"] = (
        quality_reports[0] if len(quality_reports) == 1 else quality_reports
    )

    logger.info(
        f"=== Done {result['processing_time_sec']}s "
        f"| {result['ocr_engine']} "
        f"| confidence: {result['confidence']['grade']} ==="
    )
    return result


def _process_page(image: np.ndarray, page_num: int):
    quality = analyze_quality(image)
    logger.info(
        f"Quality: {quality['grade']} score={quality['scores']['overall']:.3f} "
        f"— {len(quality['issues'])} issues"
    )
    if not quality["processable"]:
        logger.warning(f"Page {page_num+1} quality too low — skipping")
        return [], quality

    enhanced = enhance(image, quality)
    corrected, was_corrected = detect_and_correct(enhanced)
    if was_corrected:
        logger.info("Perspective corrected")
        corrected = auto_crop_margins(corrected)

    blocks = run_ocr(corrected)
    logger.info(f"Extracted {len(blocks)} blocks")
    return blocks, quality


def _clean_gstin(s: str) -> str:
    """Return empty string if value doesn't look like a real GSTIN."""
    import re
    if re.match(r'^\d{2}[A-Z]{5}\d{4}[A-Z][A-Z\d][Z][A-Z\d]$', s):
        return s
    return ""


def _looks_like_invoice_no(s: str) -> bool:
    """Check if a string looks like an invoice number rather than a vendor name."""
    import re
    # Patterns like SGT/GWL/2024-25/INV/07841 or INV-001 or 2024/07841
    return bool(re.match(r'^[A-Z0-9]{2,}/[A-Z0-9/\-]+$', s) or
                re.match(r'^INV[-/]', s, re.I) or
                re.match(r'^\d{4}[-/]\d+$', s))


def _fix_vendor_name(data: dict) -> str:
    vn = str(data.get("vendor_name", "")).strip()
    inv = str(data.get("invoice_no", "")).strip()
    # If vendor_name looks like invoice number and invoice_no is empty, clear it
    if _looks_like_invoice_no(vn) and not inv:
        return ""
    return vn


def _fix_invoice_no(data: dict) -> str:
    inv = str(data.get("invoice_no", "")).strip()
    vn  = str(data.get("vendor_name", "")).strip()
    # If invoice_no is empty but vendor_name looks like invoice number, use it
    if not inv and _looks_like_invoice_no(vn):
        return vn
    return inv


def _assemble_from_vlm(vlm_data_list: list, all_blocks: list) -> dict:
    """
    Build result directly from VLM structured output.
    Merges multi-page results if PDF.
    """
    # For now use first page data (multi-page merge can be added later)
    data = vlm_data_list[0]

    # Sanitize all numeric fields
    def f(v): 
        try: return float(v or 0)
        except: return 0.0

    # Merge split product names — bills often wrap long names across two rows
    # A continuation row has no qty, rate, amount and a short name (suffix/descriptor)
    import re as _re
    import re
    raw_items = data.get("items", [])
    merged = []
    for item in raw_items:
        name   = str(item.get("name", "")).strip()
        qty    = f(item.get("qty", 0))
        rate   = f(item.get("rate", 0))
        amount = f(item.get("amount", 0))
        hsn    = str(item.get("hsn", "")).strip()

        is_continuation = (
            qty == 0 and rate == 0 and amount == 0 and not hsn
            and len(name) > 0 and len(name) < 40
            and not _re.match(r"^\d+\s+[A-Z]", name)  # not a new numbered item
        )

        if merged and is_continuation:
            # Append to previous item name
            merged[-1]["name"] = merged[-1]["name"].rstrip() + " " + name
            logger.info(f"Merged continuation: '{name}' → appended to '{merged[-1]['name'][:50]}'")
        else:
            merged.append({
                "name":        name,
                "hsn":         hsn,
                "qty":         int(qty),
                "unit":        str(item.get("unit", "")).strip(),
                "mrp":         f(item.get("mrp", 0)),
                "rate":        rate,
                "gst_percent": f(item.get("gst_percent", 0)),
                "discount":    f(item.get("discount", 0)),
                "amount":      amount,
            })
    items = merged

    # Fallback: compute missing amounts from qty × rate
    for item in items:
        if item["amount"] == 0 and item["qty"] > 0 and item["rate"] > 0:
            item["amount"] = round(item["qty"] * item["rate"], 2)
            logger.info(f"  Computed amount for {item['name'][:30]}: "
                        f"{item['qty']} × {item['rate']} = {item['amount']}")

        # Fix: if unit looks like a number (rate got put there), clear it
        if item["unit"] and re.match(r'^\d+\.?\d*$', item["unit"].strip()):
            item["unit"] = ""

    item_total = sum(i["amount"] for i in items)

    taxable = f(data.get("taxable_amount", 0))
    cgst    = f(data.get("cgst", 0))
    sgst    = f(data.get("sgst", 0))
    igst    = f(data.get("igst", 0))
    cess    = f(data.get("cess", 0))
    disc    = f(data.get("discount_total", 0))
    total   = f(data.get("total", 0))

    # Fill computed values if VLM missed them
    if taxable == 0 and item_total > 0:
        taxable = round(item_total, 2)
    if total == 0 and taxable > 0:
        total = round(taxable + cgst + sgst + igst + cess - disc, 2)

    result = {
        # Fix: if vendor_name looks like an invoice number, swap them
        "vendor_name":    _fix_vendor_name(data),
        "gstin":          str(data.get("gstin", "")).strip(),
        "phone":          str(data.get("phone", "")).strip(),
        "invoice_no":     _fix_invoice_no(data),
        "invoice_date":   str(data.get("invoice_date", "")).strip(),
        "buyer":          str(data.get("buyer", "")).strip(),
        "buyer_gstin":    _clean_gstin(str(data.get("buyer_gstin", "")).strip()),
        "place_of_supply":str(data.get("place_of_supply", "")).strip(),
        "items":          items,
        "taxable_amount": taxable,
        "cgst":           cgst,
        "sgst":           sgst,
        "igst":           igst,
        "cess":           cess,
        "discount_total": disc,
        "total":          total,
    }

    logger.info(
        f"VLM assembled: {len(items)} items, "
        f"total=₹{total}, vendor={result['vendor_name']}"
    )

    return score_result(result, all_blocks)


def _is_summary(row: list) -> bool:
    t = row_to_text(row).lower()
    return any(kw in t for kw in SUMMARY_KW)


def _extract_and_score(blocks: list, filename: str) -> dict:
    """Standard rule-based extraction — used when Ollama is not available."""
    rows = group_into_rows(blocks)
    header_idx, col_map = find_header_and_col_map(rows)

    if header_idx is not None:
        vendor_rows   = rows[:header_idx]
        header_rows   = [rows[header_idx]]
        summary_start = None
        for i in range(header_idx + 1, len(rows)):
            if _is_summary(rows[i]):
                summary_start = i
                break
        data_rows    = rows[header_idx + 1: summary_start]
        summary_rows = rows[summary_start:] if summary_start else []
    else:
        vendor_rows  = rows[:min(8, len(rows))]
        header_rows  = []
        data_rows    = rows[8:]
        summary_rows = []

    logger.info(
        f"Partitions: {len(vendor_rows)} vendor | "
        f"{len(header_rows)} header | "
        f"{len(data_rows)} data | "
        f"{len(summary_rows)} summary"
    )

    vendor     = extract_vendor_info(vendor_rows)
    meta       = extract_invoice_meta(vendor_rows, rows)
    items      = extract_line_items(data_rows, header_rows)
    item_total = sum(i.get("amount", 0) for i in items)
    gst        = extract_gst_summary(summary_rows, item_total)

    if gst["total"] == 0 and gst["taxable_amount"] == 0 and header_idx:
        gst = extract_gst_summary(rows[header_idx + 1:], item_total)

    if gst["taxable_amount"] == 0 and item_total > 0:
        gst["taxable_amount"] = round(item_total, 2)
    if gst["total"] == 0 and gst["taxable_amount"] > 0:
        gst["total"] = round(
            gst["taxable_amount"] + gst["cgst"] + gst["sgst"]
            + gst["igst"] + gst["cess"] - gst["discount_total"], 2
        )

    result = {**vendor, **meta, "items": items, **gst}
    return score_result(result, blocks)