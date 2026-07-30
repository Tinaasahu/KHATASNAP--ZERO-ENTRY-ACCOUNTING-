"""
KhataSnap — FastAPI entry point.

IMPORTANT: os.environ must be patched BEFORE pipeline is imported,
because step4_ocr.py sets env vars at module level when it loads.
We do it here at the very top as a belt-and-suspenders measure.
"""
import os
# Must happen before any paddleocr / paddle import anywhere in the tree
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
os.environ.setdefault("FLAGS_use_mkldnn", "0")
os.environ.setdefault("GLOG_minloglevel", "3")

import logging
import traceback
from fastapi import FastAPI, UploadFile, File, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from collections import defaultdict
import time

from router import process_document


def sanitize_json(obj):
    """Recursively convert non-serializable numpy types to JSON-safe values."""
    import numpy as np
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


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

app = FastAPI(title="KhataSnap Invoice Scanner")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_request_log = defaultdict(list)
RATE_LIMIT = 30

ALLOWED_TYPES = {
    "image/jpeg", "image/jpg", "image/png",
    "image/webp", "image/bmp", "application/pdf"
}
MAX_SIZE_MB = 20


def check_rate_limit(ip: str):
    now = time.time()
    _request_log[ip] = [t for t in _request_log[ip] if now - t < 60]
    if len(_request_log[ip]) >= RATE_LIMIT:
        raise HTTPException(status_code=429, detail="Too many requests. Max 30/min.")
    _request_log[ip].append(now)


@app.get("/", response_class=HTMLResponse)
def home():
    with open("templates/index.html", "r", encoding="utf-8") as f:
        return f.read()


@app.get("/health")
def health():
    return {"status": "ok", "paddle_check_disabled": os.environ.get("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK")}


@app.post("/scan_invoice")
async def scan_invoice(request: Request, file: UploadFile = File(...)):
    check_rate_limit(request.client.host)

    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {file.content_type}. Allowed: JPG, PNG, WEBP, BMP, PDF"
        )

    contents = await file.read()
    if len(contents) > MAX_SIZE_MB * 1024 * 1024:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Max size is {MAX_SIZE_MB}MB."
        )

    try:
        result = process_document(contents, file.filename or "upload")
        return JSONResponse(content=sanitize_json(result))

    except HTTPException:
        raise  # re-raise rate limit / file errors as-is

    except Exception as e:
        # Log the FULL traceback so you can see the real error in the console
        tb = traceback.format_exc()
        logger.error(f"Pipeline error on '{file.filename}':\n{tb}")
        raise HTTPException(
            status_code=500,
            detail=f"Processing failed: {type(e).__name__}: {e}"
        )