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
_easyocr_reader = None

# ── Invoice extraction prompt ─────────────────────────────────────────────
INVOICE_PROMPT = """You are an advanced OCR + Retail Intelligence Engine designed specifically for Indian Kirana stores.

Your job is to analyze ANY uploaded bill image (printed or handwritten), extract structured data, intelligently understand it, and prepare it for inventory operations.

---

## 🎯 PRIMARY OBJECTIVE

1. Extract all relevant data from the bill
2. Classify the bill type:
   * PURCHASE_BILL → stock coming INTO inventory (distributor invoice)
   * SALE_BILL → stock going OUT (customer list / handwritten parchi)
3. Convert everything into clean, structured JSON
4. Prepare data for inventory ADD or REMOVE operations

---

## 🧠 BILL TYPE DETECTION RULES

Classify the bill using these rules:

→ PURCHASE_BILL if ANY of the following are present:
* GST number
* Supplier / distributor name
* Invoice number
* Tax breakdown (CGST/SGST/IGST)
* Printed structured format

→ SALE_BILL if:
* Simple list of items
* Handwritten content
* No GST / supplier info
* Looks like a customer purchase list

→ If handwritten but contains supplier indicators → PURCHASE_BILL
→ Default fallback → SALE_BILL

---

## 📦 STRICT OUTPUT FORMAT (ONLY JSON)

{
"bill_type": "PURCHASE_BILL" | "SALE_BILL",
"confidence": 0-1,
"needs_user_selection": false,
"supplier_details": {
"name": "",
"gst": "",
"address": ""
},
"invoice_details": {
"invoice_number": "",
"date": "",
"total_amount": "",
"tax_amount": ""
},
"items": [
{
"raw_text": "",
"standard_name": "",
"brand": "",
"variant": "",
"quantity": "",
"unit": "kg | g | L | ml | pcs",
"price": "",
"confidence": 0-1
}
]
}

Return ONLY valid JSON. No explanations.

---

## 🧾 ITEM EXTRACTION RULES

For each detected item:

1. Capture raw OCR text exactly
2. Normalize into structured fields:
   * standard_name (generic name)
   * brand (if present)
   * variant (size/type like 1kg, 500ml, packet, loose)
3. Examples:
   "Tata Salt 1kg" → name: "Salt", brand: "Tata", variant: "1kg"
   "Aashirvaad Atta 5kg" → name: "Atta", brand: "Aashirvaad", variant: "5kg"
4. Handle spelling mistakes using fuzzy correction:
   * "Suger", "Sugr", "Shugar" → "Sugar"
   * "Rce", "Ricee" → "Rice"
   * "Oyl" → "Oil"
5. Support Hinglish / Hindi:
   * "Namak" → "Salt"
   * "Chini" → "Sugar"
   * "Tel" → "Oil"
6. If quantity missing → default = 1

---

## 🧮 INVENTORY OPERATION LOGIC

DO NOT execute inventory changes, but prepare intent:
IF bill_type = PURCHASE_BILL:
→ action = "ADD_TO_INVENTORY"

IF bill_type = SALE_BILL:
→ action = "REMOVE_FROM_INVENTORY"

---

## 🔍 SMART MATCHING LOGIC

When mapping items to inventory:
* Use fuzzy matching (minimum 80% similarity)
* Match using: standard_name + brand + variant
* If exact variant exists → select it
* If multiple variants exist → DO NOT guess → Set "needs_user_selection": true

---

## ⚠️ EDGE CASE HANDLING

1. If item confidence < 0.7: Keep item but mark low confidence
2. If unreadable text: Fill "raw_text", leave others empty, confidence low
3. If total bill amount missing: Still extract items
4. If image is noisy / tilted: Attempt best possible extraction

---

## 🧠 LEARNING & IMPROVEMENT

Assume a learning system exists:
* Store corrected mappings: "tata namk" → "Tata Salt"
* Improve future predictions using history

---

## 🎤 OCR + ASR CORRELATION (IMPORTANT)

If text is ambiguous:
* Use phonetic similarity: "shupar" → "Sugar"

---

Return ONLY JSON.
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
    supplier = data.get("supplier_details") or {}
    invoice = data.get("invoice_details") or {}
    
    if supplier.get("name"): add(supplier["name"],    x1=0,   x2=500)
    if supplier.get("gst"):  add(f"GSTIN: {supplier['gst']}", x1=0, x2=400)
    if invoice.get("invoice_number"):  add(f"Invoice No. {invoice['invoice_number']}", x1=0, x2=300)
    if invoice.get("date"):add(f"Invoice Date {invoice['date']}", x1=300, x2=600)

    # Table header row
    y += 10
    header_y = y
    for col, x1, x2 in [
        ("DESCRIPTION", 0, 200), ("QTY", 200, 250), ("RATE", 250, 320), ("AMOUNT", 320, 400)
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
        brand = str(item.get("brand", "")).strip()
        standard_name = str(item.get("standard_name", "")).strip()
        variant = str(item.get("variant", "")).strip()
        name_parts = [brand, standard_name, variant]
        name = " ".join([p for p in name_parts if p])
        if not name: name = item.get("raw_text", "")
        
        if name:
            blocks.append({"text": name, "confidence": 0.95,
                "bbox": {"x1":0,"y1":row_y,"x2":200,"y2":row_y+18,"cx":100,"cy":row_y+9}})
        qty = item.get("quantity", 0)
        if qty:
            blocks.append({"text": str(qty), "confidence": 0.95,
                "bbox": {"x1":200,"y1":row_y,"x2":250,"y2":row_y+18,"cx":225,"cy":row_y+9}})
        rate = item.get("price", 0)
        if rate:
            blocks.append({"text": str(rate), "confidence": 0.95,
                "bbox": {"x1":250,"y1":row_y,"x2":320,"y2":row_y+18,"cx":285,"cy":row_y+9}})
        # Estimate amount since the new prompt schema doesn't export item amount but rate
        try:
            amt = float(rate) * int(qty or 1)
            if amt > 0:
                blocks.append({"text": str(amt), "confidence": 0.95,
                    "bbox": {"x1":320,"y1":row_y,"x2":400,"y2":row_y+18,"cx":360,"cy":row_y+9}})
        except:
            pass
        y = row_y + 22

    # Summary section
    y += 10
    total = invoice.get("total_amount", 0) if invoice else 0
    if total:
        blocks.append({"text": "Total Amount After Tax", "confidence": 0.95,
            "bbox": {"x1":0,"y1":y,"x2":300,"y2":y+18,"cx":150,"cy":y+9}})
        blocks.append({"text": str(total), "confidence": 0.95,
            "bbox": {"x1":300,"y1":y,"x2":450,"y2":y+18,"cx":375,"cy":y+9}})

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
    """Standard OCR fallback.

    Order:
    - PaddleOCR if `paddlepaddle` is available
    - Else EasyOCR (works on Python 3.14 in this environment)
    """
    global _fallback_ocr, _easyocr_reader
    import uuid

    if _fallback_ocr is None:
        logger.info("Initializing standard PaddleOCR fallback...")
        try:
            from paddleocr import PaddleOCR
            _fallback_ocr = PaddleOCR(use_angle_cls=True, lang="en")
        except ModuleNotFoundError as err:
            # Common on Python 3.14: paddleocr installs, but paddlepaddle has no wheel.
            if "paddle" in str(err).lower():
                _fallback_ocr = None
                logger.warning(
                    "PaddleOCR unavailable (missing paddle runtime). "
                    "Falling back to EasyOCR."
                )
            else:
                raise
        except TypeError:
            from paddleocr import PaddleOCR
            _fallback_ocr = PaddleOCR(lang="en")
        if _fallback_ocr is not None:
            logger.info("PaddleOCR fallback ready")

    # If PaddleOCR couldn't be initialized, use EasyOCR.
    if _fallback_ocr is None:
        return _run_easyocr(image)

    tmp = f"tmp_{uuid.uuid4().hex[:8]}.jpg"
    cv2.imwrite(tmp, image)
    results = None
    try:
        results = (
            _fallback_ocr.predict(tmp)
            if hasattr(_fallback_ocr, "predict")
            else _fallback_ocr.ocr(image)
        )
    except Exception as e:
        logger.warning(f"predict() failed: {e}")
        try:
            results = _fallback_ocr.ocr(image)
        except Exception as e2:
            # If paddle breaks at runtime, degrade to EasyOCR instead of failing the request.
            logger.warning(f"PaddleOCR runtime failure: {e2} — falling back to EasyOCR")
            return _run_easyocr(image)
    finally:
        try:
            os.remove(tmp)
        except Exception:
            pass

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


def _run_easyocr(image: np.ndarray) -> list[dict]:
    """EasyOCR fallback that doesn't require Paddle/PaddlePaddle."""
    global _easyocr_reader
    if _easyocr_reader is None:
        logger.info("Initializing EasyOCR fallback...")
        import easyocr
        # English + Hindi covers typical kirana bills.
        _easyocr_reader = easyocr.Reader(["en", "hi"], gpu=False)
        logger.info("EasyOCR fallback ready")

    # EasyOCR expects RGB
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB) if image.ndim == 3 else image
    try:
        results = _easyocr_reader.readtext(rgb)
    except Exception as e:
        raise RuntimeError(f"OCR failed (EasyOCR): {e}") from e

    blocks: list[dict] = []
    for r in results or []:
        try:
            bbox, text, conf = r
            text = str(text).strip()
            if not text:
                continue
            conf = float(conf) if conf is not None else 0.5
            if conf < 0.1:
                continue

            xs = [float(p[0]) for p in bbox]
            ys = [float(p[1]) for p in bbox]
            blocks.append(_mk(text, conf, xs, ys))
        except Exception:
            continue

    logger.info(f"EasyOCR: {len(blocks)} blocks")
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