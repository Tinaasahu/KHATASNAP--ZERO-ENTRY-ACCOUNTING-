"""
Step 4 — OCR Engine using GLM-OCR via Ollama

GLM-OCR is purpose-built for document OCR:
- 94.62 score on OmniDocBench V1.5 (ranked #1 globally)
- 0.9B parameters — fits in 4GB VRAM (RTX 2050)
- Understands tables, handwriting, skew, complex layouts
- Runs fully local via Ollama on Windows

Setup (one time):
  1. Install Ollama from https://ollama.com/download
  2. Run: ollama pull glm-ocr
  3. Ollama serves automatically on http://localhost:11434

Then start FastAPI normally — no separate terminal needed.
"""
import os
import re
import base64
import json
import logging
import tempfile
import numpy as np
import cv2

logger = logging.getLogger(__name__)

OLLAMA_URL   = os.environ.get("OLLAMA_URL",   "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "glm-ocr")

# Cached availability flag
_ollama_ok   = None
_fallback_ocr = None

# ── Invoice extraction prompt ─────────────────────────────────────────────
INVOICE_PROMPT = """请按下列JSON格式输出图中信息 (Extract all invoice data and return ONLY this JSON, nothing else):
{
  "vendor_name": "",
  "gstin": "",
  "invoice_no": "",
  "invoice_date": "",
  "buyer": "",
  "buyer_gstin": "",
  "phone": "",
  "items": [
    {
      "name": "",
      "hsn": "",
      "qty": 0,
      "unit": "",
      "mrp": 0,
      "rate": 0,
      "gst_percent": 0,
      "discount": 0,
      "amount": 0
    }
  ],
  "taxable_amount": 0,
  "cgst": 0,
  "sgst": 0,
  "igst": 0,
  "cess": 0,
  "discount_total": 0,
  "total": 0
}
Rules:
1. Each table row = ONE item. Wrap-around product names = combine into one.
2. qty = ordered quantity (integer, typically 1-500). NOT product code or SKU.
3. rate = unit selling price (decimal number from RATE column).
4. amount = line total from TOTAL or AMOUNT column (= qty × rate approximately).
5. unit = UOM text like BAG/PKT/NOS/KG — empty string if no UOM column.
6. hsn = HSN code digits only (4-8 digits).
7. gst_percent = CGST%+SGST% or IGST% (combined rate, e.g. 5 for 2.5+2.5).
8. taxable_amount = pre-tax subtotal (TAXABLE VALUE or AMOUNT BEFORE TAX row).
9. cgst/sgst = tax amount values in rupees (not percentages).
10. invoice_no = invoice number string (e.g. CN3-2254).
11. vendor_name = seller company name only.
12. buyer_gstin = 15-char GSTIN starting with 2 digits, empty if not found.
Return ONLY the JSON.
"""


# ── Ollama availability check ─────────────────────────────────────────────

def _check_ollama() -> bool:
    global _ollama_ok
    if _ollama_ok is not None:
        return _ollama_ok
    try:
        import requests
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        if r.status_code == 200:
            models = [m["name"] for m in r.json().get("models", [])]
            model_base = OLLAMA_MODEL.split(":")[0]
            has_model  = any(model_base in m for m in models)
            if has_model:
                _ollama_ok = True
                logger.info(f"Ollama ready — using {OLLAMA_MODEL}")
            else:
                logger.warning(
                    f"Ollama running but {OLLAMA_MODEL} not found.\n"
                    f"Available: {models}\n"
                    f"Run: ollama pull {OLLAMA_MODEL}"
                )
                _ollama_ok = False
        else:
            _ollama_ok = False
    except Exception as e:
        logger.warning(
            f"Ollama not reachable at {OLLAMA_URL} ({e})\n"
            f"Install from https://ollama.com/download then run: ollama pull {OLLAMA_MODEL}\n"
            f"Falling back to standard PaddleOCR."
        )
        _ollama_ok = False
    return _ollama_ok


# ── GLM-OCR via Ollama ────────────────────────────────────────────────────

def _image_to_base64(image: np.ndarray) -> str:
    """Convert OpenCV BGR image to base64 JPEG string."""
    _, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 95])
    return base64.b64encode(buf.tobytes()).decode("utf-8")


