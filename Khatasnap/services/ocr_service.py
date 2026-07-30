"""
KhataSnap — OCR Micro-service
Wraps the existing OCR pipeline (Suryaansh's 8-step PaddleOCR + GLM-OCR).
Port: 8001 (from .env → OCR_SERVICE_PORT)

Does NOT modify any pipeline/* files. Only provides a FastAPI shell around them.
"""

import os
import sys
import logging
import traceback

# ── Paddle environment patches (MUST be before any paddle import) ────────
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
os.environ.setdefault("FLAGS_use_mkldnn", "0")
os.environ.setdefault("GLOG_minloglevel", "3")

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import numpy as np

# ── Load config ──────────────────────────────────────────────────────────
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))

# ── Add parent dir to sys.path so we can import pipeline & orchestrator ──
PARENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ocr_service")

app = FastAPI(title="KhataSnap OCR Service")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def sanitize_json(obj):
    """Convert numpy types to JSON-safe Python types."""
    if isinstance(obj, dict):
        return {k: sanitize_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_json(v) for v in obj]
    elif isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.floating):
        return float(obj)
    elif isinstance(obj, np.bool_):
        return bool(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    return obj


@app.get("/health")
def health():
    return {"status": "ok", "service": "ocr", "port": int(os.getenv("OCR_SERVICE_PORT", 8001))}


@app.post("/scan")
async def scan_invoice(file: UploadFile = File(...)):
    """Accept an image/PDF and run the full OCR pipeline."""
    ALLOWED = {"image/jpeg", "image/jpg", "image/png", "image/webp",
               "image/bmp", "application/pdf"}

    if file.content_type not in ALLOWED:
        raise HTTPException(400, f"Unsupported type: {file.content_type}")

    contents = await file.read()
    if len(contents) > 20 * 1024 * 1024:
        raise HTTPException(400, "File too large (max 20MB)")

    try:
        # Try the smart router first (handles invoices vs product lists)
        try:
            from router import process_document
            result = process_document(contents, file.filename or "upload")
        except ImportError:
            # Fallback to direct orchestrator
            from orchestrator import process_invoice
            result = process_invoice(contents, file.filename or "upload")

        return JSONResponse(content=sanitize_json(result))

    except Exception as e:
        tb = traceback.format_exc()
        logger.error(f"Pipeline error on '{file.filename}':\n{tb}")
        raise HTTPException(500, f"OCR failed: {type(e).__name__}: {e}")


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("OCR_SERVICE_PORT", 8001))
    logger.info(f"OCR Service starting on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
