"""
KhataSnap — Unified Orchestrator API
Central gateway that routes all requests through the proper pipeline.
Every DB write is gated by confirmation_status == 'confirmed' and SRE check.

Port: 8000 (from .env → ORCHESTRATOR_PORT)
"""

import os
import sys

_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if _CURRENT_DIR not in sys.path:
    sys.path.insert(0, _CURRENT_DIR)
import json
import uuid
import logging
import time
import httpx
from datetime import datetime
from contextlib import asynccontextmanager
import numpy as np

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# ── Load .env ────────────────────────────────────────────────────────────────
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

OCR_URL       = os.getenv("OCR_SERVICE_URL",       "http://127.0.0.1:8001")
VOICE_URL     = os.getenv("VOICE_SERVICE_URL",     "http://127.0.0.1:8002")
SRE_URL       = os.getenv("SRE_SERVICE_URL",       "http://127.0.0.1:8003")
INVENTORY_URL = os.getenv("INVENTORY_SERVICE_URL", "http://127.0.0.1:8004")

# ── Database ─────────────────────────────────────────────────────────────────
from database import init_db, get_conn

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO")),
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("orchestrator")


# ── Lifespan ─────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initialising database …")
    init_db()
    logger.info("Database ready.")
    yield


# ── App ──────────────────────────────────────────────────────────────────────
app = FastAPI(title="KhataSnap Orchestrator", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Helpers ──────────────────────────────────────────────────────────────────
def _bill_id():
    now = datetime.now()
    return f"TXN-{now.strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"


def _now():
    return datetime.now().isoformat()


def sanitize_json(obj):
    """Convert numpy types and non-serializable objects to JSON-safe Python types."""
    if isinstance(obj, dict):
        return {k: sanitize_json(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [sanitize_json(v) for v in obj]
    elif isinstance(obj, np.generic):
        return obj.item()
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif hasattr(obj, 'item') and callable(getattr(obj, 'item')):
        try:
            return obj.item()
        except Exception:
            pass
    return obj


def _ok(data, sre_flags=None):
    return JSONResponse({
        "success": True,
        "data": sanitize_json(data),
        "error": None,
        "sre_flags": sanitize_json(sre_flags or []),
        "timestamp": _now(),
    })


def _err(msg, status=400):
    return JSONResponse(
        {"success": False, "data": None, "error": msg, "sre_flags": [], "timestamp": _now()},
        status_code=status,
    )


def _products_with_aliases(conn):
    rows = conn.execute("""
        SELECT p.id, p.name, p.selling_price, p.current_qty, p.emoji,
               GROUP_CONCAT(pa.alias, '|||') AS aliases
        FROM products p
        LEFT JOIN product_aliases pa ON pa.product_id = p.id
        WHERE p.is_active = 1
        GROUP BY p.id
    """).fetchall()
    res = []
    for r in rows:
        d = dict(r)
        alias_list = [a.lower().strip() for a in (d.pop("aliases") or "").split("|||") if a.strip()]
        d["aliases"] = alias_list
        res.append(d)
    return res



async def _forward_post(url: str, payload: dict, timeout: float = 30.0):
    """POST JSON to a downstream micro-service and return decoded body."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json()
    except httpx.ConnectError:
        raise HTTPException(503, f"Service unavailable: {url}")
    except httpx.HTTPStatusError as exc:
        raise HTTPException(exc.response.status_code, exc.response.text)
    except Exception as exc:
        raise HTTPException(500, f"Service call failed: {exc}")


async def _forward_file(url: str, file: UploadFile, timeout: float = 60.0):
    """POST a file upload to a downstream micro-service."""
    try:
        contents = await file.read()
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                url,
                files={"file": (file.filename, contents, file.content_type)},
            )
            resp.raise_for_status()
            return resp.json()
    except httpx.ConnectError:
        raise HTTPException(503, f"Service unavailable: {url}")
    except httpx.HTTPStatusError as exc:
        raise HTTPException(exc.response.status_code, exc.response.text)
    except Exception as exc:
        raise HTTPException(500, f"Service call failed: {exc}")


# ── Health ───────────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok", "service": "orchestrator", "timestamp": _now()}


# ═════════════════════════════════════════════════════════════════════════════
# 1. PRODUCTS  (local DB — no downstream service needed)
# ═════════════════════════════════════════════════════════════════════════════

@app.post("/api/inventory/add-new-item")
async def add_new_item_from_smart_checks(request: Request):
    """Adds a new item or returns an existing match for price alias grouping."""
    body = await request.json()
    name = (body.get("name") or "").strip()
    price = body.get("price")
    
    if not name or price is None:
        return _err("Name and price required", 400)
    
    # Generate a unique SKU
    slug = ''.join(c for c in name.upper() if c.isalnum())[:6]
    sku = f"KS-{slug}-{uuid.uuid4().hex[:4].upper()}"
        
    conn = get_conn()
    try:
        cur = conn.cursor()
        existing = cur.execute("""
            SELECT id, name, selling_price, current_qty, emoji
            FROM products
            WHERE LOWER(name) = LOWER(?) AND is_active = 1
            LIMIT 1
        """, (name,)).fetchone()

        if existing:
            item = {
                "id": existing["id"],
                "name": existing["name"],
                "price": existing["selling_price"],
                "quantity": existing["current_qty"],
                "emoji": existing["emoji"],
            }
            return _ok({
                "status": "exists",
                "existing_item": item,
                "new_price": price,
                "message": f"{existing['name']} already exists at ₹{existing['selling_price']}. Do you want to add ₹{price} as another price for it?",
            })

        cur.execute("""
            INSERT INTO products (name, sku, selling_price, purchase_price, mrp, current_qty, min_stock, emoji, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 0, 5, '📦', 1, datetime('now'), datetime('now'))
        """, (name, sku, price, price, price))
        item_id = cur.lastrowid
        
        conn.commit()
        return _ok({
            "status": "created",
            "item": {
                "id": item_id,
                "name": name,
                "price": price,
                "quantity": 0,
                "emoji": "📦",
            },
        })
    except Exception as e:
        conn.rollback()
        return _err(str(e), 500)
    finally:
        conn.close()

@app.get("/api/products")
async def get_products():
    conn = get_conn()
    rows = conn.execute("""
        SELECT p.*, c.name AS category_name
        FROM products p
        LEFT JOIN categories c ON p.category_id = c.id
        WHERE p.is_active = 1
        ORDER BY p.name
    """).fetchall()
    conn.close()
    products = [dict(r) for r in rows]
    return _ok(products)


@app.get("/api/categories")
async def get_categories():
    conn = get_conn()
    rows = conn.execute("SELECT id, name FROM categories ORDER BY name").fetchall()
    conn.close()
    return _ok([dict(r) for r in rows])


@app.get("/api/suppliers")
async def get_suppliers():
    conn = get_conn()
    rows = conn.execute("SELECT id, name, phone, address FROM suppliers ORDER BY name").fetchall()
    conn.close()
    return _ok([dict(r) for r in rows])


@app.post("/api/products/bulk-update")
async def bulk_update_products(request: Request):
    body = await request.json()
    ids = body.get("ids") or []
    fields = body.get("fields") or {}
    if not ids or not isinstance(ids, list):
        return _err("ids must be a non-empty list", 400)
    if not fields or not isinstance(fields, dict):
        return _err("fields must be a non-empty object", 400)

    allowed = {
        "name", "selling_price", "purchase_price", "mrp",
        "min_stock", "emoji", "notes",
        "unit_type", "brand", "barcode", "expiry_date", "supplier_id",
        "gst_rate", "discount_pct",
        "variant_group_id", "variant_label",
    }

    updates = []
    params = []
    for k, v in fields.items():
        if k in allowed:
            updates.append(f"{k}=?")
            params.append(v)
        elif k == "category":
            # handle category as a special field
            pass

    if "category" in fields:
        conn = get_conn()
        try:
            conn.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", (fields["category"],))
            cr = conn.execute("SELECT id FROM categories WHERE name=?", (fields["category"],)).fetchone()
            updates.append("category_id=?")
            params.append(cr["id"] if cr else None)
            conn.commit()
        finally:
            conn.close()

    if not updates:
        return _err("No allowed fields provided", 400)

    conn = get_conn()
    try:
        before_rows = conn.execute(
            f"SELECT * FROM products WHERE id IN ({','.join('?' for _ in ids)})",
            [int(i) for i in ids],
        ).fetchall()
        before = {int(r["id"]): dict(r) for r in before_rows}

        q_marks = ",".join("?" for _ in ids)
        sql = f"UPDATE products SET {','.join(updates)}, updated_at=datetime('now') WHERE id IN ({q_marks})"
        conn.execute(sql, params + [int(i) for i in ids])

        after_rows = conn.execute(
            f"SELECT * FROM products WHERE id IN ({','.join('?' for _ in ids)})",
            [int(i) for i in ids],
        ).fetchall()
        for r in after_rows:
            pid = int(r["id"])
            conn.execute(
                """
                INSERT INTO product_audit_logs (product_id, action, before_json, after_json, source)
                VALUES (?,?,?,?,?)
                """,
                (
                    pid,
                    "bulk_update",
                    json.dumps(before.get(pid)),
                    json.dumps(dict(r)),
                    "api/products/bulk-update",
                ),
            )

        conn.commit()
    finally:
        conn.close()
    return _ok({"updated_count": len(ids)})


@app.post("/api/products")
async def add_product(request: Request):
    body = await request.json()
    name = body.get("name", "").strip()
    if not name:
        return _err("Product name is required")

    conn = get_conn()
    # Find or create category
    cat_name = body.get("category", "Other")
    conn.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", (cat_name,))
    cat_row = conn.execute("SELECT id FROM categories WHERE name=?", (cat_name,)).fetchone()
    cat_id = cat_row["id"] if cat_row else None

    slug = ''.join(c for c in name.upper() if c.isalnum())[:6]
    sku = f"KS-{slug}-{uuid.uuid4().hex[:3].upper()}"
    selling_price = float(body.get("selling_price", body.get("price", 0)) or 0)
    purchase_price = float(body.get("purchase_price", selling_price) or 0)
    mrp = float(body.get("mrp", selling_price) or 0)
    brand = (body.get("brand") or "").strip() or None
    variant_group_id = (body.get("variant_group_id") or "").strip() or None
    variant_label = (body.get("variant_label") or "").strip() or None
    barcode = (body.get("barcode") or "").strip() or None
    unit_type = (body.get("unit_type") or body.get("unit") or "pcs").strip()
    expiry_date = (body.get("expiry_date") or "").strip() or None
    supplier_id = body.get("supplier_id")
    supplier_id = int(supplier_id) if supplier_id not in (None, "", "null") else None
    gst_rate = float(body.get("gst_rate", 0) or 0)
    discount_pct = float(body.get("discount_pct", body.get("discount", 0)) or 0)
    notes = (body.get("notes") or "").strip() or None

    conn.execute("""
        INSERT INTO products (
          name, category_id, brand, variant_group_id, variant_label, sku, barcode,
          purchase_price, selling_price, mrp, unit_type,
          current_qty, min_stock, expiry_date, supplier_id,
          gst_rate, discount_pct, emoji, notes
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
      name, cat_id, brand, variant_group_id, variant_label, sku, barcode,
      purchase_price, selling_price, mrp, unit_type,
      int(body.get("stock", body.get("current_qty", 0)) or 0),
      int(body.get("min_stock", 5) or 5),
      expiry_date, supplier_id,
      gst_rate, discount_pct, body.get("emoji", "📦"), notes
    ))
    conn.commit()
    pid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    # audit
    row = conn.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
    if row:
        conn.execute(
            """
            INSERT INTO product_audit_logs (product_id, action, before_json, after_json, source)
            VALUES (?,?,?,?,?)
            """,
            (pid, "create", None, json.dumps(dict(row)), "api/products"),
        )
        conn.commit()

    conn.close()
    return _ok({"id": pid, "name": name, "sku": sku})


@app.put("/api/products/{product_id}")
async def update_product(product_id: int, request: Request):
    body = await request.json()
    conn = get_conn()
    row = conn.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
    if not row:
        conn.close()
        return _err("Product not found", 404)

    before = dict(row)

    updates = []
    params = []
    for field in [
        "name", "selling_price", "purchase_price", "mrp",
        "min_stock", "emoji", "notes",
        "unit_type", "brand", "barcode", "expiry_date", "supplier_id",
        "gst_rate", "discount_pct",
        "variant_group_id", "variant_label",
    ]:
        if field in body:
            updates.append(f"{field}=?")
            params.append(body[field])
    if "category" in body:
        conn.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", (body["category"],))
        cr = conn.execute("SELECT id FROM categories WHERE name=?", (body["category"],)).fetchone()
        updates.append("category_id=?")
        params.append(cr["id"] if cr else None)

    if updates:
        updates.append("updated_at=datetime('now')")
        params.append(product_id)
        conn.execute(f"UPDATE products SET {','.join(updates)} WHERE id=?", params)
        after_row = conn.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
        if after_row:
            conn.execute(
                """
                INSERT INTO product_audit_logs (product_id, action, before_json, after_json, source)
                VALUES (?,?,?,?,?)
                """,
                (product_id, "update", json.dumps(before), json.dumps(dict(after_row)), "api/products/{id}"),
            )
        conn.commit()
    conn.close()
    return _ok({"updated": product_id})


@app.delete("/api/products/{product_id}")
async def delete_product(product_id: int):
    conn = get_conn()
    row = conn.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
    if not row:
        conn.close()
        return _err("Product not found", 404)
    before = dict(row)

    conn.execute("UPDATE products SET is_active=0, updated_at=datetime('now') WHERE id=?", (product_id,))
    after_row = conn.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
    conn.execute(
        """
        INSERT INTO product_audit_logs (product_id, action, before_json, after_json, source)
        VALUES (?,?,?,?,?)
        """,
        (product_id, "delete", json.dumps(before), json.dumps(dict(after_row) if after_row else None), "api/products/{id}:delete"),
    )
    conn.commit()
    conn.close()
    return _ok({"deleted": product_id})


@app.get("/api/products/{product_id}/audit")
async def product_audit(product_id: int, limit: int = 50):
    limit = max(1, min(int(limit or 50), 200))
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT id, product_id, action, source, created_at, before_json, after_json
        FROM product_audit_logs
        WHERE product_id=?
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (product_id, limit),
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["before"] = json.loads(d.get("before_json") or "null")
        except Exception:
            d["before"] = None
        try:
            d["after"] = json.loads(d.get("after_json") or "null")
        except Exception:
            d["after"] = None
        d.pop("before_json", None)
        d.pop("after_json", None)
        out.append(d)
    return _ok(out)


@app.post("/api/reconciliation/learn")
async def reconciliation_learn(request: Request):
    body = await request.json()
    raw_text = (body.get("raw_text") or body.get("text") or "").strip()
    product_id = body.get("product_id")
    if not raw_text or not product_id:
        return _err("raw_text and product_id are required", 400)

    from helpers import normalize
    norm_text = normalize(raw_text)
    conn = get_conn()
    try:
        pr = conn.execute(
            "SELECT id, variant_group_id, variant_label FROM products WHERE id=? AND is_active=1",
            (int(product_id),),
        ).fetchone()
        if not pr:
            return _err("Product not found", 404)

        conn.execute(
            """
            INSERT INTO ocr_corrections (norm_text, product_id, variant_group_id, variant_label, times_used, last_used_at)
            VALUES (?,?,?,?,1,datetime('now'))
            ON CONFLICT(norm_text, product_id) DO UPDATE SET
              times_used = times_used + 1,
              last_used_at = datetime('now'),
              variant_group_id = excluded.variant_group_id,
              variant_label = excluded.variant_label
            """,
            (norm_text, int(product_id), pr["variant_group_id"], pr["variant_label"]),
        )
        conn.commit()
        return _ok({"status": "ok", "norm_text": norm_text, "product_id": int(product_id)})
    finally:
        conn.close()


@app.get("/api/reconciliation/flags")
async def reconciliation_flags(status: str = "pending", limit: int = 50):
    status = (status or "pending").strip().lower()
    limit = max(1, min(int(limit or 50), 200))
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT id, source, ref_id, flag_type, severity, payload_json, resolution, resolved_by, resolved_at, created_at
        FROM reconciliation_flags
        WHERE resolution = ?
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (status, limit),
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["payload"] = json.loads(d.get("payload_json") or "null")
        except Exception:
            d["payload"] = None
        d.pop("payload_json", None)
        out.append(d)
    return _ok(out)


@app.post("/api/reconciliation/flags/{flag_id}/resolve")
async def reconcile_resolve(flag_id: int, request: Request):
    body = await request.json()
    resolution = (body.get("resolution") or "resolved").strip().lower()
    if resolution not in ("resolved", "ignored"):
        return _err("resolution must be resolved|ignored", 400)
    resolved_by = (body.get("resolved_by") or "ui").strip()
    learn = bool(body.get("learn"))
    raw_text = (body.get("raw_text") or "").strip()
    product_id = body.get("product_id")
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM reconciliation_flags WHERE id=?", (int(flag_id),)).fetchone()
        if not row:
            return _err("Flag not found", 404)
        conn.execute(
            """
            UPDATE reconciliation_flags
            SET resolution=?, resolved_by=?, resolved_at=datetime('now')
            WHERE id=?
            """,
            (resolution, resolved_by, int(flag_id)),
        )
        # Optional learning hook for future OCR corrections
        if learn and raw_text and product_id and resolution == "resolved":
            from helpers import normalize
            norm_text = normalize(raw_text)
            pr = conn.execute(
                "SELECT id, variant_group_id, variant_label FROM products WHERE id=? AND is_active=1",
                (int(product_id),),
            ).fetchone()
            if pr:
                conn.execute(
                    """
                    INSERT INTO ocr_corrections (norm_text, product_id, variant_group_id, variant_label, times_used, last_used_at)
                    VALUES (?,?,?,?,1,datetime('now'))
                    ON CONFLICT(norm_text, product_id) DO UPDATE SET
                      times_used = times_used + 1,
                      last_used_at = datetime('now'),
                      variant_group_id = excluded.variant_group_id,
                      variant_label = excluded.variant_label
                    """,
                    (norm_text, int(product_id), pr["variant_group_id"], pr["variant_label"]),
                )
        conn.commit()
        return _ok({"status": "ok", "id": int(flag_id), "resolution": resolution})
    finally:
        conn.close()


@app.post("/api/reconciliation/run")
async def reconciliation_run(request: Request):
    """
    Real-time reconciliation: scan last N minutes of activity and flag discrepancies.
    Current heuristic (safe + cheap):
    - Flag OCR/confirmed bills where any line item has match_status ambiguous/needs_selection but no product_id.
    - Flag stock_logs where product_id is null (should be rare).
    """
    body = await request.json()
    minutes = max(5, min(int(body.get("minutes") or 60), 24 * 60))
    conn = get_conn()
    created = 0
    try:
        # 1) Bill-level flags for unresolved items saved in confirmed_bills.items JSON
        bills = conn.execute(
            """
            SELECT bill_id, source, items, confirmed_at
            FROM confirmed_bills
            WHERE confirmation_status='confirmed'
              AND confirmed_at >= datetime('now', ?)
            ORDER BY confirmed_at DESC
            LIMIT 50
            """,
            (f"-{minutes} minutes",),
        ).fetchall()
        for b in bills:
            try:
                items = json.loads(b["items"] or "[]")
            except Exception:
                items = []
            unresolved = []
            for idx, it in enumerate(items):
                if it.get("product_id"):
                    continue
                st = it.get("match_status")
                if st in ("ambiguous", "needs_selection") or it.get("needs_user_selection"):
                    unresolved.append(
                        {
                            "index": idx,
                            "name": it.get("name"),
                            "raw_text": it.get("raw_text"),
                            "match_status": st,
                            "candidates": it.get("match_candidates") or [],
                        }
                    )
            if unresolved:
                payload = {
                    "bill_id": b["bill_id"],
                    "confirmed_at": b["confirmed_at"],
                    "unresolved_items": unresolved,
                }
                conn.execute(
                    """
                    INSERT INTO reconciliation_flags (source, ref_id, flag_type, severity, payload_json)
                    VALUES (?,?,?,?,?)
                    """,
                    (b["source"], b["bill_id"], "ambiguous_variant", "warning", json.dumps(payload)),
                )
                created += 1

        # 2) Stock logs missing product_id
        sl = conn.execute(
            """
            SELECT transaction_id, product_name, qty_change, action_type, source, reason, created_at
            FROM stock_logs
            WHERE product_id IS NULL
              AND created_at >= datetime('now', ?)
            ORDER BY created_at DESC
            LIMIT 25
            """,
            (f"-{minutes} minutes",),
        ).fetchall()
        for r in sl:
            payload = dict(r)
            conn.execute(
                """
                INSERT INTO reconciliation_flags (source, ref_id, flag_type, severity, payload_json)
                VALUES (?,?,?,?,?)
                """,
                (r["source"], r["transaction_id"], "mismatch", "info", json.dumps(payload)),
            )
            created += 1

        conn.commit()
        return _ok({"status": "ok", "created": created, "window_minutes": minutes})
    finally:
        conn.close()


@app.get("/api/reconciliation/eod")
async def reconciliation_eod(day: str = ""):
    """
    End-of-day reconciliation summary for a given YYYY-MM-DD (default today).
    """
    day = (day or datetime.now().strftime("%Y-%m-%d")).strip()
    conn = get_conn()
    try:
        pending = conn.execute(
            "SELECT COUNT(*) AS c FROM reconciliation_flags WHERE resolution='pending' AND date(created_at)=?",
            (day,),
        ).fetchone()["c"]
        resolved = conn.execute(
            "SELECT COUNT(*) AS c FROM reconciliation_flags WHERE resolution='resolved' AND date(created_at)=?",
            (day,),
        ).fetchone()["c"]
        ignored = conn.execute(
            "SELECT COUNT(*) AS c FROM reconciliation_flags WHERE resolution='ignored' AND date(created_at)=?",
            (day,),
        ).fetchone()["c"]
        by_type = conn.execute(
            """
            SELECT flag_type, COUNT(*) AS c
            FROM reconciliation_flags
            WHERE date(created_at)=?
            GROUP BY flag_type
            ORDER BY c DESC
            """,
            (day,),
        ).fetchall()
        return _ok(
            {
                "day": day,
                "pending": int(pending or 0),
                "resolved": int(resolved or 0),
                "ignored": int(ignored or 0),
                "by_type": [dict(r) for r in by_type],
            }
        )
    finally:
        conn.close()


# ═════════════════════════════════════════════════════════════════════════════
# 2. OCR UPLOAD  →  returns extracted data, NO DB write
# ═════════════════════════════════════════════════════════════════════════════

@app.post("/api/ocr/upload")
async def ocr_upload(file: UploadFile = File(...)):
    logger.info(f"OCR upload: {file.filename} ({file.content_type})")

    contents = await file.read()
    result = None

    # Try external OCR service first if running
    if OCR_URL:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.post(
                    f"{OCR_URL}/scan",
                    files={"file": (file.filename or "upload.jpg", contents, file.content_type or "image/jpeg")}
                )
                if resp.status_code == 200:
                    result = resp.json()
        except Exception as e:
            logger.info(f"External OCR at {OCR_URL} unavailable ({e}), using built-in OCR pipeline.")

    # If external service is unavailable, execute built-in OCR pipeline directly
    if not result:
        try:
            from orchestrator import process_invoice
            result = process_invoice(contents, file.filename or "upload.jpg")
        except Exception as pipe_err:
            logger.error(f"In-process OCR pipeline error: {pipe_err}")
            result = {"items": [], "total": 0}

    # Build DATA_CONTRACT bill shape (pending confirmation)
    items = []
    raw_items = result.get("items") or result.get("line_items") or []
    needs_user_selection = False

    # Hardcoded catalog mapping (temporary, as requested)
    from catalog_mapping import map_to_catalog

    # If table extraction failed, try mapping directly from OCR blocks text
    if not raw_items:
        ocr_blocks = result.get("ocr_blocks") or []
        # keep higher-confidence, non-trivial tokens
        candidates = []
        for b in ocr_blocks:
            t = str(b.get("text", "")).strip()
            if len(t) < 3:
                continue
            # avoid pure numbers
            if t.replace(".", "").replace(",", "").isdigit():
                continue
            candidates.append(t)

        # Build synthetic "raw_items" from unique catalog hits
        seen_keys = set()
        for t in candidates:
            mapped = map_to_catalog(t)
            if mapped.is_unmapped:
                continue
            key = (mapped.standard_name, mapped.brand)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            raw_items.append({"raw_text": t, "name": t, "qty": 1, "unit": "pcs", "rate": 0, "amount": 0, "confidence": mapped.confidence})

    for idx, it in enumerate(raw_items):
        raw_name = it.get("raw_text") or it.get("name") or it.get("product_name") or f"Item {idx+1}"
        mapped = map_to_catalog(str(raw_name))
        if mapped.needs_user_selection:
            needs_user_selection = True

        items.append({
            # Keep original OCR value as raw_text, but prefer catalog-mapped display when available
            "raw_text":     str(raw_name),
            "standard_name": mapped.standard_name,
            "brand":         mapped.brand,
            "variant":       mapped.variant,
            "is_unmapped":   bool(mapped.is_unmapped),
            "needs_user_selection": bool(mapped.needs_user_selection),

            # Existing fields used by current UI/DB flow
            "name":         (f"{mapped.brand} {mapped.standard_name} {mapped.variant}".strip()
                             if (mapped.standard_name or mapped.brand) and not mapped.is_unmapped
                             else str(raw_name)),
            "matched_name": None,
            "product_id":   None,
            "match_status": "unmatched",
            "match_candidates": [],
            "qty":          it.get("qty", it.get("quantity", 1)),
            "unit":         it.get("unit", "pcs"),
            "price":        float(it.get("rate", it.get("price", it.get("mrp", 0)))),
            "amount":       float(it.get("amount", 0)),
            "confidence":   float(it.get("confidence", mapped.confidence or 0.5)),
            "match_method": "ocr_raw",
        })

    # Heuristic bill type for inventory intent.
    # PURCHASE_BILL if any supplier/invoice indicators exist; else SALE_BILL.
    bill_type = "PURCHASE_BILL" if (
        (result.get("gstin") or result.get("vendor_name") or result.get("invoice_no"))
    ) else "SALE_BILL"

    bill = {
        "bill_id":              _bill_id(),
        "source":               "ocr",
        "bill_type":            bill_type,
        "vendor_name":          result.get("vendor_name"),
        "invoice_no":           result.get("invoice_no"),
        "invoice_date":         result.get("invoice_date"),
        "needs_user_selection": needs_user_selection,
        "items":                items,
        "subtotal":             float(result.get("taxable_amount", 0)),
        "tax":                  float(result.get("cgst", 0)) + float(result.get("sgst", 0)),
        "total_amount":         float(result.get("total", 0)),
        "payment_mode":         "cash",
        "confirmation_status":  "pending",
        "sre_flags":            [],
        "raw_data":             result,
        "created_at":           _now(),
        "confirmed_at":         None,
    }

    # Variant-safe matching against local product DB (never auto-select when ambiguous)
    conn = get_conn()
    db_products = [dict(r) for r in conn.execute(
        """
        SELECT
          id, name, brand, barcode, variant_group_id, variant_label,
          selling_price, purchase_price, unit_type, emoji
        FROM products
        WHERE is_active=1
        """
    ).fetchall()]

    # Load learned OCR corrections (norm_text -> most-used product_id)
    corr_rows = conn.execute(
        """
        SELECT norm_text, product_id, times_used
        FROM ocr_corrections
        ORDER BY times_used DESC, last_used_at DESC
        """
    ).fetchall()
    corrections = {}
    for r in corr_rows:
        nt = str(r["norm_text"] or "").strip()
        pid = r["product_id"]
        if not nt or not pid:
            continue
        # keep the strongest correction per norm_text
        if nt not in corrections:
            corrections[nt] = {"product_id": int(pid), "times_used": int(r["times_used"] or 0)}
    conn.close()

    import re
    from difflib import SequenceMatcher

    _SPACE_RE = re.compile(r"\s+")
    _NON_ALNUM_RE = re.compile(r"[^a-z0-9\s]+")

    def _norm(s: str) -> str:
        s = (s or "").lower()
        s = _NON_ALNUM_RE.sub(" ", s)
        s = _SPACE_RE.sub(" ", s).strip()
        return s

    def _ratio(a: str, b: str) -> float:
        a = a.strip()
        b = b.strip()
        if not a or not b:
            return 0.0
        return SequenceMatcher(None, a, b).ratio()

    def _norm_variant(v: str) -> str:
        t = _norm(v)
        t = t.replace(" ", "")
        t = t.replace("litre", "l").replace("liter", "l")
        if t.endswith("l"):
            t = t[:-1] + "L"
        return t

    for item in bill["items"]:
        item_name_n = _norm(item.get("name") or "")
        std_n = _norm(item.get("standard_name") or "")
        brand_n = _norm(item.get("brand") or "")
        variant_n = _norm_variant(item.get("variant") or "")

        # Learned correction overrides (strongest signal; still respects "no auto-select if ambiguous variants")
        corr = corrections.get(item_name_n) or corrections.get(_norm(item.get("raw_text") or ""))
        if corr and not item.get("needs_user_selection"):
            pid = corr["product_id"]
            matched = next((p for p in db_products if int(p.get("id")) == int(pid)), None)
            if matched:
                item["matched_name"] = matched.get("name")
                item["product_id"] = matched.get("id")
                item["confidence"] = max(item["confidence"], 0.93)
                item["match_method"] = "learned_correction"
                item["match_status"] = "matched"
                if item["price"] == 0:
                    item["price"] = float(matched.get("selling_price") or 0)
                    item["amount"] = item["price"] * item["qty"]
                continue

        candidates = []
        for p in db_products:
            pname_n = _norm(p.get("name") or "")
            pbrand_n = _norm(p.get("brand") or "")
            pvariant_n = _norm_variant(p.get("variant_label") or "")

            base = _ratio(item_name_n, pname_n)
            score = base
            reasons = []

            if brand_n and pbrand_n and brand_n == pbrand_n:
                score = max(score, 0.80)
                reasons.append("brand_exact")

            if std_n and std_n in pname_n:
                score = max(score, 0.78)
                reasons.append("std_in_name")

            if brand_n and brand_n in pname_n:
                score = max(score, 0.78)
                reasons.append("brand_in_name")

            if variant_n and pvariant_n:
                if variant_n == pvariant_n:
                    score = max(score, 0.92)
                    reasons.append("variant_exact")
                else:
                    # If OCR thinks a variant but product has different variant -> penalize (avoid wrong auto-pick)
                    score = min(score, 0.74)
                    reasons.append("variant_mismatch")

            # keep only plausible candidates
            if score >= 0.70:
                candidates.append({
                    "id": p.get("id"),
                    "name": p.get("name"),
                    "emoji": p.get("emoji") or "📦",
                    "selling_price": float(p.get("selling_price") or 0),
                    "purchase_price": float(p.get("purchase_price") or 0),
                    "brand": p.get("brand"),
                    "variant_group_id": p.get("variant_group_id"),
                    "variant_label": p.get("variant_label"),
                    "barcode": p.get("barcode"),
                    "score": round(float(score), 3),
                    "reasons": reasons,
                })

        candidates.sort(key=lambda x: x["score"], reverse=True)
        item["match_candidates"] = candidates[:5]

        # If catalog indicates ambiguity, never auto-select
        if item.get("needs_user_selection"):
            item["match_status"] = "needs_selection"
            bill["needs_user_selection"] = True
            continue

        if not candidates:
            item["match_status"] = "unmatched"
            continue

        top = candidates[0]
        second = candidates[1] if len(candidates) > 1 else None
        top_score = float(top["score"] or 0)
        second_score = float(second["score"] or 0) if second else 0.0

        # Auto-match only if it's clearly unique, high confidence, and not a variant ambiguity
        is_clear = (top_score >= 0.86) and ((top_score - second_score) >= 0.08)

        # If OCR variant exists but product variant_label missing, treat as ambiguous (require user to confirm)
        if variant_n and not _norm_variant(top.get("variant_label") or ""):
            is_clear = False

        if is_clear:
            item["matched_name"] = top["name"]
            item["product_id"] = top["id"]
            item["confidence"] = max(item["confidence"], top_score)
            item["match_method"] = "variant_safe"
            item["match_status"] = "matched"
            if item["price"] == 0:
                item["price"] = top.get("selling_price", 0)
                item["amount"] = item["price"] * item["qty"]
        else:
            item["match_status"] = "ambiguous"
            bill["needs_user_selection"] = True

    # Recalculate total
    bill["subtotal"] = sum(i["amount"] for i in bill["items"])
    if bill["total_amount"] == 0:
        bill["total_amount"] = bill["subtotal"] + bill["tax"]

    return _ok(bill)


# ═════════════════════════════════════════════════════════════════════════════
# 3. OCR CONFIRM  →  SRE check  →  DB write  →  inventory update
# ═════════════════════════════════════════════════════════════════════════════

@app.post("/api/ocr/confirm")
async def ocr_confirm(request: Request):
    bill = await request.json()
    # Frontend may send a minimal contract payload (see buildBillPayload).
    # Make confirm robust by filling required fields.
    if not bill.get("bill_id"):
        bill["bill_id"] = _bill_id()
    if not bill.get("source"):
        bill["source"] = "ocr"
    if not bill.get("created_at"):
        bill["created_at"] = _now()
    if "items" not in bill or bill["items"] is None:
        bill["items"] = []

    # Normalize numeric totals if missing
    try:
        bill["subtotal"] = float(bill.get("subtotal") or sum(float(i.get("amount", 0) or 0) for i in bill["items"]))
    except Exception:
        bill["subtotal"] = 0.0
    try:
        bill["tax"] = float(bill.get("tax") or 0)
    except Exception:
        bill["tax"] = 0.0
    try:
        bill["total_amount"] = float(bill.get("total_amount") or (bill["subtotal"] + bill["tax"]))
    except Exception:
        bill["total_amount"] = bill["subtotal"] + bill["tax"]
    if not bill.get("payment_mode"):
        bill["payment_mode"] = "cash"

    bill["confirmation_status"] = "confirmed"
    bill["confirmed_at"] = _now()

    # ── Variant safety gate ───────────────────────────────────────────────
    unresolved = []
    for idx, it in enumerate(bill.get("items") or []):
        if not it.get("product_id") and (it.get("match_status") in ("ambiguous", "needs_selection") or it.get("needs_user_selection")):
            unresolved.append({
                "index": idx,
                "name": it.get("name"),
                "raw_text": it.get("raw_text"),
                "standard_name": it.get("standard_name"),
                "brand": it.get("brand"),
                "variant": it.get("variant"),
            })
    if unresolved:
        return _err(
            "Some items need manual variant selection before confirming.",
            409,
            unresolved_items=unresolved,
        )

    # ── SRE gate ──────────────────────────────────────────────────────────
    client_flags = bill.get("sre_flags")
    if client_flags is not None:
        sre_flags = client_flags
    else:
        sre_flags = await _run_sre_check(bill)
        
    bill["sre_flags"] = sre_flags

    # ── Inventory update ─────────────────────────────────────────────────
    # Inward bills confirmed via OCR are purchases/restock (ADD stock to inventory)
    bt = (bill.get("bill_type") or "").upper()
    if bt == "SALE_BILL":
        action = "sale"
    else:
        # Default for OCR purchase bills is always restock (+qty)
        action = "restock"

    conn = get_conn()
    stock_updates = []
    for item in bill["items"]:
        pid = item.get("product_id")
        qty = item.get("qty", 0) or 0
        delta = qty if action == "restock" else -qty

        # Auto-create product if missing in inventory
        if not pid:
            item_name = (item.get("matched_name") or item.get("name") or "").strip()
            if item_name:
                try:
                    # Ensure "Other" category exists
                    conn.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", ("Other",))
                    cat_row = conn.execute("SELECT id FROM categories WHERE name=?", ("Other",)).fetchone()
                    cat_id = cat_row["id"] if cat_row else None

                    slug = ''.join(c for c in item_name.upper() if c.isalnum())[:6]
                    sku = f"KS-{slug}-{uuid.uuid4().hex[:3].upper()}"
                    price = float(item.get("price", 0) or 0)

                    # Start qty at 0; we apply delta via unified stock update below.
                    conn.execute("""
                        INSERT INTO products (name, category_id, sku, purchase_price, selling_price, mrp,
                                              current_qty, min_stock, emoji)
                        VALUES (?,?,?,?,?,?,?,?,?)
                    """, (item_name, cat_id, sku, price, price, price, 0, 5, "📦"))
                    pid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

                    item["product_id"] = pid
                    item["matched_name"] = item_name
                    item["match_method"] = "auto_created"
                except Exception:
                    # If we fail to create the product, skip inventory update for this line item
                    pid = None

        if pid:

            row = conn.execute("SELECT current_qty FROM products WHERE id=?", (pid,)).fetchone()
            old_qty = row["current_qty"] if row else 0
            new_qty = max(0, old_qty + delta)

            conn.execute("UPDATE products SET current_qty=?, updated_at=datetime('now') WHERE id=?",
                         (new_qty, pid))

            txn_id = f"{bill['bill_id']}-{pid}"
            conn.execute("""
                INSERT OR IGNORE INTO stock_logs
                    (transaction_id, product_id, product_name, qty_change,
                     action_type, source, reason, old_qty, new_qty)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, (txn_id, pid, item.get("matched_name", item["name"]),
                  delta, action, bill["source"],
                  f"Bill {bill['bill_id']}", old_qty, new_qty))

            stock_updates.append({
                "product_id": pid,
                "name": item.get("matched_name", item["name"]),
                "action": action,
                "qty_change": delta,
                "old_qty": old_qty,
                "new_qty": new_qty,
            })

    # ── DB write ──────────────────────────────────────────────────────────
    conn.execute("""
        INSERT OR REPLACE INTO confirmed_bills
            (bill_id, source, vendor_name, invoice_no, invoice_date, items,
             subtotal, tax, total_amount, payment_mode, confirmation_status,
             raw_data, sre_flags, created_at, confirmed_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        bill["bill_id"], bill["source"], bill.get("vendor_name"),
        bill.get("invoice_no"), bill.get("invoice_date"),
        json.dumps(bill["items"]), bill["subtotal"], bill["tax"],
        bill["total_amount"], bill["payment_mode"], "confirmed",
        json.dumps(bill.get("raw_data")), json.dumps(sre_flags),
        bill["created_at"], bill["confirmed_at"],
    ))

    # Also write to legacy completed_bills for backward compat
    conn.execute("""
        INSERT OR IGNORE INTO completed_bills (bill_no, items, total_amount, payment_mode, source)
        VALUES (?,?,?,?,?)
    """, (
        bill["bill_id"], json.dumps(bill["items"]),
        bill["total_amount"], bill["payment_mode"], bill["source"],
    ))

    # ── SRE flags log ────────────────────────────────────────────────────
    for f in sre_flags:
        resolution = f.get("resolution", "pending")
        if float(f.get("confidence", 0)) >= 0.8 and resolution == "pending":
            resolution = "auto_accepted"
            
        conn.execute("""
            INSERT INTO sre_flags_log
                (bill_id, flag_type, severity, field, expected_val, actual_val,
                 message, confidence, resolution)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (
            bill["bill_id"], f.get("flag_type"), f.get("severity", "info"),
            f.get("field"), str(f.get("expected")), str(f.get("actual")),
            f.get("message"), f.get("confidence", 0), resolution,
        ))

    conn.commit()
    conn.close()

    return _ok({
        "bill": bill,
        "stock_updates": stock_updates,
        "message": f"Bill {bill['bill_id']} confirmed with {len(stock_updates)} stock updates",
    }, sre_flags=sre_flags)


# ═════════════════════════════════════════════════════════════════════════════
# 4. VOICE RECOGNITION & SPEECH MATCHING
# ═════════════════════════════════════════════════════════════════════════════

@app.post("/api/voice/transcribe")
async def voice_transcribe(request: Request):
    body = await request.json()
    transcript = body.get("transcript", "").strip().lower()
    if not transcript:
        return _err("Transcript is required")

    conn = get_conn()
    rows = conn.execute("""
        SELECT p.id, p.name, p.selling_price, p.emoji,
               GROUP_CONCAT(pa.alias, '|||') AS aliases
        FROM products p
        LEFT JOIN product_aliases pa ON pa.product_id = p.id
        WHERE p.is_active = 1
        GROUP BY p.id
    """).fetchall()
    conn.close()

    db_products = []
    for r in rows:
        d = dict(r)
        alias_list = [a.lower().strip() for a in (d.pop("aliases") or "").split("|||") if a.strip()]
        d["aliases"] = alias_list
        db_products.append(d)

    quantity_words = {
        'ek':1, 'do':2, 'teen':3, 'char':4, 'paanch':5, 'chhe':6, 'saat':7, 'aath':8, 'nau':9, 'das':10,
        'one':1, 'two':2, 'three':3, 'four':4, 'five':5, 'six':6, 'seven':7, 'eight':8, 'nine':9, 'ten':10,
        'half':0.5, 'dhai':2.5, 'couple':2
    }
    from helpers import normalize
    import difflib

    transcript = normalize(transcript)
    words = transcript.split()
    STOP_WORDS = {"and", "aur", "or", "bhi", "with", "ka", "ki", "ke", "ko", "de", "do", "dena", "packet", "piece", "pcs", "bhai", "waala", "chahiye"}

    candidates = []

    for p in db_products:
        p_name = p['name'].lower()
        all_variants = [p_name] + p.get("aliases", [])
        
        best_score = 0
        best_span = (0, 0)
        
        for i in range(len(words)):
            for j in range(i+1, min(len(words)+1, i+4)):
                sub = ' '.join(words[i:j])
                if sub in STOP_WORDS or sub in quantity_words:
                    continue
                if len(sub) < 3:
                    continue
                
                score = 0.0
                for v in all_variants:
                    if sub == v:
                        score = max(score, 1.0)
                    elif v.startswith(sub) or sub.startswith(v):
                        score = max(score, 0.95)
                    else:
                        v_words = [w for w in v.split() if w not in STOP_WORDS and len(w) >= 3]
                        if any(vw == sub for vw in v_words):
                            score = max(score, 0.92)
                        elif v_words:
                            sim = max([difflib.SequenceMatcher(None, sub, vw).ratio() for vw in v_words] or [0])
                            if sim >= 0.70:
                                score = max(score, sim)
                
                if score > best_score and score >= 0.65:
                    best_score = score
                    best_span = (i, j)
                    
        if best_score >= 0.65:
            candidates.append({
                'product': p,
                'score': best_score,
                'span': best_span
            })
            
    # Sort candidates by match quality (highest score first, then longer span)
    candidates.sort(key=lambda x: (x['score'], x['span'][1] - x['span'][0]), reverse=True)
    
    claimed_words = set()
    structured_items = []
    total_amount = 0.0
    
    for c in candidates:
        span_words = set(range(c['span'][0], c['span'][1]))
        if not (span_words & claimed_words):
            start_idx, end_idx = c['span']
            qty = 1
            qty_word_idx = None
            
            if start_idx > 0:
                prev_w = words[start_idx - 1]
                if prev_w in quantity_words:
                    qty = quantity_words[prev_w]
                    qty_word_idx = start_idx - 1
                elif prev_w.isdigit():
                    qty = int(prev_w)
                    qty_word_idx = start_idx - 1
            elif end_idx < len(words):
                next_w = words[end_idx]
                if next_w in quantity_words:
                    qty = quantity_words[next_w]
                    qty_word_idx = end_idx
                elif next_w.isdigit():
                    qty = int(next_w)
                    qty_word_idx = end_idx
                    
            claimed_words.update(span_words)
            if qty_word_idx is not None:
                claimed_words.add(qty_word_idx)
                
            p = c['product']
            price = float(p.get('selling_price', 0))
            amt = price * qty
            
            structured_items.append({
                "id": p['id'],
                "name": p['name'],
                "matched_name": p['name'],
                "product_id": p['id'],
                "qty": qty,
                "unit": "pcs",
                "price": price,
                "amount": amt,
                "confidence": c['score'],
                "emoji": p.get('emoji', '📦'),
                "match_method": "voice_single_best"
            })
            total_amount += amt

    return JSONResponse({
        'success': True,
        'data': {
            'items': structured_items,
            'total_amount': total_amount
        }
    })


@app.post("/api/voice/inventory")
async def voice_inventory_parse(request: Request):
    """
    Parse add/deduct/remove inventory commands (preview only; confirm applies via /api/inventory/update).
    Matches Flask app.py /api/voice/inventory behaviour.
    """
    body = await request.json()
    raw = (body.get("transcript") or "").strip()
    if not raw:
        return _err("Transcript is required")

    from helpers import fuzzy_match, normalize

    transcript = normalize(raw)

    ADD_KEYWORDS = [
        "add", "stock in", "restock", "received", "purchase",
        "jodo", "daalo", "laya", "aaya",
    ]
    DEDUCT_KEYWORDS = [
        "deduct", "remove", "sell", "sold", "reduce", "minus",
        "hatao", "kam karo", "nikalo", "gaya", "bika",
    ]

    action = None
    for kw in ADD_KEYWORDS:
        if kw in transcript:
            action = "add"
            break
    if action is None:
        for kw in DEDUCT_KEYWORDS:
            if kw in transcript:
                action = "deduct"
                break

    if action is None:
        return _err('No action detected. Say "add" or "deduct/remove".', 422)

    quantity_words = {
        "ek": 1, "do": 2, "teen": 3, "char": 4, "paanch": 5,
        "chhe": 6, "saat": 7, "aath": 8, "nau": 9, "das": 10,
        "bees": 20, "tees": 30, "chalis": 40, "pachas": 50,
        "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
        "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
        "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20,
        "thirty": 30, "forty": 40, "fifty": 50, "hundred": 100,
        "half": 0.5, "couple": 2, "dozen": 12,
    }

    words = transcript.split()
    parsed_qty = 1
    for i, w in enumerate(words):
        if w.isdigit():
            parsed_qty = int(w)
            break
        if w in quantity_words:
            parsed_qty = quantity_words[w]
            break

    conn = get_conn()
    products = _products_with_aliases(conn)

    best_match = None
    best_conf = 0.0
    for p in products:
        matched, conf = fuzzy_match(transcript, [p], min_confidence=0.45)
        if matched and conf > best_conf:
            best_match = matched
            best_conf = conf

    if not best_match:
        conn.close()
        return _err("No matching product found in inventory.", 404)

    row = conn.execute(
        "SELECT current_qty FROM products WHERE id=?", (best_match["id"],)
    ).fetchone()
    current_qty = row["current_qty"] if row else 0
    conn.close()

    new_qty = (current_qty + parsed_qty) if action == "add" else max(0, current_qty - parsed_qty)

    return _ok({
        "items": [{
            "action": action,
            "product_id": best_match["id"],
            "product_name": best_match["name"],
            "qty": parsed_qty,
            "current_qty": current_qty,
            "new_qty": new_qty,
            "confidence": round(best_conf, 3),
        }]
    })


# ═════════════════════════════════════════════════════════════════════════════
# 5. VOICE CONFIRM  (same SRE-gated flow as OCR confirm)
# ═════════════════════════════════════════════════════════════════════════════

@app.post("/api/voice/confirm")
async def voice_confirm(request: Request):
    # Re-use the same confirm logic as OCR
    return await ocr_confirm(request)


# ═════════════════════════════════════════════════════════════════════════════
# 6. CALCULATOR ENTRY
# ═════════════════════════════════════════════════════════════════════════════

from price_resolver import PriceResolver
from pattern_engine import PatternRecognitionEngine

pr_resolver = PriceResolver()
pattern_engine = PatternRecognitionEngine()

@app.post("/api/calculator/resolve-price")
async def resolve_price(request: Request):
    body = await request.json()
    price = int(body.get("price", 0))
    hour = body.get("hour")
    day = body.get("day")
    cart_item_ids = body.get("cart_item_ids", [])
    asr_transcript = body.get("asr_transcript", "")

    # Multi-dimensional pattern prediction
    pred = pattern_engine.predict_item(
        price=price,
        hour=hour,
        day=day,
        active_cart_item_ids=cart_item_ids,
        asr_transcript=asr_transcript
    )

    if pred.get("status") == "not_found":
        return _ok({"status": "not_found", "items": []})

    best = pred.get("best_match")
    candidates = pred.get("candidates", [])

    if len(candidates) == 1:
        return _ok({
            "status": "unique",
            "item": candidates[0],
            "confidence": 1.0,
            "reason": candidates[0].get("reason", "Unique price match")
        })

    if pred.get("status") == "auto" and best:
        return _ok({
            "status": "auto",
            "item": best,
            "confidence": best.get("confidence", 0.8),
            "reason": best.get("reason", "Pattern prediction"),
            "alternatives": candidates
        })

    return _ok({
        "status": "ambiguous",
        "items": candidates,
        "best_guess": best,
        "confidence": best.get("confidence", 0) if best else 0
    })

@app.post("/api/calculator/predict-item")
async def predict_item_api(request: Request):
    """Real-time parallel prediction endpoint for live speech + keypad inputs."""
    body = await request.json()
    price = body.get("price", 0)
    hour = body.get("hour")
    day = body.get("day")
    cart_item_ids = body.get("cart_item_ids", [])
    asr_transcript = body.get("asr_transcript", "")

    pred = pattern_engine.predict_item(
        price=price,
        hour=hour,
        day=day,
        active_cart_item_ids=cart_item_ids,
        asr_transcript=asr_transcript
    )
    return _ok(pred)

@app.post("/api/calculator/select-item")
async def select_item(request: Request):
    body = await request.json()
    pr_resolver.record_selection(
        body["price"], body["item_id"], body["item_name"],
        body["hour"], body["day"]
    )
    pattern_engine.record_transaction_patterns([{
        "item_id": body["item_id"],
        "item_name": body["item_name"],
        "price": body["price"]
    }], hour=body.get("hour"), day=body.get("day"))
    return _ok({"status": "recorded"})

@app.post("/api/calculator/submit-session")
async def submit_session(request: Request):
    body = await request.json()
    entries = body.get("entries", [])
    
    # 1. Always write session to DB first (so we have a session_id for retroactive assignment)
    conn = get_conn()
    now_dt = datetime.now()
    
    spoken_context = body.get("spoken_context", {})
    spoken_transcript = spoken_context.get("raw_transcript", "")

    conn.execute("""
        INSERT INTO calculator_sessions (entries_json, expression, result, session_date, session_time, status, spoken_transcript)
        VALUES (?, ?, ?, ?, ?, 'confirmed', ?)
    """, (json.dumps(entries), body.get("expression"), body.get("result"), now_dt.strftime("%Y-%m-%d"), now_dt.strftime("%H:%M:%S"), spoken_transcript))
    session_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    
    inventory_updates = []
    for e in entries:
        pid = e.get("item_id")
        qty = e.get("qty", 1)
        item_name = e.get("item_name", "").strip() or "Unknown Item"
        price = e.get("price", 0)
        
        # If no product_id, auto-create the product in inventory
        if not pid and item_name and item_name != "Unknown Item":
            slug = ''.join(c for c in item_name.upper() if c.isalnum())[:6]
            sku = f"KS-{slug}-{uuid.uuid4().hex[:3].upper()}"
            
            # Ensure "Other" category exists
            conn.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", ("Other",))
            cat_row = conn.execute("SELECT id FROM categories WHERE name=?", ("Other",)).fetchone()
            cat_id = cat_row["id"] if cat_row else None
            
            conn.execute("""
                INSERT INTO products (name, category_id, sku, purchase_price, selling_price, mrp,
                                      current_qty, min_stock, emoji)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, (item_name, cat_id, sku, price, price, price, 0, 5, "📦"))
            pid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            print(f"Auto-created product '{item_name}' (id={pid}) at ₹{price} from calculator")
        
        if pid:
            conn.execute("UPDATE products SET current_qty = current_qty - ?, updated_at = datetime('now') WHERE id=?", (qty, pid))
            
            alias_used = e.get("alias_used", False)
            conn.execute("""
                INSERT INTO inventory_deduction_log (session_id, item_id, item_name, qty_deducted, price_at_time, alias_used)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (session_id, pid, item_name, qty, price, alias_used))
            
            inventory_updates.append({"item_id": pid, "item_name": item_name, "qty_deducted": qty, "auto_created": e.get("item_id") is None})

            conn.execute("""
                INSERT INTO stock_logs (transaction_id, product_id, product_name, qty_change, action_type, source, reason)
                VALUES (?, ?, ?, ?, 'sale', 'calculator', ?)
            """, (f"CALC-{session_id}-{pid}", pid, item_name, -qty, f"Session {session_id}"))

    # Store unresolved operand indices passed directly from frontend
    unresolved_operands = body.get("unresolved_operands", [])
    conn.execute("UPDATE calculator_sessions SET unresolved_operands=? WHERE id=?",
                 (json.dumps(unresolved_operands), session_id))

    conn.commit()
    conn.close()

    # Automatically learn transaction patterns into the Pattern Recognition Engine
    try:
        pattern_engine.record_transaction_patterns(entries)
    except Exception as ex:
        print(f"Pattern learning error: {ex}")
    
    # 2. Run SRE checks on session (after DB write so session_id is available)
    bill_for_sre = {
        "source": "calculator",
        "items": [{"product_id": e.get("item_id"), "name": e.get("item_name", "Unknown"), "price": e.get("price", 0), "qty": e.get("qty", 1)} for e in entries],
        "total_amount": body.get("result", 0),
        "spoken_context": body.get("spoken_context")
    }
    
    flags = await _run_sre_check(bill_for_sre)

    # Filter out flags handled by the frontend inline prompts:
    # - HIGH_TOTAL: permanently disabled
    # - unknown_product: the calculator's inline "New item detected" prompt handles naming
    flags = [f for f in flags if f.get("flag_type") not in ("HIGH_TOTAL", "unknown_product")]
    
    blocking_flags = [f for f in flags if f.get("blocking")]
    low_conf_flags = [f for f in flags if float(f.get("confidence", 1.0)) < 0.50]
    
    if blocking_flags or low_conf_flags:
        return _ok({"status": "flags_detected", "session_id": session_id, "sre_flags": flags})
    
    return _ok({"status": "confirmed", "session_id": session_id, "inventory_updates": inventory_updates})

@app.get("/api/calculator/history")
async def get_calc_history(limit: int = 20, offset: int = 0):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM calculator_sessions ORDER BY created_at DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
    conn.close()
    
    results = []
    for r in rows:
        d = dict(r)
        d["entries"] = json.loads(d["entries_json"])
        d["unresolved_operands"] = json.loads(d.get("unresolved_operands") or "[]")
        results.append(d)
    return _ok(results)


@app.patch("/api/calculator/session/{session_id}/assign-item")
async def assign_item_to_session(session_id: int, request: Request):
    """Retroactively assign an item to an unresolved operand in a past session."""
    body = await request.json()
    operand_index = body.get("operand_index")
    operand       = body.get("operand")
    item_id       = body.get("item_id")
    item_name     = body.get("item_name", "")
    qty           = int(body.get("qty", 1))
    allow_out_of_stock = bool(body.get("allow_out_of_stock"))

    if operand_index is None or not item_id:
        return _err("operand_index and item_id are required")
        
    operand_index = int(operand_index)

    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM calculator_sessions WHERE id=?", (session_id,)).fetchone()
        if not row:
            conn.close()
            return _err("Session not found", 404)

        entries = json.loads(row["entries_json"])

        # Update by operand_index
        if operand_index < 0 or operand_index >= len(entries):
            conn.close()
            return _err("Invalid operand index", 400)
            
        updated_entry = entries[operand_index]
        
        if updated_entry.get("item_id"):
            conn.close()
            return _err("Operand at this index is already assigned", 400)
            
        updated_entry["item_id"] = item_id
        updated_entry["item_name"] = item_name
        updated_entry["qty"] = qty
        
        # Determine the price from the entry
        assigned_price = int(updated_entry.get("price", operand or 0))

        # Stock check
        stock_row = conn.execute(
            "SELECT name, current_qty FROM products WHERE id=? AND is_active=1", (item_id,)
        ).fetchone()
        if not stock_row:
            conn.close()
            return _err("Item not found", 404)
        if stock_row["current_qty"] < qty and not allow_out_of_stock:
            conn.close()
            return _err(f"{stock_row['name']} is out of stock \u2014 cannot deduct.", 409)

        # Remove the operand_index from unresolved_operands list
        unresolved = json.loads(row["unresolved_operands"] if row["unresolved_operands"] else "[]")
        try:
            unresolved.remove(operand_index)
        except ValueError:
            pass

        old_qty = stock_row["current_qty"]
        new_qty = max(0, old_qty - qty)

        # All writes in one transaction
        conn.execute("UPDATE products SET current_qty=?, updated_at=datetime('now') WHERE id=?",
                     (new_qty, item_id))
        conn.execute("UPDATE calculator_sessions SET entries_json=?, unresolved_operands=? WHERE id=?",
                     (json.dumps(entries), json.dumps(unresolved), session_id))
        conn.execute("""
            INSERT INTO inventory_deduction_log
                (session_id, item_id, item_name, qty_deducted, price_at_time, alias_used)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (session_id, item_id, item_name, qty, int(operand), False))
        conn.execute("""
            INSERT INTO stock_logs
                (transaction_id, product_id, product_name, qty_change, action_type, source, reason)
            VALUES (?, ?, ?, ?, 'sale', 'calculator_retro', ?)
        """, (f"RETRO-{session_id}-{item_id}", item_id, item_name, -qty,
               f"Retroactive assign session {session_id}"))

        conn.commit()
        conn.close()

        return _ok({
            "status": "ok",
            "item_id": item_id,
            "item_name": item_name,
            "new_quantity": new_qty,
            "unresolved_operands": unresolved,
        })
    except Exception as ex:
        try:
            conn.close()
        except Exception:
            pass
        return _err(str(ex))

@app.get("/api/calculator/pattern-confidence/{price}")
async def get_pattern_conf(price: int):
    stats = pr_resolver.get_pattern_stats(price)
    return _ok(stats)

@app.get("/api/calculator/learning-stats")
async def get_learning_stats():
    conn = get_conn()
    total_prices = conn.execute("SELECT COUNT(DISTINCT selling_price) FROM products WHERE is_active=1").fetchone()[0]
    learned_prices = conn.execute("SELECT COUNT(DISTINCT price) FROM price_item_patterns").fetchone()[0]
    conn.close()
    return _ok({"total": total_prices, "learned": learned_prices})


# ═════════════════════════════════════════════════════════════════════════════
# 7. MANUAL BILL CONFIRM  (for calculator and direct manual entries)
# ═════════════════════════════════════════════════════════════════════════════

@app.post("/api/bills/confirm")
async def bills_confirm(request: Request):
    return await ocr_confirm(request)


# ═════════════════════════════════════════════════════════════════════════════
# 8. SRE CHECK  (universal pre-write validation)
# ═════════════════════════════════════════════════════════════════════════════

async def _run_sre_check(bill: dict) -> list:
    """Run SRE validation on a bill. Returns list of flags."""
    flags = []
    conn = get_conn()

    # == CALCULATOR SRE LOGIC ==
    if bill.get("source") == "calculator":
        items = bill.get("items", [])
        
        from collections import Counter
        counts = Counter([i.get("product_id") for i in items if i.get("product_id")])
        
        for idx, item in enumerate(items):
            pid = item.get("product_id")
            price = item.get("price")
            if not pid:
                flags.append({
                    "flag_type":  "unknown_product",
                    "severity":   "warning",
                    "field":      f"items[{idx}]",
                    "actual":     f"₹{price}",
                    "message":    "New item detected what is this then",
                    "confidence": 0,
                    "blocking": False
                })
                continue
            
            qty = item.get("qty", 1)
            
            row = conn.execute("SELECT current_qty FROM products WHERE id=?", (pid,)).fetchone()
            if row and row["current_qty"] < qty:
                flags.append({
                    "flag_type": "OUT_OF_STOCK",
                    "severity": "critical",
                    "field": f"items[{idx}].qty",
                    "message": f"{item['name']} only has {row['current_qty']} left in stock but you sold {qty}",
                    "confidence": 1.0,
                    "blocking": True
                })
                
            avg_row = conn.execute("SELECT AVG(qty_deducted) as avg_qty FROM inventory_deduction_log WHERE item_id=? AND deducted_at >= datetime('now', '-30 days')", (pid,)).fetchone()
            avg = avg_row["avg_qty"] if avg_row and avg_row["avg_qty"] else 1
            if qty > 3:
                # Add HIGH_QTY_DEDUCTION for composite amounts
                flags.append({
                    "flag_type": "HIGH_QTY_DEDUCTION",
                    "severity": "warning",
                    "field": f"items[{idx}].qty",
                    "message": f"Deducting {qty}× {item['name']} — confirm this is correct",
                    "confidence": 0.70,
                    "blocking": False,
                    "options": [
                        {"qty": qty, "name": f"Yes, {qty}× {item['name']}"},
                        {"qty": 1, "name": "Actually 1×"}
                    ]
                })
            elif qty > (avg * 3) and qty > 2:
                flags.append({
                    "flag_type": "HIGH_QUANTITY",
                    "severity": "warning",
                    "field": f"items[{idx}].qty",
                    "message": f"You usually sell {avg:.1f} {item['name']} per transaction. You entered {qty} — confirm this is correct.",
                    "confidence": 0.60,
                    "blocking": False
                })

        for pid, count in counts.items():
            if count > 2:
                name = next(i["name"] for i in items if i["product_id"] == pid)
                flags.append({
                    "flag_type": "REPEATED_ITEM",
                    "severity": "warning",
                    "field": f"items[{pid}]",
                    "message": f"{name} sold {count} times in one transaction — confirm this",
                    "confidence": 0.85,
                    "blocking": False
                })

        # high total check removed per user request
        spoken = bill.get("spoken_context")
        if spoken and spoken.get("raw_transcript"):
            mentions = spoken.get("mentions", [])
            for idx, item in enumerate(items):
                pid = item.get("product_id")
                price = item.get("price")
                competing = [m for m in mentions if m.get("price") == price and m.get("item_id") != pid]
                if competing:
                    comp_best = max(competing, key=lambda x: x.get("match_score", 0))
                    if comp_best.get("match_score", 0) >= 0.7:
                        flags.append({
                            "flag_type": "SPEECH_MISMATCH",
                            "severity": "warning",
                            "field": f"items[{idx}]",
                            "message": f"You entered ₹{price} which resolved to '{item['name']}', but you seem to have said '{comp_best['item_name']}'. Which is correct?",
                            "confidence": 0.65,
                            "blocking": False,
                            "options": [
                                {"id": pid, "name": item["name"]},
                                {"id": comp_best["item_id"], "name": comp_best["item_name"]}
                            ]
                        })

        conn.close()
        return flags

    # == STANDARD OCR/VOICE SRE LOGIC ==
    for idx, item in enumerate(bill.get("items", [])):
        pid = item.get("product_id")
        if not pid:
            flags.append({
                "flag_type":  "unknown_product",
                "severity":   "warning",
                "field":      f"items[{idx}].name",
                "expected":   "Known product in database",
                "actual":     item.get("name", "?"),
                "message":    f"'{item.get('name')}' not found in product database",
                "confidence": item.get("confidence", 0),
            })
            continue

        row = conn.execute(
            "SELECT name, selling_price, current_qty, min_stock FROM products WHERE id=?",
            (pid,)
        ).fetchone()
        if not row:
            continue

        db_price = row["selling_price"]
        item_price = item.get("price", 0)
        if db_price > 0 and item_price > 0 and abs(db_price - item_price) > db_price * 0.2:
            flags.append({
                "flag_type":  "price_mismatch",
                "severity":   "warning",
                "field":      f"items[{idx}].price",
                "expected":   db_price,
                "actual":     item_price,
                "message":    f"Price for '{row['name']}' differs by >20% from DB (₹{db_price} vs ₹{item_price})",
                "confidence": 0.8,
            })

        qty = item.get("qty", 0)
        action = "restock" if bill.get("source") == "ocr" and bill.get("vendor_name") else "sale"

        if action == "sale" and row["current_qty"] < qty:
            flags.append({
                "flag_type":  "stock_warning",
                "severity":   "critical",
                "field":      f"items[{idx}].qty",
                "expected":   f"Available: {row['current_qty']}",
                "actual":     qty,
                "message":    f"Not enough stock for '{row['name']}': have {row['current_qty']}, need {qty}",
                "confidence": 1.0,
            })

        if action == "sale" and (row["current_qty"] - qty) < row["min_stock"]:
            flags.append({
                "flag_type":  "stock_warning",
                "severity":   "info",
                "field":      f"items[{idx}].qty",
                "expected":   f"Min stock: {row['min_stock']}",
                "actual":     row["current_qty"] - qty,
                "message":    f"'{row['name']}' will drop below minimum stock after this sale",
                "confidence": 0.9,
            })

    conn.close()
    return flags


# Public endpoint: run SRE without committing anything.
@app.post("/api/sre/check")
async def sre_check(request: Request):
    body = await request.json()

    # Accept minimal payloads from the frontend (e.g. OCRPage smart-checks).
    bill = {
        "source": body.get("source") or "ocr",
        "vendor_name": body.get("vendor_name"),
        "payment_mode": body.get("payment_mode") or "cash",
        "total_amount": body.get("total_amount") or 0,
        "items": body.get("items") or [],
        "spoken_context": body.get("spoken_context"),
    }

    try:
        flags = await _run_sre_check(bill)
        # Put flags both in `data` and top-level `sre_flags` for compatibility.
        return _ok({"sre_flags": flags}, sre_flags=flags)
    except Exception as exc:
        return _err(f"SRE check failed: {exc}", 500)


# ═════════════════════════════════════════════════════════════════════════════
# 9. SRE SMART SESSION  (Q&A reconciliation flow — passthrough)
# ═════════════════════════════════════════════════════════════════════════════

@app.post("/api/sre/smart/start")
async def sre_smart_start(request: Request):
    body = await request.json()
    try:
        result = await _forward_post(f"{SRE_URL}/smart/start", body)
        return _ok(result)
    except HTTPException:
        # Fallback: use local SRE engine if service is down
        from sre_engine import create_session
        session = create_session(float(body.get("mismatch_amount", 0)),
                                 body.get("products", []))
        return _ok(session)


@app.post("/api/sre/smart/answer")
async def sre_smart_answer(request: Request):
    body = await request.json()
    try:
        result = await _forward_post(f"{SRE_URL}/smart/answer", body)
        return _ok(result)
    except HTTPException:
        from sre_engine import answer_question
        result = answer_question(body.get("session_id"), body.get("answer"))
        return _ok(result)


@app.post("/api/sre/smart/learn")
async def sre_smart_learn(request: Request):
    body = await request.json()
    try:
        result = await _forward_post(f"{SRE_URL}/smart/learn", body)
        return _ok(result)
    except HTTPException:
        from sre_engine import confirm_and_learn
        result = confirm_and_learn(body.get("session_id"), body.get("confirmed_items", []))
        return _ok(result)


@app.get("/api/sre/conflicts")
async def sre_conflicts():
    conn = get_conn()
    flags = conn.execute("""
        SELECT * FROM sre_flags_log WHERE resolution='pending'
        ORDER BY created_at DESC LIMIT 50
    """).fetchall()
    conn.close()
    return _ok([dict(f) for f in flags])


# ═════════════════════════════════════════════════════════════════════════════
# 10. INVENTORY ENDPOINTS
# ═════════════════════════════════════════════════════════════════════════════

@app.get("/inventory/search")
@app.get("/api/inventory/search")
async def inventory_search(q: str = ""):
    typed = (q or "").strip()
    if len(typed) < 2:
        return _ok({"items": []})

    conn = get_conn()
    rows = conn.execute("""
        SELECT id, name, selling_price AS price, current_qty AS quantity, emoji
        FROM products
        WHERE is_active = 1
          AND (
            LOWER(name) LIKE '%' || LOWER(?) || '%'
            OR LOWER(?) LIKE '%' || LOWER(name) || '%'
            OR barcode = ?
          )
        LIMIT 4
    """, (typed, typed, typed)).fetchall()
    conn.close()

    return _ok({"items": [dict(r) for r in rows]})


@app.get("/api/products/by-barcode")
async def product_by_barcode(code: str = ""):
    code = (code or "").strip()
    if not code:
        return _err("code is required", 400)
    conn = get_conn()
    row = conn.execute(
        """
        SELECT p.*, c.name AS category
        FROM products p
        LEFT JOIN categories c ON p.category_id = c.id
        WHERE p.is_active=1 AND p.barcode=?
        LIMIT 1
        """,
        (code,),
    ).fetchone()
    conn.close()
    if not row:
        return _err("Not found", 404)
    return _ok(dict(row))


@app.get("/api/inventory")
async def inventory_snapshot():
    conn = get_conn()
    rows = conn.execute("""
        SELECT p.id, p.name, p.sku, p.current_qty, p.min_stock,
               p.selling_price, p.purchase_price, p.mrp, p.unit_type,
               p.brand, p.barcode, p.expiry_date, p.supplier_id,
               p.variant_group_id, p.variant_label,
               p.gst_rate, p.discount_pct,
               p.emoji, p.notes,
               c.name AS category
        FROM products p
        LEFT JOIN categories c ON p.category_id = c.id
        WHERE p.is_active = 1
        ORDER BY p.name
    """).fetchall()
    conn.close()

    products = []
    for r in rows:
        d = dict(r)
        d["stock_status"] = (
            "out" if d["current_qty"] == 0
            else "low" if d["current_qty"] <= d["min_stock"]
            else "ok"
        )
        products.append(d)

    return _ok(products)


@app.get("/api/inventory/logs")
async def inventory_logs():
    conn = get_conn()
    rows = conn.execute("""
        SELECT * FROM stock_logs ORDER BY created_at DESC LIMIT 100
    """).fetchall()
    conn.close()
    return _ok([dict(r) for r in rows])


@app.get("/api/inventory/low-stock")
async def low_stock():
    conn = get_conn()
    rows = conn.execute("""
        SELECT p.id, p.name, p.current_qty, p.min_stock, p.emoji, c.name as category
        FROM products p
        LEFT JOIN categories c ON p.category_id = c.id
        WHERE p.is_active = 1 AND p.current_qty <= p.min_stock
        ORDER BY p.current_qty ASC
    """).fetchall()
    conn.close()
    return _ok([dict(r) for r in rows])


@app.get("/api/inventory/expiring")
async def expiring(days: int = 30):
    days = max(1, min(int(days or 30), 365))
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT
          p.id, p.name, p.emoji, p.expiry_date, p.current_qty, p.min_stock,
          COALESCE(c.name, 'Uncategorized') AS category
        FROM products p
        LEFT JOIN categories c ON p.category_id = c.id
        WHERE p.is_active=1
          AND p.expiry_date IS NOT NULL
          AND trim(p.expiry_date) <> ''
          AND date(p.expiry_date) <= date('now', ?)
        ORDER BY date(p.expiry_date) ASC
        LIMIT 50
        """,
        (f"+{days} days",),
    ).fetchall()
    conn.close()
    return _ok([dict(r) for r in rows])


@app.get("/api/inventory/alerts")
async def inventory_alerts(days: int = 30):
    days = max(1, min(int(days or 30), 365))
    conn = get_conn()
    low = conn.execute(
        """
        SELECT p.id, p.name, p.emoji, p.current_qty, p.min_stock, COALESCE(c.name,'Uncategorized') AS category
        FROM products p
        LEFT JOIN categories c ON p.category_id = c.id
        WHERE p.is_active=1 AND p.current_qty <= p.min_stock
        ORDER BY p.current_qty ASC, p.name ASC
        LIMIT 50
        """
    ).fetchall()
    exp = conn.execute(
        """
        SELECT p.id, p.name, p.emoji, p.expiry_date, p.current_qty, p.min_stock, COALESCE(c.name,'Uncategorized') AS category
        FROM products p
        LEFT JOIN categories c ON p.category_id = c.id
        WHERE p.is_active=1
          AND p.expiry_date IS NOT NULL
          AND trim(p.expiry_date) <> ''
          AND date(p.expiry_date) <= date('now', ?)
        ORDER BY date(p.expiry_date) ASC
        LIMIT 50
        """,
        (f"+{days} days",),
    ).fetchall()
    conn.close()
    return _ok({"low_stock": [dict(r) for r in low], "expiring_soon": [dict(r) for r in exp], "window_days": days})


@app.post("/api/inventory/update")
async def inventory_update(request: Request):
    body = await request.json()
    pid = body.get("product_id")
    qty_change = body.get("qty_change", 0)
    action = body.get("action", "adjust")
    reason = body.get("reason", "Manual adjustment")

    if not pid:
        return _err("product_id is required")

    conn = get_conn()
    row = conn.execute("SELECT id, name, current_qty FROM products WHERE id=?", (pid,)).fetchone()
    if not row:
        conn.close()
        return _err("Product not found", 404)

    old_qty = row["current_qty"]
    new_qty = max(0, old_qty + qty_change)

    conn.execute("UPDATE products SET current_qty=?, updated_at=datetime('now') WHERE id=?",
                 (new_qty, pid))

    txn_id = f"INV-{_bill_id()}"
    conn.execute("""
        INSERT INTO stock_logs
            (transaction_id, product_id, product_name, qty_change,
             action_type, source, reason, old_qty, new_qty)
        VALUES (?,?,?,?,?,?,?,?,?)
    """, (txn_id, pid, row["name"], qty_change, action, "manual", reason, old_qty, new_qty))

    conn.commit()
    conn.close()

    return _ok({
        "product_id": pid,
        "name": row["name"],
        "old_qty": old_qty,
        "new_qty": new_qty,
        "qty_change": qty_change,
    })


@app.post("/api/inventory/add-price-alias")
async def add_price_alias(request: Request):
    body = await request.json()
    item_id = body.get("item_id")
    item_name = body.get("item_name")
    alias_price = body.get("alias_price")
    
    if not item_id or not item_name or alias_price is None:
        return _err("item_id, item_name, and alias_price are required")
        
    conn = get_conn()
    row = conn.execute("SELECT selling_price FROM products WHERE id=? AND is_active=1", (item_id,)).fetchone()
    if not row:
        conn.close()
        return _err("Item not found", 404)
        
    primary_price = row["selling_price"]
    
    try:
        conn.execute("""
            INSERT OR IGNORE INTO price_aliases (item_id, item_name, alias_price)
            VALUES (?, ?, ?)
        """, (item_id, item_name, int(alias_price)))
        conn.commit()
    except Exception as e:
        conn.close()
        return _err(f"Failed to add price alias: {e}")
        
    conn.close()
    
    return _ok({
        "status": "ok",
        "item_id": item_id,
        "item_name": item_name,
        "alias_price": int(alias_price),
        "primary_price": primary_price
    })

# ═════════════════════════════════════════════════════════════════════════════
# 11. DASHBOARD / ANALYTICS
# ═════════════════════════════════════════════════════════════════════════════

@app.get("/api/dashboard")
async def dashboard():
    conn = get_conn()

    # Today's stats
    today = datetime.now().strftime("%Y-%m-%d")
    bills = conn.execute("""
        SELECT * FROM confirmed_bills
        WHERE date(confirmed_at) = ? AND confirmation_status='confirmed'
    """, (today,)).fetchall()

    total_revenue = sum(b["total_amount"] for b in bills)
    bill_count = len(bills)

    cash_total = sum(b["total_amount"] for b in bills if b["payment_mode"] == "cash")
    upi_total = sum(b["total_amount"] for b in bills if b["payment_mode"] == "upi")

    # Low stock count
    low = conn.execute("""
        SELECT COUNT(*) as cnt FROM products
        WHERE is_active=1 AND current_qty <= min_stock
    """).fetchone()["cnt"]

    # Pending SRE flags
    pending_flags = conn.execute("""
        SELECT COUNT(*) as cnt FROM sre_flags_log WHERE resolution='pending'
    """).fetchone()["cnt"]

    # Recent bills
    recent = conn.execute("""
        SELECT bill_id, source, total_amount, payment_mode, confirmed_at
        FROM confirmed_bills
        WHERE confirmation_status='confirmed'
        ORDER BY confirmed_at DESC LIMIT 10
    """).fetchall()

    conn.close()

    return _ok({
        "date":            today,
        "total_revenue":   total_revenue,
        "bill_count":      bill_count,
        "cash_total":      cash_total,
        "upi_total":       upi_total,
        "low_stock_count": low,
        "pending_sre_flags": pending_flags,
        "recent_bills":    [dict(r) for r in recent],
    })


@app.get("/api/dashboard/shopkeeper")
async def shopkeeper_dashboard(days: int = 30, limit: int = 7):
    """
    Shopkeeper analytics:
    - revenue/cost/profit (from stock_logs + current product prices)
    - most selling items
    - profit margin per item

    Notes:
    - Uses stock_logs action_type to distinguish 'sale' vs 'restock'
    - Uses products.selling_price and products.purchase_price as proxies for price-at-time
    """
    days = max(1, min(int(days or 30), 365))
    limit = max(3, min(int(limit or 7), 25))

    conn = get_conn()
    try:
        # Aggregate by product for sales
        rows = conn.execute(
            """
            SELECT
              p.id AS product_id,
              p.name AS name,
              p.emoji AS emoji,
              COALESCE(p.selling_price, 0) AS selling_price,
              COALESCE(p.purchase_price, 0) AS purchase_price,
              SUM(CASE WHEN sl.action_type='sale' THEN -sl.qty_change ELSE 0 END) AS sold_qty
            FROM stock_logs sl
            JOIN products p ON p.id = sl.product_id
            WHERE sl.created_at >= datetime('now', ?)
              AND p.is_active = 1
            GROUP BY p.id
            HAVING sold_qty > 0
            ORDER BY sold_qty DESC
            """,
            (f"-{days} days",),
        ).fetchall()

        items = []
        total_revenue = 0.0
        total_cost = 0.0

        for r in rows:
            sold_qty = float(r["sold_qty"] or 0)
            sp = float(r["selling_price"] or 0)
            pp = float(r["purchase_price"] or 0)

            revenue = sold_qty * sp
            cost = sold_qty * pp
            profit = revenue - cost
            margin_pct = ((profit / revenue) * 100) if revenue > 0 else 0.0

            total_revenue += revenue
            total_cost += cost

            items.append(
                {
                    "product_id": r["product_id"],
                    "name": r["name"],
                    "emoji": r["emoji"] or "📦",
                    "sold_qty": round(sold_qty, 3),
                    "selling_price": round(sp, 2),
                    "purchase_price": round(pp, 2),
                    "revenue": round(revenue, 2),
                    "cost": round(cost, 2),
                    "profit": round(profit, 2),
                    "profit_margin_pct": round(margin_pct, 2),
                }
            )

        total_profit = total_revenue - total_cost
        overall_margin_pct = ((total_profit / total_revenue) * 100) if total_revenue > 0 else 0.0

        top_selling = sorted(items, key=lambda x: x["sold_qty"], reverse=True)[:limit]
        top_profit = sorted(items, key=lambda x: x["profit"], reverse=True)[:limit]

        # Efficiency (simple): average profit per sold unit, and revenue per sold unit
        total_units = sum(i["sold_qty"] for i in items) if items else 0.0
        profit_per_unit = (total_profit / total_units) if total_units > 0 else 0.0
        revenue_per_unit = (total_revenue / total_units) if total_units > 0 else 0.0

        return _ok(
            {
                "window_days": days,
                "totals": {
                    "revenue": round(total_revenue, 2),
                    "cost": round(total_cost, 2),
                    "profit": round(total_profit, 2),
                    "profit_margin_pct": round(overall_margin_pct, 2),
                    "units_sold": round(total_units, 3),
                    "profit_per_unit": round(profit_per_unit, 2),
                    "revenue_per_unit": round(revenue_per_unit, 2),
                },
                "top_selling_items": top_selling,
                "top_profit_items": top_profit,
            }
        )
    finally:
        conn.close()


@app.get("/api/dashboard/shopkeeper/daily")
async def shopkeeper_daily(days: int = 30):
    """
    Day-wise profit/loss with date and computed totals.
    Uses stock_logs (sales only) + current product prices as proxies.
    """
    days = max(1, min(int(days or 30), 365))
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT
              date(sl.created_at) AS day,
              SUM(CASE WHEN sl.action_type='sale' THEN -sl.qty_change ELSE 0 END) AS sold_qty,
              SUM(
                CASE WHEN sl.action_type='sale'
                  THEN (-sl.qty_change) * COALESCE(p.selling_price, 0)
                  ELSE 0
                END
              ) AS revenue,
              SUM(
                CASE WHEN sl.action_type='sale'
                  THEN (-sl.qty_change) * COALESCE(p.purchase_price, 0)
                  ELSE 0
                END
              ) AS cost
            FROM stock_logs sl
            LEFT JOIN products p ON p.id = sl.product_id
            WHERE sl.created_at >= datetime('now', ?)
            GROUP BY date(sl.created_at)
            ORDER BY day DESC
            """,
            (f"-{days} days",),
        ).fetchall()

        days_out = []
        for r in rows:
            revenue = float(r["revenue"] or 0)
            cost = float(r["cost"] or 0)
            profit = revenue - cost
            margin_pct = (profit / revenue * 100) if revenue > 0 else 0.0
            days_out.append(
                {
                    "day": r["day"],
                    "units_sold": float(r["sold_qty"] or 0),
                    "revenue": round(revenue, 2),
                    "cost": round(cost, 2),
                    "profit": round(profit, 2),
                    "profit_margin_pct": round(margin_pct, 2),
                }
            )

        return _ok({"window_days": days, "days": days_out})
    finally:
        conn.close()


@app.get("/api/dashboard/shopkeeper/insights")
async def shopkeeper_insights(days: int = 30):
    """
    Extended shopkeeper dashboard datasets:
    - daily revenue/profit chart
    - purchase vs sales comparison (from stock_logs)
    - category-wise performance (sales)
    - supplier insights (sales + restock proxies)
    - low-stock alerts (list)
    - recent transactions (stock_logs)
    - monthly growth trends (sales revenue by month)
    """
    days = max(1, min(int(days or 30), 365))
    conn = get_conn()
    try:
        # Daily (sales only)
        daily_rows = conn.execute(
            """
            SELECT
              date(sl.created_at) AS day,
              SUM(CASE WHEN sl.action_type='sale' THEN -sl.qty_change ELSE 0 END) AS sold_qty,
              SUM(CASE WHEN sl.action_type='sale' THEN (-sl.qty_change) * COALESCE(p.selling_price,0) ELSE 0 END) AS revenue,
              SUM(CASE WHEN sl.action_type='sale' THEN (-sl.qty_change) * COALESCE(p.purchase_price,0) ELSE 0 END) AS cost
            FROM stock_logs sl
            LEFT JOIN products p ON p.id = sl.product_id
            WHERE sl.created_at >= datetime('now', ?)
            GROUP BY date(sl.created_at)
            ORDER BY day ASC
            """,
            (f"-{days} days",),
        ).fetchall()

        daily = []
        for r in daily_rows:
            revenue = float(r["revenue"] or 0)
            cost = float(r["cost"] or 0)
            profit = revenue - cost
            daily.append(
                {
                    "day": r["day"],
                    "units_sold": float(r["sold_qty"] or 0),
                    "revenue": round(revenue, 2),
                    "profit": round(profit, 2),
                }
            )

        # Purchase vs Sales (window)
        pv = conn.execute(
            """
            SELECT
              SUM(CASE WHEN sl.action_type='sale' THEN (-sl.qty_change) * COALESCE(p.selling_price,0) ELSE 0 END) AS sales_revenue,
              SUM(CASE WHEN sl.action_type='sale' THEN (-sl.qty_change) * COALESCE(p.purchase_price,0) ELSE 0 END) AS sales_cost,
              SUM(CASE WHEN sl.action_type='restock' THEN (sl.qty_change) * COALESCE(p.purchase_price,0) ELSE 0 END) AS purchase_cost,
              SUM(CASE WHEN sl.action_type='restock' THEN (sl.qty_change) ELSE 0 END) AS restock_units,
              SUM(CASE WHEN sl.action_type='sale' THEN (-sl.qty_change) ELSE 0 END) AS sold_units
            FROM stock_logs sl
            LEFT JOIN products p ON p.id = sl.product_id
            WHERE sl.created_at >= datetime('now', ?)
            """,
            (f"-{days} days",),
        ).fetchone()
        sales_revenue = float(pv["sales_revenue"] or 0)
        sales_cost = float(pv["sales_cost"] or 0)
        purchase_cost = float(pv["purchase_cost"] or 0)

        purchase_vs_sales = {
            "window_days": days,
            "sales_revenue": round(sales_revenue, 2),
            "sales_cost": round(sales_cost, 2),
            "sales_profit": round(sales_revenue - sales_cost, 2),
            "purchase_cost": round(purchase_cost, 2),
            "sold_units": float(pv["sold_units"] or 0),
            "restock_units": float(pv["restock_units"] or 0),
        }

        # Category-wise performance (sales)
        cat_rows = conn.execute(
            """
            SELECT
              COALESCE(c.name, 'Uncategorized') AS category,
              SUM(CASE WHEN sl.action_type='sale' THEN -sl.qty_change ELSE 0 END) AS sold_qty,
              SUM(CASE WHEN sl.action_type='sale' THEN (-sl.qty_change) * COALESCE(p.selling_price,0) ELSE 0 END) AS revenue,
              SUM(CASE WHEN sl.action_type='sale' THEN (-sl.qty_change) * COALESCE(p.purchase_price,0) ELSE 0 END) AS cost
            FROM stock_logs sl
            LEFT JOIN products p ON p.id = sl.product_id
            LEFT JOIN categories c ON c.id = p.category_id
            WHERE sl.created_at >= datetime('now', ?)
            GROUP BY COALESCE(c.name, 'Uncategorized')
            HAVING sold_qty > 0
            ORDER BY revenue DESC
            """,
            (f"-{days} days",),
        ).fetchall()
        categories = []
        for r in cat_rows:
            revenue = float(r["revenue"] or 0)
            cost = float(r["cost"] or 0)
            profit = revenue - cost
            categories.append(
                {
                    "category": r["category"],
                    "sold_qty": float(r["sold_qty"] or 0),
                    "revenue": round(revenue, 2),
                    "profit": round(profit, 2),
                    "margin_pct": round((profit / revenue * 100) if revenue > 0 else 0.0, 2),
                }
            )

        # Supplier insights (sales + restock proxies)
        sup_rows = conn.execute(
            """
            SELECT
              s.id AS supplier_id,
              s.name AS supplier_name,
              COUNT(DISTINCT p.id) AS products_count,
              SUM(CASE WHEN sl.action_type='sale' THEN (-sl.qty_change) * COALESCE(p.selling_price,0) ELSE 0 END) AS sales_revenue,
              SUM(CASE WHEN sl.action_type='sale' THEN (-sl.qty_change) * COALESCE(p.purchase_price,0) ELSE 0 END) AS sales_cost,
              SUM(CASE WHEN sl.action_type='restock' THEN (sl.qty_change) * COALESCE(p.purchase_price,0) ELSE 0 END) AS purchase_cost,
              SUM(CASE WHEN sl.action_type='restock' THEN (sl.qty_change) ELSE 0 END) AS restock_units
            FROM suppliers s
            LEFT JOIN products p ON p.supplier_id = s.id AND p.is_active = 1
            LEFT JOIN stock_logs sl ON sl.product_id = p.id AND sl.created_at >= datetime('now', ?)
            GROUP BY s.id
            ORDER BY sales_revenue DESC
            """,
            (f"-{days} days",),
        ).fetchall()
        suppliers = []
        for r in sup_rows:
            sales_rev = float(r["sales_revenue"] or 0)
            sales_cost_i = float(r["sales_cost"] or 0)
            profit = sales_rev - sales_cost_i
            suppliers.append(
                {
                    "supplier_id": r["supplier_id"],
                    "supplier_name": r["supplier_name"],
                    "products_count": int(r["products_count"] or 0),
                    "sales_revenue": round(sales_rev, 2),
                    "sales_profit": round(profit, 2),
                    "purchase_cost": round(float(r["purchase_cost"] or 0), 2),
                    "restock_units": float(r["restock_units"] or 0),
                }
            )

        # Low-stock alerts (list)
        low_rows = conn.execute(
            """
            SELECT
              p.id, p.name, p.emoji, p.current_qty, p.min_stock,
              COALESCE(c.name, 'Uncategorized') AS category
            FROM products p
            LEFT JOIN categories c ON c.id = p.category_id
            WHERE p.is_active=1 AND p.current_qty <= p.min_stock
            ORDER BY p.current_qty ASC, p.name ASC
            LIMIT 25
            """
        ).fetchall()
        low_stock = [dict(r) for r in low_rows]

        # Recent transactions (stock_logs)
        tx_rows = conn.execute(
            """
            SELECT
              sl.transaction_id, sl.product_id, sl.product_name, sl.qty_change,
              sl.action_type, sl.source, sl.reason, sl.created_at
            FROM stock_logs sl
            ORDER BY sl.created_at DESC
            LIMIT 25
            """
        ).fetchall()
        recent_transactions = [dict(r) for r in tx_rows]

        # Monthly growth trends (sales revenue by month)
        month_rows = conn.execute(
            """
            SELECT
              strftime('%Y-%m', sl.created_at) AS month,
              SUM(CASE WHEN sl.action_type='sale' THEN (-sl.qty_change) * COALESCE(p.selling_price,0) ELSE 0 END) AS revenue
            FROM stock_logs sl
            LEFT JOIN products p ON p.id = sl.product_id
            WHERE sl.created_at >= datetime('now', '-365 days')
            GROUP BY strftime('%Y-%m', sl.created_at)
            ORDER BY month ASC
            """
        ).fetchall()
        monthly = [{"month": r["month"], "revenue": round(float(r["revenue"] or 0), 2)} for r in month_rows]

        return _ok(
            {
                "window_days": days,
                "daily": daily,
                "purchase_vs_sales": purchase_vs_sales,
                "category_performance": categories,
                "supplier_insights": suppliers,
                "low_stock_alerts": low_stock,
                "recent_transactions": recent_transactions,
                "monthly_growth": monthly,
            }
        )
    finally:
        conn.close()


@app.get("/api/bills")
async def get_bills():
    conn = get_conn()
    rows = conn.execute("""
        SELECT * FROM confirmed_bills
        WHERE confirmation_status='confirmed'
        ORDER BY confirmed_at DESC LIMIT 50
    """).fetchall()
    conn.close()
    return _ok([dict(r) for r in rows])


# ═════════════════════════════════════════════════════════════════════════════
# 12. BACKWARD COMPAT — legacy routes that the mobile PWA uses
# ═════════════════════════════════════════════════════════════════════════════

@app.post("/api/bills")
async def legacy_save_bill(request: Request):
    """Legacy endpoint used by mobile PWA — wraps into confirm flow."""
    body = await request.json()
    items = body.get("items", [])
    bill = {
        "bill_id":              _bill_id(),
        "source":               body.get("source", "manual"),
        "vendor_name":          None,
        "invoice_no":           None,
        "invoice_date":         None,
        "items":                [{
            "name":         i.get("name", ""),
            "matched_name": i.get("name"),
            "product_id":   i.get("product_id"),
            "qty":          i.get("qty", 1),
            "unit":         "pcs",
            "price":        float(i.get("price", 0)),
            "amount":       float(i.get("price", 0)) * i.get("qty", 1),
            "confidence":   1.0,
            "match_method": "manual",
        } for i in items],
        "subtotal":             float(body.get("total_amount", 0)),
        "tax":                  0,
        "total_amount":         float(body.get("total_amount", 0)),
        "payment_mode":         body.get("payment_mode", "cash"),
        "confirmation_status":  "confirmed",
        "sre_flags":            [],
        "raw_data":             body,
        "created_at":           _now(),
        "confirmed_at":         _now(),
    }

    # Fuzzy match product IDs
    conn = get_conn()
    db_products = [dict(r) for r in conn.execute(
        "SELECT id, name, selling_price FROM products WHERE is_active=1"
    ).fetchall()]
    conn.close()

    from helpers import fuzzy_match
    for item in bill["items"]:
        if not item["product_id"]:
            match = fuzzy_match(item["name"], db_products)
            if match:
                item["product_id"] = match["id"]
                item["matched_name"] = match["name"]

    # Use the confirm flow
    class FakeRequest:
        async def json(self):
            return bill
    return await ocr_confirm(FakeRequest())


@app.post("/api/asr")
async def legacy_asr(request: Request):
    """Legacy ASR endpoint used by mobile PWA."""
    body = await request.json()
    items = body.get("items", [{"name": body.get("name"), "qty": body.get("qty", 1)}])
    bill_body = {
        "items": items,
        "total_amount": sum(float(i.get("price", 0)) * i.get("qty", 1) for i in items),
        "payment_mode": body.get("payment_mode", "cash"),
        "source": "voice",
    }
    class FakeRequest:
        async def json(self):
            return bill_body
    return await legacy_save_bill(FakeRequest())


# ═════════════════════════════════════════════════════════════════════════════
# 9. PARALLEL TRANSACTION BUFFER  — ASR + Calculator + Inventory
# ═════════════════════════════════════════════════════════════════════════════
#
# Architecture:
#   /api/txn-buffer/start        → create a new buffer (in-memory + staged_transactions row)
#   /api/txn-buffer/asr-update   → append ASR segment while shopkeeper talks
#   /api/txn-buffer/amount-update→ sync calculator operands into buffer
#   /api/txn-buffer/finalize     → run Confidence Engine, return decision
#   /api/txn-buffer/commit       → persist high/medium to permanent DB
#   /api/txn-buffer/flag         → persist low-confidence to night_reconciliation
#   /api/txn-buffer/discard      → cancel a buffer (C button pressed)
#
# The in-memory dict (_txn_buffers) is the fast path.
# staged_transactions is the durable backup (survives restarts via /finalize).
# ─────────────────────────────────────────────────────────────────────────────

from confidence_engine import ConfidenceEngine, confidence_result_to_dict

_confidence_engine = ConfidenceEngine()
_txn_buffers: dict = {}   # txn_id → { asr_segments, calc_amounts, created_at, ... }

# Max age for an in-memory buffer (seconds) before it's considered stale
_BUFFER_MAX_AGE_S = 3600   # 1 hour


def _clean_stale_buffers():
    """Evict in-memory buffers older than _BUFFER_MAX_AGE_S."""
    import time
    now = time.time()
    stale = [k for k, v in _txn_buffers.items() if now - v.get("_ts", now) > _BUFFER_MAX_AGE_S]
    for k in stale:
        del _txn_buffers[k]


@app.post("/api/txn-buffer/start")
async def txn_buffer_start(request: Request):
    """
    Called when a new calculator session begins (first key press).
    Creates an in-memory buffer and a staged_transactions row.
    """
    body = await request.json()
    txn_id = body.get("txn_id") or f"TXN-{uuid.uuid4().hex[:10].upper()}"

    import time
    _clean_stale_buffers()
    _txn_buffers[txn_id] = {
        "txn_id": txn_id,
        "asr_segments": [],
        "calc_amounts": [],
        "_ts": time.time(),
    }

    conn = get_conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO staged_transactions (txn_id, status) VALUES (?, 'pending')",
            (txn_id,)
        )
        conn.commit()
    finally:
        conn.close()

    return _ok({"txn_id": txn_id, "status": "started"})


