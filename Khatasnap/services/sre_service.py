"""
KhataSnap — SRE Micro-service
Wraps the Smart Reconciliation Engine as a standalone FastAPI service.
Port: 8003 (from .env → SRE_SERVICE_PORT)

Does NOT modify sre_engine.py. Only provides HTTP endpoints.
"""

import os
import sys
import logging

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# ── Config ───────────────────────────────────────────────────────────────
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))

PARENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("sre_service")

# ── Import the existing SRE engine ───────────────────────────────────────
from sre_engine import (
    create_session,
    answer_question,
    save_learning,
    get_learning_log,
    get_session,
)

# ── App ──────────────────────────────────────────────────────────────────
app = FastAPI(title="KhataSnap SRE Service")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok", "service": "sre", "port": int(os.getenv("SRE_SERVICE_PORT", 8003))}


@app.post("/smart/start")
async def smart_start(request: Request):
    """Start an SRE reconciliation session."""
    body = await request.json()
    mismatch = float(body.get("mismatch_amount", 0))
    products = body.get("products", [])

    if mismatch <= 0:
        raise HTTPException(400, "mismatch_amount must be positive")

    try:
        session_id, session_data = create_session(products, mismatch)
        return {"success": True, "session_id": session_id, **session_data}
    except Exception as e:
        logger.error(f"SRE start error: {e}")
        raise HTTPException(500, str(e))


@app.post("/smart/answer")
async def smart_answer(request: Request):
    """Answer a yes/no question in an active SRE session."""
    body = await request.json()
    sid = body.get("session_id")
    ans = body.get("answer")
    question_dict = body.get("question") # new engine requires question_dict

    if not sid or ans is None or not question_dict:
        raise HTTPException(400, "session_id, question, and answer are required")

    try:
        session_data, error = answer_question(sid, question_dict, ans)
        if error:
            raise HTTPException(400, error)
        return {"success": True, "session_id": sid, **session_data}
    except Exception as e:
        logger.error(f"SRE answer error: {e}")
        raise HTTPException(500, str(e))


@app.post("/smart/learn")
async def smart_learn(request: Request):
    """Confirm result and train SRE memory."""
    body = await request.json()
    sid = body.get("session_id")
    confirmed = body.get("confirmed_items", [])
    mismatch = float(body.get("mismatch_amount", 0))

    try:
        # Get the session to pass question history and product details
        session_data = get_session(sid)
        if hasattr(session_data, 'get'):
             q_history = session_data.get('question_history')
             probs = session_data.get('probabilities')
             products = session_data.get('products')
        else:
             q_history, probs, products = None, None, None

        result = save_learning(confirmed, mismatch, q_history, probs, products)
        return {"success": True, "data": result}
    except Exception as e:
        logger.error(f"SRE learn error: {e}")
        raise HTTPException(500, str(e))


@app.get("/memory/stats")
async def memory_stats():
    """Get SRE memory statistics."""
    stats = get_learning_log()
    return {"success": True, "data": stats}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("SRE_SERVICE_PORT", 8003))
    logger.info(f"SRE Service starting on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
