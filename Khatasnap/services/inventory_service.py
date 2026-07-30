"""
KhataSnap — Inventory Micro-service
Wraps inventory management (Tina's module) as standalone FastAPI service.
Port: 8004 (from .env → INVENTORY_SERVICE_PORT)

Uses the shared SQLite database through database.py.
"""

import os
import sys
import json
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
logger = logging.getLogger("inventory_service")

from database import get_conn, init_db

# ── App ──────────────────────────────────────────────────────────────────
app = FastAPI(title="KhataSnap Inventory Service")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok", "service": "inventory", "port": int(os.getenv("INVENTORY_SERVICE_PORT", 8004))}


@app.get("/snapshot")
async def snapshot():
    """Full inventory snapshot with stock status."""
    conn = get_conn()
    rows = conn.execute("""
        SELECT p.id, p.name, p.sku, p.current_qty, p.min_stock,
               p.selling_price, p.purchase_price, p.unit_type, p.emoji,
               c.name AS category
        FROM products p
        LEFT JOIN categories c ON p.category_id = c.id
        WHERE p.is_active = 1
        ORDER BY p.name
    """).fetchall()
    conn.close()

    items = []
    for r in rows:
        d = dict(r)
        d["stock_status"] = (
            "out" if d["current_qty"] == 0
            else "low" if d["current_qty"] <= d["min_stock"]
            else "ok"
        )
        items.append(d)

    return {"success": True, "data": items}


@app.post("/update")
async def update_stock(request: Request):
    """Apply an inventory delta."""
    body = await request.json()
    pid = body.get("product_id")
    qty_change = int(body.get("qty_change", 0))
    action = body.get("action", "adjust")
    reason = body.get("reason", "Service update")

    if not pid:
        raise HTTPException(400, "product_id required")

    conn = get_conn()
    row = conn.execute("SELECT id, name, current_qty FROM products WHERE id=?", (pid,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "Product not found")

    old_qty = row["current_qty"]
    new_qty = max(0, old_qty + qty_change)

    conn.execute("UPDATE products SET current_qty=?, updated_at=datetime('now') WHERE id=?", (new_qty, pid))

    import uuid
    txn_id = f"INV-{uuid.uuid4().hex[:8].upper()}"
    conn.execute("""
        INSERT INTO stock_logs
            (transaction_id, product_id, product_name, qty_change,
             action_type, source, reason, old_qty, new_qty)
        VALUES (?,?,?,?,?,?,?,?,?)
    """, (txn_id, pid, row["name"], qty_change, action, "inventory_service", reason, old_qty, new_qty))

    conn.commit()
    conn.close()

    return {
        "success": True,
        "data": {
            "product_id": pid,
            "name": row["name"],
            "old_qty": old_qty,
            "new_qty": new_qty,
            "qty_change": qty_change,
        }
    }


@app.get("/logs")
async def logs():
    """Recent stock change history."""
    conn = get_conn()
    rows = conn.execute("SELECT * FROM stock_logs ORDER BY created_at DESC LIMIT 100").fetchall()
    conn.close()
    return {"success": True, "data": [dict(r) for r in rows]}


@app.get("/low-stock")
async def low_stock():
    """Items at or below minimum stock."""
    conn = get_conn()
    rows = conn.execute("""
        SELECT p.id, p.name, p.current_qty, p.min_stock, p.emoji, c.name as category
        FROM products p
        LEFT JOIN categories c ON p.category_id = c.id
        WHERE p.is_active = 1 AND p.current_qty <= p.min_stock
        ORDER BY p.current_qty ASC
    """).fetchall()
    conn.close()
    return {"success": True, "data": [dict(r) for r in rows]}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("INVENTORY_SERVICE_PORT", 8004))
    init_db()
    logger.info(f"Inventory Service starting on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