@app.post("/api/txn-buffer/asr-update")
async def txn_buffer_asr_update(request: Request):
    """
    Called each time the passive ASR produces a final speech segment.
    Appends the segment to the buffer — no DB write (pure in-memory).
    """
    body = await request.json()
    txn_id = body.get("txn_id")
    segment = (body.get("segment") or "").strip()
    if not txn_id or not segment:
        return _ok({"status": "noop"})

    import time
    buf = _txn_buffers.get(txn_id)
    if buf is None:
        # Recreate buffer if server restarted
        _txn_buffers[txn_id] = {"txn_id": txn_id, "asr_segments": [], "calc_amounts": [], "_ts": time.time()}
        buf = _txn_buffers[txn_id]

    buf["asr_segments"].append({"text": segment, "ts": time.time()})
    buf["_ts"] = time.time()
    # Keep rolling window — drop segments older than 5 minutes
    cutoff = time.time() - 300
    buf["asr_segments"] = [s for s in buf["asr_segments"] if s["ts"] > cutoff]

    return _ok({"txn_id": txn_id, "segment_count": len(buf["asr_segments"])})


@app.post("/api/txn-buffer/amount-update")
async def txn_buffer_amount_update(request: Request):
    """
    Called each time a calculator operand is finalized.
    Syncs the current operand list into the buffer (replaces, doesn't append).
    """
    body = await request.json()
    txn_id = body.get("txn_id")
    amounts = body.get("amounts", [])   # full list every time
    if not txn_id:
        return _ok({"status": "noop"})

    import time
    buf = _txn_buffers.get(txn_id)
    if buf is None:
        _txn_buffers[txn_id] = {"txn_id": txn_id, "asr_segments": [], "calc_amounts": [], "_ts": time.time()}
        buf = _txn_buffers[txn_id]

    buf["calc_amounts"] = [{"value": float(a.get("value", a) if isinstance(a, dict) else a), "entry_id": a.get("entry_id") if isinstance(a, dict) else None} for a in amounts]
    buf["_ts"] = time.time()

    return _ok({"txn_id": txn_id, "amount_count": len(buf["calc_amounts"])})