def _call_ollama(image: np.ndarray) -> dict:
    """Call GLM-OCR via Ollama API and return parsed JSON result."""
    import requests

    img_b64 = _image_to_base64(image)

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": INVOICE_PROMPT,
        "images": [img_b64],
        "stream": False,
        "options": {
            "temperature": 0.0,   # Deterministic — we want exact extraction
            "num_ctx": 4096,
        }
    }

    logger.info(f"Calling Ollama {OLLAMA_MODEL}...")
    r = requests.post(
        f"{OLLAMA_URL}/api/generate",
        json=payload,
        timeout=120   # VLMs can take 10-30s on first run
    )
    r.raise_for_status()

    raw = r.json().get("response", "")
    logger.info(f"Ollama response length: {len(raw)} chars")

    # Strip markdown fences if present
    raw = re.sub(r"```json\s*", "", raw)
    raw = re.sub(r"```\s*",     "", raw)
    raw = raw.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Try to extract JSON object from response
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            return json.loads(m.group())
        raise ValueError(f"GLM-OCR returned non-JSON response: {raw[:300]}")


def _vlm_result_to_blocks(data: dict) -> list[dict]:
    """
    Convert VLM structured JSON output into standard block format
    so the rest of the pipeline (steps 5-7) can process it normally.

    Each field becomes a positioned block with synthetic bounding boxes
    arranged in a logical document layout.
    """
    blocks = []
    y = 10  # running Y position

    def add(text: str, conf: float = 0.95, x1: int = 0, y1: int = None, x2: int = 400):
        nonlocal y
        if y1 is None:
            y1 = y
        y2 = y1 + 20
        y  = y2 + 4
        blocks.append({
            "text": str(text).strip(),
            "confidence": conf,
            "bbox": {
                "x1": x1, "y1": y1,
                "x2": x2, "y2": y2,
                "cx": (x1 + x2) // 2,
                "cy": (y1 + y2) // 2,
            }
        })

    # Vendor header section
    if data.get("vendor_name"): add(data["vendor_name"],    x1=0,   x2=500)
    if data.get("gstin"):       add(f"GSTIN: {data['gstin']}", x1=0, x2=400)
    if data.get("invoice_no"):  add(f"Invoice No. {data['invoice_no']}", x1=0, x2=300)
    if data.get("invoice_date"):add(f"Invoice Date {data['invoice_date']}", x1=300, x2=600)
    if data.get("buyer"):       add(f"Bill To: {data['buyer']}", x1=0, x2=400)

    # Table header row
    y += 10
    header_y = y
    for col, x1, x2 in [
        ("DESCRIPTION", 0, 200), ("QTY", 200, 250), ("RATE", 250, 320),
        ("AMOUNT", 320, 400), ("GST%", 400, 450), ("HSN", 450, 520)
    ]:
        blocks.append({
            "text": col, "confidence": 0.99,
            "bbox": {"x1": x1, "y1": header_y, "x2": x2, "y2": header_y+18,
                     "cx": (x1+x2)//2, "cy": header_y+9}
        })
    y = header_y + 22

    # Line items — each field as a separate block at correct X position
    for item in data.get("items", []):
        row_y = y
        name = item.get("name", "")
        if name:
            blocks.append({"text": name, "confidence": 0.95,
                "bbox": {"x1":0,"y1":row_y,"x2":200,"y2":row_y+18,"cx":100,"cy":row_y+9}})
        qty = item.get("qty", 0)
        if qty:
            blocks.append({"text": str(qty), "confidence": 0.95,
                "bbox": {"x1":200,"y1":row_y,"x2":250,"y2":row_y+18,"cx":225,"cy":row_y+9}})
        rate = item.get("rate", 0)
        if rate:
            blocks.append({"text": str(rate), "confidence": 0.95,
                "bbox": {"x1":250,"y1":row_y,"x2":320,"y2":row_y+18,"cx":285,"cy":row_y+9}})
        amount = item.get("amount", 0)
        if amount:
            blocks.append({"text": str(amount), "confidence": 0.95,
                "bbox": {"x1":320,"y1":row_y,"x2":400,"y2":row_y+18,"cx":360,"cy":row_y+9}})
        gst = item.get("gst_percent", 0)
        if gst:
            blocks.append({"text": str(gst)+"%", "confidence": 0.95,
                "bbox": {"x1":400,"y1":row_y,"x2":450,"y2":row_y+18,"cx":425,"cy":row_y+9}})
        hsn = item.get("hsn", "")
        if hsn:
            blocks.append({"text": str(hsn), "confidence": 0.95,
                "bbox": {"x1":450,"y1":row_y,"x2":520,"y2":row_y+18,"cx":485,"cy":row_y+9}})
        y = row_y + 22

    # Summary section
    y += 10
    for label, key in [
        ("Total Amount Before Tax", "taxable_amount"),
        ("Add: CGST",               "cgst"),
        ("Add: SGST",               "sgst"),
        ("Add: IGST",               "igst"),
        ("Add: CESS",               "cess"),
        ("Discount",                "discount_total"),
        ("Total Amount After Tax",  "total"),
    ]:
        val = data.get(key, 0)
        if val:
            blocks.append({"text": label, "confidence": 0.95,
                "bbox": {"x1":0,"y1":y,"x2":300,"y2":y+18,"cx":150,"cy":y+9}})
            blocks.append({"text": str(val), "confidence": 0.95,
                "bbox": {"x1":300,"y1":y,"x2":450,"y2":y+18,"cx":375,"cy":y+9}})
            y += 22

    logger.info(f"VLM extracted {len(data.get('items', []))} items → {len(blocks)} blocks")
    return blocks


# ── Main entry point ──────────────────────────────────────────────────────

def run_ocr(image: np.ndarray) -> list[dict]:
    """
    Run OCR. Uses GLM-OCR via Ollama if available, else standard PaddleOCR.
    Returns list of positioned text blocks.
    """
    if _check_ollama():
        return _run_vlm(image)
    return _run_standard(image)


def _run_vlm(image: np.ndarray) -> list[dict]:
    """GLM-OCR path — full invoice understanding in one shot."""
    try:
        data   = _call_ollama(image)
        blocks = _vlm_result_to_blocks(data)

        # Attach raw VLM data to first block for orchestrator to use directly
        if blocks:
            blocks[0]["_vlm_data"] = data

        return blocks

    except Exception as e:
        logger.error(f"GLM-OCR failed: {e} — falling back to standard OCR")
        return _run_standard(image)


def _run_standard(image: np.ndarray) -> list[dict]:
    """Standard PaddleOCR fallback."""
    global _fallback_ocr
    import uuid

    if _fallback_ocr is None:
        logger.info("Initializing standard PaddleOCR fallback...")
        try:
            from paddleocr import PaddleOCR
            _fallback_ocr = PaddleOCR(use_angle_cls=True, lang="en")
        except TypeError:
            from paddleocr import PaddleOCR
            _fallback_ocr = PaddleOCR(lang="en")
        logger.info("PaddleOCR fallback ready")

    tmp = f"tmp_{uuid.uuid4().hex[:8]}.jpg"
    cv2.imwrite(tmp, image)
    results = None
    try:
        results = (_fallback_ocr.predict(tmp)
                   if hasattr(_fallback_ocr, "predict")
                   else _fallback_ocr.ocr(image))
    except Exception as e:
        logger.warning(f"predict() failed: {e}")
        try:
            results = _fallback_ocr.ocr(image)
        except Exception as e2:
            raise RuntimeError(f"OCR failed: {e2}") from e2
    finally:
        try: os.remove(tmp)
        except: pass

    if not results: return []

    blocks = []
    for r in results:
        if r is None: continue
        if isinstance(r, dict):
            blocks.extend(_blocks_from_dict(r))
        elif isinstance(r, list):
            blocks.extend(_blocks_from_list(r))

    logger.info(f"Standard OCR: {len(blocks)} blocks")
    return blocks


def _blocks_from_dict(r: dict) -> list[dict]:
    keys_t = ["rec_texts","texts","text"]
    keys_s = ["rec_scores","scores","score"]
    keys_p = ["dt_polys","boxes","dt_boxes","polys"]
    texts  = next((r[k] for k in keys_t if r.get(k)), None)
    scores = next((r[k] for k in keys_s if r.get(k)), None)
    polys  = next((r[k] for k in keys_p if r.get(k)), None)
    if not texts: return []
    n = len(texts)
    scores = list(scores) if scores else [0.9]*n
    polys  = list(polys)  if polys  else [None]*n
    blocks = []
    for text, score, poly in zip(texts, scores, polys):
        text = str(text).strip()
        if not text: continue
        try:    sf = float(score)
        except: sf = 0.9
        if sf < 0.1: continue
        if poly is not None:
            try:
                arr = np.array(poly); xs = arr[:,0].tolist(); ys = arr[:,1].tolist()
            except:
                xs, ys = [0.,100.], [len(blocks)*20., len(blocks)*20.+16.]
        else:
            xs, ys = [0.,100.], [len(blocks)*20., len(blocks)*20.+16.]
        blocks.append(_mk(text, sf, xs, ys))
    return blocks


def _blocks_from_list(page: list) -> list[dict]:
    blocks = []
    for line in page:
        if line is None: continue
        try:
            box, (text, conf) = line
            if str(text).strip() and float(conf) >= 0.1:
                blocks.append(_mk(text, conf,
                    [float(p[0]) for p in box],
                    [float(p[1]) for p in box]))
        except: continue
    return blocks


def _mk(text, conf, xs, ys) -> dict:
    return {
        "text": str(text).strip(), "confidence": round(float(conf), 4),
        "bbox": {
            "x1": int(min(xs)),  "y1": int(min(ys)),
            "x2": int(max(xs)),  "y2": int(max(ys)),
            "cx": int(sum(xs)/len(xs)), "cy": int(sum(ys)/len(ys)),
        }
    }