"""
KhataSnap — Smart Document Router

Purpose:
Automatically detect whether the input is:
1. Invoice → use existing pipeline (unchanged)
2. Product List (handwritten / simple list) → use EasyOCR pipeline

IMPORTANT:
- DOES NOT modify your existing pipeline
- Only adds routing layer
"""

import re
import numpy as np
import cv2

from pipeline.step8_input import load_input
from pipeline.step4_ocr import _run_standard  # force PaddleOCR only for classification

from orchestrator import process_invoice


# ─────────────────────────────────────────────────────────────
# 🔥 DOCUMENT CLASSIFIER (STRUCTURE-BASED — RELIABLE)
# ─────────────────────────────────────────────────────────────

def classify_document(blocks):
    texts = [b["text"].lower() for b in blocks]
    full_text = " ".join(texts)

    # Invoice keyword signals
    invoice_keywords = [
        "gst", "invoice", "cgst", "sgst", "igst",
        "hsn", "tax", "bill", "total", "amount"
    ]

    invoice_score = sum(1 for k in invoice_keywords if k in full_text)

    # Structural signals
    numeric_blocks = sum(1 for t in texts if any(c.isdigit() for c in t))
    short_blocks = sum(1 for t in texts if len(t.split()) <= 2)
    has_list_unit = any(("pic" in t or "pcs" in t) for t in texts)

    total_blocks = len(texts) if texts else 1

    # Decision logic

    # Strong invoice
    if invoice_score >= 2 and numeric_blocks > 10:
        return "invoice"

    # Strong list (short text dominant)
    if short_blocks > total_blocks * 0.6:
        return "list"

    # List unit present without invoice signals
    if has_list_unit and invoice_score == 0:
        return "list"

    # Very low numeric density → list
    if numeric_blocks < 5:
        return "list"

    return "invoice"


# ─────────────────────────────────────────────────────────────
# 🔥 LIST MODE PIPELINE (EASYOCR)
# ─────────────────────────────────────────────────────────────

def process_list_mode(image):
    import easyocr

    reader = easyocr.Reader(['en'], gpu=False)
    results = reader.readtext(image)

    lines = []
    for _, text, _ in results:
        if text.strip():
            lines.append(text.strip())

    items = []

    for line in lines:
        line_clean = line.lower()

        # Pattern: name + number + optional unit
        match = re.search(r"(.*?)(\d+)\s*(pic|pcs|pc)?", line_clean)

        if match:
            name = match.group(1).strip()
            qty = int(match.group(2))

            if len(name) > 1:
                items.append({
                    "name": name.title(),
                    "qty": qty
                })

    return {
        "mode": "list",
        "items": items,
        "confidence": {
            "grade": "medium",
            "warnings": [
                "Handwritten OCR may contain spelling errors",
                "Verify product names if critical"
            ]
        },
        "ocr_engine": "EasyOCR (list mode)"
    }


# ─────────────────────────────────────────────────────────────
# 🔥 MAIN ROUTER ENTRY POINT
# ─────────────────────────────────────────────────────────────

def process_document(file_bytes: bytes, filename: str):

    # Load image(s)
    images = load_input(file_bytes, filename)
    image = images[0]

    # STEP 1: Fast OCR (Paddle only) for classification
    blocks = _run_standard(image)

    # STEP 2: Classify document type
    mode = classify_document(blocks)

    print(f"[Router] Detected mode: {mode}")

    # STEP 3: Route accordingly

    if mode == "invoice":
        # Use your PERFECT existing pipeline (unchanged)
        return process_invoice(file_bytes, filename)

    else:
        # Use lightweight handwritten list pipeline
        return process_list_mode(image)