@app.post("/api/txn-buffer/finalize")
async def txn_buffer_finalize(request: Request):
    """
    Called when shopkeeper presses =.
    Runs the Confidence Engine across all three signals.
    Returns decision (high/medium/low) + matched items + score.
    Does NOT commit to permanent DB yet.
    """
    body = await request.json()
    txn_id = body.get("txn_id")
    if not txn_id:
        return _err("txn_id required")

    import time
    buf = _txn_buffers.get(txn_id, {})

    # Merge buffer state with any frontend-provided overrides
    asr_segments = buf.get("asr_segments", [])
    calc_amounts_raw = body.get("amounts") or [a["value"] for a in buf.get("calc_amounts", [])]
    calc_amounts = [float(a) for a in calc_amounts_raw if a]

    full_transcript = " ".join(s["text"] for s in asr_segments)

    # Fetch inventory snapshot
    conn = get_conn()
    try:
        inv_rows = conn.execute("""
            SELECT p.id, p.name, p.selling_price, p.current_qty, p.emoji,
                   GROUP_CONCAT(pa.alias_price, ',') AS alias_prices
            FROM products p
            LEFT JOIN price_aliases pa ON pa.item_id = p.id
            WHERE p.is_active = 1
            GROUP BY p.id
        """).fetchall()

        # Load price patterns
        pattern_rows = conn.execute("""
            SELECT price, item_id, item_name, SUM(selection_count) AS selection_count
            FROM price_item_patterns
            GROUP BY price, item_id
            ORDER BY selection_count DESC
        """).fetchall()
    finally:
        conn.close()

    inventory = []
    for r in inv_rows:
        d = dict(r)
        aliases = [a.strip() for a in (d.pop("alias_prices", None) or "").split(",") if a.strip()]
        d["aliases"] = aliases
        inventory.append(d)

    patterns = [dict(r) for r in pattern_rows]

    # Run confidence engine
    result = _confidence_engine.score(
        calculator_amounts=calc_amounts,
        asr_transcript=full_transcript,
        inventory_snapshot=inventory,
        price_patterns=patterns,
    )
    result_dict = confidence_result_to_dict(result)

    # ── Structured Pipeline Logging ──
    logger.info(f"[CALCULATOR] amount=₹{sum(calc_amounts):.2f} operands={calc_amounts}")
    logger.info(f"[ASR] text=\"{full_transcript}\"")
    for it in result.matched_items:
        logger.info(f"[INVENTORY] item={it.item_name} price=₹{it.price} qty={it.qty} in_stock={it.in_stock}")
    logger.info(f"[VALIDATION] calculated=₹{sum(it.price * it.qty for it in result.matched_items):.2f} confidence={result.score:.2f}")
    logger.info(f"[DECISION] {result.decision.upper()}")
    if result.decision == "low":
        logger.info(f"[REASON] UNCERTAIN_OR_AMOUNT_MISMATCH -> Flagged for Night Reconciliation")

    # Persist finalized state to staged_transactions
    conn = get_conn()
    try:
        conn.execute("""
            INSERT OR REPLACE INTO staged_transactions
                (txn_id, asr_buffer, calc_amounts, matched_items, confidence_score, decision, status)
            VALUES (?, ?, ?, ?, ?, ?, 'finalized')
        """, (
            txn_id,
            json.dumps(asr_segments),
            json.dumps(calc_amounts),
            json.dumps(result_dict["matched_items"]),
            result.score,
            result.decision,
        ))
        conn.commit()
    finally:
        conn.close()

    # Update in-memory buffer with finalized result
    if txn_id in _txn_buffers:
        _txn_buffers[txn_id]["finalized_result"] = result_dict
        _txn_buffers[txn_id]["_ts"] = time.time()

    return _ok({
        "txn_id": txn_id,
        "confidence": result_dict,
        "asr_transcript": full_transcript,
        "amount_count": len(calc_amounts),
    })


@app.post("/api/txn-buffer/commit")
async def txn_buffer_commit(request: Request):
    """
    Called after finalize when decision is high or medium.
    Writes the matched items to calculator_sessions + inventory_deduction_log.
    Marks staged_transactions.status = 'committed'.
    Clears the in-memory buffer.
    Includes idempotency protection against duplicate commits.
    """
    body = await request.json()
    txn_id = body.get("txn_id")
    entries = body.get("entries", [])       # final resolved entries from frontend
    expression = body.get("expression", "")
    result_total = float(body.get("result", 0))
    spoken_context = body.get("spoken_context", {})
    confidence_score = float(body.get("confidence_score", 0))

    if not txn_id:
        return _err("txn_id required")

    conn = get_conn()
    try:
        # ── Idempotency Check: Prevent duplicate commits ──
        existing = conn.execute("SELECT status FROM staged_transactions WHERE txn_id=?", (txn_id,)).fetchone()
        if existing and existing["status"] == "committed":
            logger.info(f"[DUPLICATE_PROTECTION] txn_id={txn_id} already committed. Skipping duplicate deduction.")
            return _ok({
                "txn_id": txn_id,
                "status": "already_committed",
                "message": "Transaction already committed safely without duplicate stock deduction."
            })

        now_dt = datetime.now()
        spoken_transcript = spoken_context.get("raw_transcript", "")

        conn.execute("""
            INSERT INTO calculator_sessions
                (entries_json, expression, result, session_date, session_time, status, spoken_transcript)
            VALUES (?, ?, ?, ?, ?, 'confirmed', ?)
        """, (
            json.dumps(entries), expression, result_total,
            now_dt.strftime("%Y-%m-%d"), now_dt.strftime("%H:%M:%S"),
            spoken_transcript
        ))
        session_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        inventory_updates = []
        unresolved_indices = []

        for idx, e in enumerate(entries):
            pid = e.get("item_id")
            qty = int(e.get("qty", 1))
            item_name = (e.get("item_name") or e.get("name") or "").strip() or "Unknown Item"
            price = float(e.get("price", 0))

            # Auto-create product if named but not in inventory
            if not pid and item_name and item_name not in ("Unknown Item", ""):
                slug = ''.join(c for c in item_name.upper() if c.isalnum())[:6]
                sku = f"KS-{slug}-{uuid.uuid4().hex[:3].upper()}"
                conn.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", ("Other",))
                cat_row = conn.execute("SELECT id FROM categories WHERE name=?", ("Other",)).fetchone()
                cat_id = cat_row["id"] if cat_row else None
                conn.execute("""
                    INSERT INTO products (name, category_id, sku, purchase_price, selling_price,
                                          mrp, current_qty, min_stock, emoji)
                    VALUES (?,?,?,?,?,?,0,5,'📦')
                """, (item_name, cat_id, sku, price, price, price))
                pid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

            if pid:
                conn.execute(
                    "UPDATE products SET current_qty = current_qty - ?, updated_at = datetime('now') WHERE id=?",
                    (qty, pid)
                )
                conn.execute("""
                    INSERT INTO inventory_deduction_log
                        (session_id, item_id, item_name, qty_deducted, price_at_time, alias_used)
                    VALUES (?,?,?,?,?,?)
                """, (session_id, pid, item_name, qty, price, e.get("alias_used", False)))
                conn.execute("""
                    INSERT INTO stock_logs
                        (transaction_id, product_id, product_name, qty_change, action_type, source, reason)
                    VALUES (?,?,?,?,'sale','calculator_parallel',?)
                """, (f"CALC-{session_id}-{pid}", pid, item_name, -qty, f"Session {session_id} | confidence={confidence_score:.2f}"))

                inventory_updates.append({
                    "item_id": pid, "item_name": item_name,
                    "qty_deducted": qty, "price": price,
                })
            else:
                unresolved_indices.append(idx)

        conn.execute(
            "UPDATE calculator_sessions SET unresolved_operands=? WHERE id=?",
            (json.dumps(unresolved_indices), session_id)
        )

        # Mark staged_transaction committed
        conn.execute(
            "UPDATE staged_transactions SET status='committed', committed_at=datetime('now') WHERE txn_id=?",
            (txn_id,)
        )
        conn.commit()

    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        return _err(f"Commit failed: {exc}", 500)
    finally:
        try:
            conn.close()
        except Exception:
            pass

    # Clear in-memory buffer only after successful DB commit
    _txn_buffers.pop(txn_id, None)

    # Automatically learn transaction patterns into the Pattern Recognition Engine
    try:
        pattern_engine.record_transaction_patterns(entries)
    except Exception as ex:
        print(f"Pattern learning error on buffer commit: {ex}")

    return _ok({
        "status": "committed",
        "session_id": session_id,
        "inventory_updates": inventory_updates,
        "unresolved_count": len(unresolved_indices),
    })


@app.post("/api/txn-buffer/flag")
async def txn_buffer_flag(request: Request):
    """
    Called when confidence is low (< 0.50).
    Saves full snapshot to night_reconciliation.
    Does NOT deduct inventory — preserves accuracy.
    Marks staged_transactions.status = 'flagged'.
    Clears the in-memory buffer.
    """
    body = await request.json()
    txn_id = body.get("txn_id")
    reason = body.get("reason", "low_confidence")
    confidence_score = float(body.get("confidence_score", 0))
    payload = body.get("payload", {})

    if not txn_id:
        return _err("txn_id required")

    buf = _txn_buffers.get(txn_id, {})
    full_payload = {
        "asr_segments": buf.get("asr_segments", []),
        "calc_amounts": buf.get("calc_amounts", []),
        "finalized_result": buf.get("finalized_result"),
        **payload,
    }

    conn = get_conn()
    try:
        conn.execute("""
            INSERT INTO night_reconciliation
                (txn_id, reason, confidence_score, payload_json, status)
            VALUES (?,?,?,?,'pending')
        """, (txn_id, reason, confidence_score, json.dumps(full_payload)))

        conn.execute(
            "UPDATE staged_transactions SET status='flagged', flagged_at=datetime('now') WHERE txn_id=?",
            (txn_id,)
        )
        recon_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
    finally:
        conn.close()

    # Clear buffer — nothing was committed to inventory so no harm
    _txn_buffers.pop(txn_id, None)

    return _ok({"status": "flagged", "txn_id": txn_id, "reconciliation_id": recon_id, "reason": reason})


@app.post("/api/txn-buffer/discard")
async def txn_buffer_discard(request: Request):
    """Called when shopkeeper presses Clear (C). Cancels the buffer without any DB side-effects."""
    body = await request.json()
    txn_id = body.get("txn_id")
    if not txn_id:
        return _ok({"status": "noop"})

    _txn_buffers.pop(txn_id, None)

    conn = get_conn()
    try:
        conn.execute(
            "UPDATE staged_transactions SET status='cancelled' WHERE txn_id=? AND status='pending'",
            (txn_id,)
        )
        conn.commit()
    finally:
        conn.close()

    return _ok({"status": "discarded", "txn_id": txn_id})


# ─────────────────────────────────────────────────────────────────────────────
# Night Reconciliation Review endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/night-reconciliation")
async def get_night_reconciliation(status: str = "pending", limit: int = 50, offset: int = 0):
    """Return night reconciliation queue entries."""
    status = (status or "pending").strip().lower()
    limit = max(1, min(int(limit or 50), 200))
    conn = get_conn()
    try:
        rows = conn.execute("""
            SELECT id, txn_id, session_id, reason, confidence_score,
                   payload_json, status, notes, reviewed_at, created_at
            FROM night_reconciliation
            WHERE status = ?
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """, (status, limit, offset)).fetchall()

        total = conn.execute(
            "SELECT COUNT(*) FROM night_reconciliation WHERE status=?", (status,)
        ).fetchone()[0]
    finally:
        conn.close()

    out = []
    for r in rows:
        d = dict(r)
        try:
            d["payload"] = json.loads(d.pop("payload_json") or "{}")
        except Exception:
            d["payload"] = {}
        out.append(d)

    return _ok({"items": out, "total": total, "status_filter": status})


@app.post("/api/night-reconciliation/{recon_id}/resolve")
async def resolve_night_reconciliation(recon_id: int, request: Request):
    """
    Mark a reconciliation item as resolved or dismissed.
    Optionally commit inventory deductions for the items the shopkeeper confirms.
    """
    body = await request.json()
    resolution = (body.get("resolution") or "resolved").strip().lower()
    if resolution not in ("resolved", "dismissed"):
        return _err("resolution must be resolved|dismissed")

    confirmed_entries = body.get("confirmed_entries", [])   # items shopkeeper confirms
    notes = (body.get("notes") or "").strip()

    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM night_reconciliation WHERE id=?", (recon_id,)
        ).fetchone()
        if not row:
            return _err("Record not found", 404)

        inventory_updates = []
        if resolution == "resolved" and confirmed_entries:
            now_dt = datetime.now()
            conn.execute("""
                INSERT INTO calculator_sessions
                    (entries_json, expression, result, session_date, session_time, status, spoken_transcript)
                VALUES (?, ?, ?, ?, ?, 'confirmed', ?)
            """, (
                json.dumps(confirmed_entries),
                " + ".join(str(e.get("price", 0)) for e in confirmed_entries),
                sum(e.get("price", 0) * e.get("qty", 1) for e in confirmed_entries),
                now_dt.strftime("%Y-%m-%d"),
                now_dt.strftime("%H:%M:%S"),
                f"Night reconciliation #{recon_id}",
            ))
            session_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.execute(
                "UPDATE night_reconciliation SET session_id=? WHERE id=?",
                (session_id, recon_id)
            )

            for e in confirmed_entries:
                pid = e.get("item_id")
                qty = int(e.get("qty", 1))
                item_name = (e.get("item_name") or "").strip()
                price = float(e.get("price", 0))
                if pid and qty > 0:
                    conn.execute(
                        "UPDATE products SET current_qty = current_qty - ?, updated_at = datetime('now') WHERE id=?",
                        (qty, pid)
                    )
                    conn.execute("""
                        INSERT INTO stock_logs
                            (transaction_id, product_id, product_name, qty_change, action_type, source, reason)
                        VALUES (?,?,?,?,'sale','night_reconciliation',?)
                    """, (
                        f"RECON-{recon_id}-{pid}", pid, item_name, -qty,
                        f"Night reconciliation #{recon_id}"
                    ))
                    inventory_updates.append({"item_id": pid, "item_name": item_name, "qty_deducted": qty})

        conn.execute("""
            UPDATE night_reconciliation
            SET status=?, notes=?, reviewed_at=datetime('now')
            WHERE id=?
        """, (resolution, notes, recon_id))

        conn.commit()
        if resolution == "resolved" and confirmed_entries:
            try:
                pattern_engine.record_transaction_patterns(confirmed_entries)
            except Exception as ex:
                print(f"Pattern learning error on recon resolve: {ex}")
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        conn.close()
        return _err(str(exc), 500)
    finally:
        try:
            conn.close()
        except Exception:
            pass

    return _ok({
        "status": resolution,
        "id": recon_id,
        "inventory_updates": inventory_updates,
    })


@app.get("/api/night-reconciliation/stats")
async def night_reconciliation_stats():
    """Quick stats for the reconciliation badge/dashboard."""
    conn = get_conn()
    try:
        pending = conn.execute(
            "SELECT COUNT(*) FROM night_reconciliation WHERE status='pending'"
        ).fetchone()[0]
        resolved_today = conn.execute(
            "SELECT COUNT(*) FROM night_reconciliation WHERE status='resolved' AND date(reviewed_at)=date('now')"
        ).fetchone()[0]
        total_today = conn.execute(
            "SELECT COUNT(*) FROM night_reconciliation WHERE date(created_at)=date('now')"
        ).fetchone()[0]
    finally:
        conn.close()

    return _ok({
        "pending": pending,
        "resolved_today": resolved_today,
        "total_today": total_today,
    })


# ═════════════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("ORCHESTRATOR_PORT", 8000))
    logger.info(f"""
╔═══════════════════════════════════════════════════════╗
║           KhataSnap Orchestrator v1.0                ║
║  Port: {port}                                          ║
║  Routes: /api/ocr/* /api/voice/* /api/sre/*          ║
║          /api/inventory/* /api/products/*             ║
║          /api/calculator/* /api/dashboard             ║
║          /api/txn-buffer/* /api/night-reconciliation/*║
╚═══════════════════════════════════════════════════════╝
    """)
    uvicorn.run(app, host="0.0.0.0", port=port)

