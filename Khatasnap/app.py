"""
KhataSnap — Flask Application
Single file, SQLite backend, serves the mobile PWA frontend.

Run:  python app.py
Open: http://localhost:8000  (or your local IP on any phone on same WiFi)
"""

import os
import json
import logging
import traceback
from datetime import datetime
from collections import defaultdict

from flask import Flask, jsonify, request, render_template, send_from_directory
try:
    from flask_cors import CORS
except ImportError:
    # flask-cors not installed — use Flask's built-in after_request for CORS
    class CORS:
        def __init__(self, app=None, **kwargs):
            if app:
                @app.after_request
                def _cors(response):
                    response.headers['Access-Control-Allow-Origin'] = '*'
                    response.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization'
                    response.headers['Access-Control-Allow-Methods'] = 'GET,POST,PUT,DELETE,OPTIONS'
                    return response

from database import get_conn, init_db
from helpers  import generate_sku, generate_txn_id, generate_bill_no, fuzzy_match, normalize

# ── SRE engine (unchanged from original) ─────────────────────────────────────
from sre_engine import (
    create_session, get_session, answer_question, clear_session,
    generate_best_question, get_next_question, should_continue_questioning,
    save_learning, get_learning_log, find_relevant_memories,
    get_session_memories, find_history_seeds, check_warm_start,
    _memory_confidence, _decay_weight, get_memory_stats,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__, template_folder='templates', static_folder='static')
CORS(app)


# ══════════════════════════════════════════════════════════════════════════════
# UTILITY
# ══════════════════════════════════════════════════════════════════════════════

def db():
    """Open a connection. Always close in a finally block."""
    return get_conn()


def row_to_dict(row):
    """sqlite3.Row → plain dict."""
    if row is None:
        return None
    return dict(row)


def rows_to_list(rows):
    return [dict(r) for r in rows]


def is_duplicate_txn(cur, txn_id):
    cur.execute("SELECT 1 FROM processed_transactions WHERE transaction_id=?", (txn_id,))
    return cur.fetchone() is not None


def mark_txn_done(cur, txn_id, source):
    cur.execute(
        "INSERT OR IGNORE INTO processed_transactions (transaction_id,source) VALUES (?,?)",
        (txn_id, source)
    )


def get_all_products_with_aliases(cur):
    cur.execute("""
        SELECT p.id, p.name,
               group_concat(pa.alias, '|||') AS alias_blob
        FROM products p
        LEFT JOIN product_aliases pa ON pa.product_id = p.id
        WHERE p.is_active = 1
        GROUP BY p.id
    """)
    result = []
    for row in cur.fetchall():
        d = dict(row)
        blob = d.pop('alias_blob', '') or ''
        d['aliases'] = [a for a in blob.split('|||') if a] if blob else []
        result.append(d)
    return result


def update_stock(cur, conn, product_id, qty_change, action_type, source, reason='', txn_id=None):
    """Central stock update. Returns (ok, result_dict_or_error_str)."""
    cur.execute(
        "SELECT id, name, current_qty FROM products WHERE id=? AND is_active=1",
        (product_id,)
    )
    product = cur.fetchone()
    if not product:
        return False, "Product not found"

    old_qty = product['current_qty']
    new_qty = max(0, old_qty + qty_change)

    cur.execute(
        "UPDATE products SET current_qty=?, updated_at=datetime('now') WHERE id=?",
        (new_qty, product_id)
    )

    txn = txn_id or generate_txn_id(source)
    cur.execute("""
        INSERT OR IGNORE INTO stock_logs
            (transaction_id, product_id, product_name, qty_change,
             action_type, source, reason, old_qty, new_qty)
        VALUES (?,?,?,?,?,?,?,?,?)
    """, (txn, product_id, product['name'], qty_change,
          action_type, source, reason, old_qty, new_qty))

    conn.commit()
    return True, {
        'old_qty':   old_qty,
        'new_qty':   new_qty,
        'product':   product['name'],
        'txn_id':    txn,
    }


# ══════════════════════════════════════════════════════════════════════════════
# SERVE THE MOBILE FRONTEND
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/')
def index():
    return render_template('index.html')


# ── Static fallback (in case static/ has assets) ────────────────────────────
@app.route('/static/<path:path>')
def serve_static(path):
    return send_from_directory('static', path)


# ══════════════════════════════════════════════════════════════════════════════
# HEALTH
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/api/health')
def health():
    return jsonify({'status': 'ok', 'storage': 'sqlite', 'db': 'khatasnap.db'})


# ══════════════════════════════════════════════════════════════════════════════
# CATEGORIES
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/api/categories', methods=['GET'])
def get_categories():
    conn = db()
    cur  = conn.cursor()
    cur.execute("SELECT * FROM categories ORDER BY name")
    rows = rows_to_list(cur.fetchall())
    cur.close(); conn.close()
    return jsonify(rows)


@app.route('/api/categories', methods=['POST'])
def add_category():
    data = request.json or {}
    name = data.get('name', '').strip()
    if not name:
        return jsonify({'error': 'Name required'}), 400
    conn = db(); cur = conn.cursor()
    try:
        cur.execute("INSERT INTO categories (name) VALUES (?) RETURNING *", (name,))
        row = row_to_dict(cur.fetchone())
        conn.commit()
        return jsonify(row), 201
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 409
    finally:
        cur.close(); conn.close()


@app.route('/api/categories/<int:cat_id>', methods=['PUT'])
def edit_category(cat_id):
    data = request.json or {}
    conn = db(); cur = conn.cursor()
    cur.execute("UPDATE categories SET name=? WHERE id=? RETURNING *", (data['name'], cat_id))
    row = row_to_dict(cur.fetchone())
    conn.commit(); cur.close(); conn.close()
    return jsonify(row)


@app.route('/api/categories/<int:cat_id>', methods=['DELETE'])
def delete_category(cat_id):
    conn = db(); cur = conn.cursor()
    cur.execute("DELETE FROM categories WHERE id=?", (cat_id,))
    conn.commit(); cur.close(); conn.close()
    return jsonify({'success': True})


# ══════════════════════════════════════════════════════════════════════════════
# SUPPLIERS
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/api/suppliers', methods=['GET'])
def get_suppliers():
    conn = db(); cur = conn.cursor()
    cur.execute("SELECT * FROM suppliers ORDER BY name")
    rows = rows_to_list(cur.fetchall())
    cur.close(); conn.close()
    return jsonify(rows)


@app.route('/api/suppliers', methods=['POST'])
def add_supplier():
    data = request.json or {}
    conn = db(); cur = conn.cursor()
    cur.execute(
        "INSERT INTO suppliers (name,phone,address) VALUES (?,?,?) RETURNING *",
        (data['name'], data.get('phone'), data.get('address'))
    )
    row = row_to_dict(cur.fetchone())
    conn.commit(); cur.close(); conn.close()
    return jsonify(row), 201


@app.route('/api/suppliers/<int:sup_id>', methods=['PUT'])
def edit_supplier(sup_id):
    data = request.json or {}
    conn = db(); cur = conn.cursor()
    cur.execute(
        "UPDATE suppliers SET name=?,phone=?,address=? WHERE id=? RETURNING *",
        (data['name'], data.get('phone'), data.get('address'), sup_id)
    )
    row = row_to_dict(cur.fetchone())
    conn.commit(); cur.close(); conn.close()
    return jsonify(row)


@app.route('/api/suppliers/<int:sup_id>', methods=['DELETE'])
def delete_supplier(sup_id):
    conn = db(); cur = conn.cursor()
    cur.execute("DELETE FROM suppliers WHERE id=?", (sup_id,))
    conn.commit(); cur.close(); conn.close()
    return jsonify({'success': True})


# ══════════════════════════════════════════════════════════════════════════════
# PRODUCTS  (the mobile UI's core data source)
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/api/products', methods=['GET'])
def get_products():
    conn = db(); cur = conn.cursor()
    cur.execute("""
        SELECT p.*,
               c.name AS category_name,
               s.name AS supplier_name,
               group_concat(pa.alias,'|||') AS alias_blob
        FROM products p
        LEFT JOIN categories c ON c.id = p.category_id
        LEFT JOIN suppliers  s ON s.id = p.supplier_id
        LEFT JOIN product_aliases pa ON pa.product_id = p.id
        WHERE p.is_active = 1
        GROUP BY p.id
        ORDER BY p.name
    """)
    result = []
    for row in cur.fetchall():
        d = dict(row)
        blob = d.pop('alias_blob', '') or ''
        d['aliases'] = [a for a in blob.split('|||') if a]
        # Compute profit margin
        pp = d.get('purchase_price', 0) or 0
        sp = d.get('selling_price', 0)  or 0
        d['profit_margin'] = round((sp - pp) / pp * 100, 2) if pp else 0
        result.append(d)
    cur.close(); conn.close()
    return jsonify(result)


@app.route('/api/products', methods=['POST'])
def add_product():
    data = request.json or {}
    name = data.get('name', '').strip()
    if not name:
        return jsonify({'error': 'Product name required'}), 400

    conn = db(); cur = conn.cursor()

    # Duplicate check
    cur.execute("SELECT id FROM products WHERE LOWER(name)=LOWER(?) AND is_active=1", (name,))
    if cur.fetchone():
        cur.close(); conn.close()
        return jsonify({'error': f'"{name}" already exists'}), 409

    sku = data.get('sku') or generate_sku(name, data.get('brand', ''))
    cur.execute("SELECT id FROM products WHERE sku=?", (sku,))
    if cur.fetchone():
        sku = generate_sku(name, data.get('brand', ''))

    try:
        cur.execute("""
            INSERT INTO products
                (name, category_id, brand, sku, barcode, purchase_price,
                 selling_price, mrp, unit_type, current_qty, min_stock,
                 expiry_date, supplier_id, emoji, notes)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) RETURNING *
        """, (
            name, data.get('category_id'), data.get('brand'), sku,
            data.get('barcode'),
            float(data.get('purchase_price', 0)),
            float(data.get('selling_price', 0)),
            float(data.get('mrp', 0)),
            data.get('unit_type', 'pcs'),
            int(data.get('current_qty', 0)),
            int(data.get('min_stock', 5)),
            data.get('expiry_date') or None,
            data.get('supplier_id'),
            data.get('emoji', '📦'),
            data.get('notes'),
        ))
        product = dict(cur.fetchone())

        # Log initial stock if qty > 0
        if product['current_qty'] > 0:
            txn = generate_txn_id('ADD')
            cur.execute("""
                INSERT OR IGNORE INTO stock_logs
                    (transaction_id, product_id, product_name, qty_change,
                     action_type, source, old_qty, new_qty)
                VALUES (?,?,?,?,'stock_in','manual',0,?)
            """, (txn, product['id'], product['name'],
                  product['current_qty'], product['current_qty']))

        conn.commit()
        return jsonify(product), 201
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 400
    finally:
        cur.close(); conn.close()


@app.route('/api/products/<int:pid>', methods=['GET'])
def get_product(pid):
    conn = db(); cur = conn.cursor()
    cur.execute("""
        SELECT p.*, c.name AS category_name, s.name AS supplier_name,
               group_concat(pa.alias,'|||') AS alias_blob,
               group_concat(pa.id,   '|||') AS alias_id_blob
        FROM products p
        LEFT JOIN categories c ON c.id = p.category_id
        LEFT JOIN suppliers  s ON s.id = p.supplier_id
        LEFT JOIN product_aliases pa ON pa.product_id = p.id
        WHERE p.id=? GROUP BY p.id
    """, (pid,))
    row = cur.fetchone()
    cur.close(); conn.close()
    if not row:
        return jsonify({'error': 'Not found'}), 404
    d = dict(row)
    blob    = d.pop('alias_blob',    '') or ''
    id_blob = d.pop('alias_id_blob', '') or ''
    d['aliases']    = [a for a in blob.split('|||')    if a]
    d['alias_ids']  = [a for a in id_blob.split('|||') if a]
    return jsonify(d)


@app.route('/api/products/<int:pid>', methods=['PUT'])
def edit_product(pid):
    data = request.json or {}
    conn = db(); cur = conn.cursor()
    cur.execute("""
        UPDATE products SET
            name=?, category_id=?, brand=?, barcode=?,
            purchase_price=?, selling_price=?, mrp=?,
            unit_type=?, min_stock=?, expiry_date=?,
            supplier_id=?, emoji=?, notes=?,
            updated_at=datetime('now')
        WHERE id=? RETURNING *
    """, (
        data['name'], data.get('category_id'), data.get('brand'),
        data.get('barcode'),
        float(data.get('purchase_price', 0)),
        float(data.get('selling_price', 0)),
        float(data.get('mrp', 0)),
        data.get('unit_type', 'pcs'),
        int(data.get('min_stock', 5)),
        data.get('expiry_date') or None,
        data.get('supplier_id'),
        data.get('emoji', '📦'),
        data.get('notes'),
        pid
    ))
    row = row_to_dict(cur.fetchone())
    conn.commit(); cur.close(); conn.close()
    return jsonify(row)


@app.route('/api/products/<int:pid>', methods=['DELETE'])
def delete_product(pid):
    conn = db(); cur = conn.cursor()
    cur.execute("UPDATE products SET is_active=0 WHERE id=?", (pid,))
    conn.commit(); cur.close(); conn.close()
    return jsonify({'success': True})


# ── Aliases ──────────────────────────────────────────────────────────────────

@app.route('/api/products/<int:pid>/aliases', methods=['POST'])
def add_alias(pid):
    alias = (request.json or {}).get('alias', '').strip()
    conn  = db(); cur = conn.cursor()
    cur.execute(
        "INSERT INTO product_aliases (product_id, alias) VALUES (?,?) RETURNING *",
        (pid, alias)
    )
    row = row_to_dict(cur.fetchone())
    conn.commit(); cur.close(); conn.close()
    return jsonify(row), 201


@app.route('/api/aliases/<int:alias_id>', methods=['DELETE'])
def delete_alias(alias_id):
    conn = db(); cur = conn.cursor()
    cur.execute("DELETE FROM product_aliases WHERE id=?", (alias_id,))
    conn.commit(); cur.close(); conn.close()
    return jsonify({'success': True})


# ══════════════════════════════════════════════════════════════════════════════
# STOCK MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/api/stock/add', methods=['POST'])
def stock_add():
    data   = request.json or {}
    pid    = data.get('product_id')
    qty    = int(data.get('qty', 0))
    reason = data.get('reason', '')
    txn    = generate_txn_id('ADD')
    conn   = db()
    ok, result = update_stock(conn.cursor(), conn, pid, qty, 'stock_in', 'manual', reason, txn)
    conn.close()
    if ok:
        return jsonify({'success': True, 'txn_id': txn, **result})
    return jsonify({'error': result}), 400


@app.route('/api/stock/remove', methods=['POST'])
def stock_remove():
    data   = request.json or {}
    pid    = data.get('product_id')
    qty    = int(data.get('qty', 0))
    reason = data.get('reason', '')
    txn    = generate_txn_id('REM')
    conn   = db()
    ok, result = update_stock(conn.cursor(), conn, pid, -qty, 'stock_out', 'manual', reason, txn)
    conn.close()
    if ok:
        return jsonify({'success': True, 'txn_id': txn, **result})
    return jsonify({'error': result}), 400


@app.route('/api/stock/adjust', methods=['POST'])
def stock_adjust():
    data    = request.json or {}
    pid     = data.get('product_id')
    new_qty = int(data.get('new_qty', 0))
    reason  = data.get('reason', 'correction')
    txn     = generate_txn_id('ADJ')
    conn    = db(); cur = conn.cursor()
    cur.execute("SELECT current_qty FROM products WHERE id=?", (pid,))
    row = cur.fetchone()
    if not row:
        cur.close(); conn.close()
        return jsonify({'error': 'Product not found'}), 404
    diff = new_qty - row['current_qty']
    ok, result = update_stock(cur, conn, pid, diff, 'adjustment', 'manual', reason, txn)
    cur.close(); conn.close()
    if ok:
        return jsonify({'success': True, 'txn_id': txn, **result})
    return jsonify({'error': result}), 400


# ══════════════════════════════════════════════════════════════════════════════
# INVENTORY READ APIs  (used by mobile frontend)
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/api/inventory', methods=['GET'])
def get_inventory():
    conn = db(); cur = conn.cursor()
    cur.execute("""
        SELECT p.id, p.name, p.sku, p.current_qty, p.min_stock,
               p.selling_price, p.purchase_price, p.unit_type, p.emoji,
               c.name AS category,
               CASE
                 WHEN p.current_qty = 0    THEN 'out'
                 WHEN p.current_qty <= p.min_stock THEN 'low'
                 ELSE 'ok'
               END AS stock_status
        FROM products p
        LEFT JOIN categories c ON c.id = p.category_id
        WHERE p.is_active = 1
        ORDER BY p.name
    """)
    rows = rows_to_list(cur.fetchall())
    cur.close(); conn.close()
    return jsonify(rows)


@app.route('/api/inventory/logs', methods=['GET'])
def get_logs():
    limit  = int(request.args.get('limit', 100))
    source = request.args.get('source')
    conn   = db(); cur = conn.cursor()
    if source:
        cur.execute(
            "SELECT * FROM stock_logs WHERE source=? ORDER BY created_at DESC LIMIT ?",
            (source, limit)
        )
    else:
        cur.execute("SELECT * FROM stock_logs ORDER BY created_at DESC LIMIT ?", (limit,))
    rows = rows_to_list(cur.fetchall())
    cur.close(); conn.close()
    return jsonify(rows)


@app.route('/api/inventory/low-stock', methods=['GET'])
def get_low_stock():
    conn = db(); cur = conn.cursor()
    cur.execute("""
        SELECT p.*, c.name AS category_name
        FROM products p
        LEFT JOIN categories c ON c.id = p.category_id
        WHERE p.is_active=1 AND p.current_qty <= p.min_stock
        ORDER BY p.current_qty ASC
    """)
    rows = rows_to_list(cur.fetchall())
    cur.close(); conn.close()
    return jsonify(rows)


# ══════════════════════════════════════════════════════════════════════════════
# DASHBOARD  (used by Analytics screen)
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/api/dashboard', methods=['GET'])
def dashboard():
    conn = db(); cur = conn.cursor()

    cur.execute("""
        SELECT
            COUNT(*) AS total_products,
            SUM(current_qty * purchase_price) AS total_purchase_value,
            SUM(current_qty * selling_price)  AS total_selling_value,
            COUNT(*) FILTER (WHERE current_qty = 0)            AS out_of_stock,
            COUNT(*) FILTER (WHERE current_qty > 0
                AND current_qty <= min_stock) AS low_stock,
            COUNT(*) FILTER (WHERE current_qty > min_stock)    AS in_stock
        FROM products WHERE is_active=1
    """)
    stats = dict(cur.fetchone())

    # Low stock items
    cur.execute("""
        SELECT p.name, p.current_qty, p.min_stock, c.name AS category
        FROM products p
        LEFT JOIN categories c ON c.id = p.category_id
        WHERE p.is_active=1 AND p.current_qty <= p.min_stock
        ORDER BY p.current_qty ASC LIMIT 5
    """)
    stats['low_stock_items'] = rows_to_list(cur.fetchall())

    # Recent activity
    cur.execute("""
        SELECT product_name, qty_change, action_type, source,
               old_qty, new_qty, created_at
        FROM stock_logs ORDER BY created_at DESC LIMIT 10
    """)
    stats['recent_activity'] = rows_to_list(cur.fetchall())

    # Today's revenue from completed bills
    today = datetime.now().strftime('%Y-%m-%d')
    cur.execute("""
        SELECT
            COUNT(*) AS total_bills,
            SUM(total_amount) AS total_revenue,
            AVG(total_amount) AS avg_bill,
            COUNT(*) FILTER (WHERE payment_mode='cash') AS cash_count,
            SUM(CASE WHEN payment_mode='cash' THEN total_amount ELSE 0 END) AS cash_total,
            COUNT(*) FILTER (WHERE payment_mode='upi')  AS upi_count,
            SUM(CASE WHEN payment_mode='upi'  THEN total_amount ELSE 0 END) AS upi_total
        FROM completed_bills
        WHERE date(created_at) = ?
    """, (today,))
    day_stats = dict(cur.fetchone())
    stats.update({k: (v or 0) for k, v in day_stats.items()})

    # Hourly sales (last 12 hours) for bar chart
    cur.execute("""
        SELECT strftime('%H', created_at) AS hr,
               SUM(total_amount) AS revenue
        FROM completed_bills
        WHERE date(created_at) = ?
        GROUP BY hr ORDER BY hr
    """, (today,))
    stats['hourly_sales'] = rows_to_list(cur.fetchall())

    # Top products by deduction count today
    cur.execute("""
        SELECT product_name, SUM(ABS(qty_change)) AS total_sold
        FROM stock_logs
        WHERE action_type='stock_out'
          AND date(created_at) = ?
        GROUP BY product_name
        ORDER BY total_sold DESC LIMIT 5
    """, (today,))
    stats['top_products'] = rows_to_list(cur.fetchall())

    # Voice billing count (source='voice')
    cur.execute("""
        SELECT COUNT(*) AS cnt FROM stock_logs
        WHERE source='voice' AND date(created_at)=?
    """, (today,))
    _row = cur.fetchone()
    stats['voice_bills_today'] = dict(_row)['cnt'] if _row else 0

    cur.close(); conn.close()
    return jsonify(stats)


# ══════════════════════════════════════════════════════════════════════════════
# COMPLETED BILLS  (mobile checkout saves here)
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/api/bills', methods=['POST'])
def save_bill():
    """
    Called when shopkeeper taps Pay Cash / Pay UPI on the mobile Bill screen.
    Body: { items:[{name,qty,price,emoji}], total_amount, payment_mode, source }
    """
    data         = request.json or {}
    items        = data.get('items', [])
    total_amount = float(data.get('total_amount', 0))
    payment_mode = data.get('payment_mode', 'cash')
    source       = data.get('source', 'manual')

    if not items:
        return jsonify({'error': 'Items required'}), 400
    if payment_mode not in ('cash', 'upi'):
        return jsonify({'error': 'payment_mode must be cash or upi'}), 400

    bill_no = generate_bill_no()
    conn    = db(); cur = conn.cursor()

    try:
        cur.execute("""
            INSERT INTO completed_bills
                (bill_no, items, total_amount, payment_mode, source)
            VALUES (?,?,?,?,?)
        """, (bill_no, json.dumps(items), total_amount, payment_mode, source))

        # Deduct stock for each item (best-effort fuzzy match)
        products = get_all_products_with_aliases(cur)
        for item in items:
            name  = item.get('name', '')
            qty   = int(item.get('qty', 1))
            matched, conf = fuzzy_match(name, products, min_confidence=0.55)
            if matched and qty > 0:
                update_stock(
                    cur, conn, matched['id'], -qty,
                    'stock_out', source,
                    f"Bill {bill_no} ({payment_mode})",
                    generate_txn_id('BILL')
                )

        conn.commit()
        return jsonify({'success': True, 'bill_no': bill_no}), 201
    except Exception as e:
        conn.rollback()
        logger.error("Bill save error: %s", e)
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close(); conn.close()


@app.route('/api/bills', methods=['GET'])
def get_bills():
    limit = int(request.args.get('limit', 50))
    date  = request.args.get('date')
    conn  = db(); cur = conn.cursor()
    if date:
        cur.execute(
            "SELECT * FROM completed_bills WHERE date(created_at)=? ORDER BY created_at DESC LIMIT ?",
            (date, limit)
        )
    else:
        cur.execute("SELECT * FROM completed_bills ORDER BY created_at DESC LIMIT ?", (limit,))
    rows = rows_to_list(cur.fetchall())
    cur.close(); conn.close()
    # Parse items JSON
    for r in rows:
        if isinstance(r.get('items'), str):
            try:
                r['items'] = json.loads(r['items'])
            except Exception:
                pass
    return jsonify(rows)


# ══════════════════════════════════════════════════════════════════════════════
# OCR INTEGRATION  — receive items from OCR pipeline
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/api/ocr1', methods=['POST'])
def ocr1_input():
    """Sales bill → DEDUCT stock."""
    data   = request.json or {}
    txn_id = data.get('transaction_id') or generate_txn_id('OCR1')
    conn   = db(); cur = conn.cursor()

    if is_duplicate_txn(cur, txn_id):
        cur.close(); conn.close()
        return jsonify({'error': 'Duplicate transaction'}), 409

    products = get_all_products_with_aliases(cur)
    log      = []

    for entry in data.get('items', []):
        name = str(entry.get('name', '')).strip()
        qty  = int(entry.get('qty', 0))
        matched, conf = fuzzy_match(name, products, min_confidence=0.55)
        if matched:
            ok, result = update_stock(cur, conn, matched['id'], -qty,
                                      'stock_out', 'ocr1', 'OCR1 sales bill', txn_id)
            log.append({'status': 'deducted' if ok else 'error',
                        'name': matched['name'], 'qty': qty,
                        'confidence': conf})
        else:
            log.append({'status': 'not_found', 'name': name,
                        'message': f"'{name}' not found"})

    mark_txn_done(cur, txn_id, 'ocr1')
    conn.commit(); cur.close(); conn.close()
    return jsonify({'success': True, 'txn_id': txn_id, 'log': log})


@app.route('/api/ocr2', methods=['POST'])
def ocr2_input():
    """Distributor bill → ADD stock. Creates new products if not found."""
    data   = request.json or {}
    txn_id = data.get('transaction_id') or generate_txn_id('OCR2')
    conn   = db(); cur = conn.cursor()

    if is_duplicate_txn(cur, txn_id):
        cur.close(); conn.close()
        return jsonify({'error': 'Duplicate transaction'}), 409

    products = get_all_products_with_aliases(cur)
    log      = []

    for entry in data.get('items', []):
        name = str(entry.get('name', '')).strip()
        qty  = int(entry.get('qty', 0))
        matched, conf = fuzzy_match(name, products, min_confidence=0.55)
        if matched:
            ok, result = update_stock(cur, conn, matched['id'], qty,
                                      'stock_in', 'ocr2', 'OCR2 distributor bill', txn_id)
            log.append({'status': 'added', 'name': matched['name'], 'qty': qty})
        else:
            # Auto-create new product
            sku = generate_sku(name)
            cur.execute("""
                INSERT INTO products (name, sku, current_qty, min_stock)
                VALUES (?,?,?,5) RETURNING id, name
            """, (name, sku, qty))
            new_p = dict(cur.fetchone())
            cur.execute("""
                INSERT OR IGNORE INTO stock_logs
                    (transaction_id, product_id, product_name, qty_change,
                     action_type, source, old_qty, new_qty)
                VALUES (?,?,?,?,'stock_in','ocr2',0,?)
            """, (generate_txn_id('OCR2'), new_p['id'], new_p['name'], qty, qty))
            log.append({'status': 'created', 'name': name, 'qty': qty})
            conn.commit()

    mark_txn_done(cur, txn_id, 'ocr2')
    conn.commit(); cur.close(); conn.close()
    return jsonify({'success': True, 'txn_id': txn_id, 'log': log})


# ══════════════════════════════════════════════════════════════════════════════
# ASR / VOICE INTEGRATION
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/api/voice/transcribe', methods=['POST'])
def voice_transcribe_local():
    data = request.json or {}
    transcript = data.get('transcript', '').lower().strip()
    if not transcript:
        return jsonify({'error': 'No transcript provided'}), 400

    conn = db()
    cur = conn.cursor()
    products = get_all_products_with_aliases(cur)
    cur.close()
    conn.close()

    quantity_words = {
        'ek':1, 'do':2, 'teen':3, 'char':4, 'paanch':5, 'chhe':6, 'saat':7, 'aath':8, 'nau':9, 'das':10,
        'one':1, 'two':2, 'three':3, 'four':4, 'five':5, 'six':6, 'seven':7, 'eight':8, 'nine':9, 'ten':10,
        'half':0.5, 'dhai':2.5, 'couple':2
    }
    
    words = transcript.split()
    seen_ids = set()
    matched_names = set()
    total_amount = 0
    structured_items = []
    
    for p in products:
        p_name_lower = p['name'].lower().strip()
        if p_name_lower in matched_names:
            continue
            
        matched, conf = fuzzy_match(transcript, [p], min_confidence=0.55)
        if matched and p['id'] not in seen_ids:
            seen_ids.add(p['id'])
            matched_names.add(p_name_lower)
            qty = 1
            match_index = -1
            alias_used = matched['name'].lower()
            if alias_used in transcript:
                alias_first = alias_used.split()[0]
                try:
                    match_index = words.index(alias_first)
                except ValueError:
                    pass
            if match_index > 0 and words[match_index-1] in quantity_words:
                qty = quantity_words[words[match_index-1]]
            elif match_index > 0 and words[match_index-1].isdigit():
                qty = int(words[match_index-1])
            elif match_index < len(words)-1 and words[match_index+1] in quantity_words:
                qty = quantity_words[words[match_index+1]]
            elif match_index < len(words)-1 and words[match_index+1].isdigit():
                qty = int(words[match_index+1])
                
            price = p.get('selling_price', 0)
            structured_items.append({
                "name": p['name'], "qty": qty, "price": price, "confidence": conf
            })
            total_amount += (price * qty)

    # Note: Returning nested in data to match React api.js formatting
    return jsonify({
        'success': True,
        'data': {
            'items': structured_items,
            'total_amount': total_amount
        }
    })

@app.route('/api/voice/inventory', methods=['POST'])
def voice_inventory_parse():
    """
    Parses an inventory voice command transcript.
    Detects action (add / deduct / remove) + quantity + item name via fuzzy match.
    Returns a PREVIEW — does NOT apply stock changes yet.
    Frontend confirms via /api/stock/add or /api/stock/remove.

    Example transcripts:
      "add 10 rice"
      "deduct 5 oil"
      "remove three bottles water"
      "add twenty kg sugar"
    """
    data = request.json or {}
    transcript = normalize(data.get('transcript', ''))
    if not transcript:
        return jsonify({'error': 'No transcript provided'}), 400

    # ── Detect action keyword ────────────────────────────────────────────────
    ADD_KEYWORDS    = ['add', 'stock in', 'restock', 'received', 'purchase',
                       'jodo', 'daalo', 'laya', 'aaya']
    DEDUCT_KEYWORDS = ['deduct', 'remove', 'sell', 'sold', 'reduce', 'minus',
                       'hatao', 'kam karo', 'nikalo', 'gaya', 'bika']

    action = None
    for kw in ADD_KEYWORDS:
        if kw in transcript:
            action = 'add'
            break
    if action is None:
        for kw in DEDUCT_KEYWORDS:
            if kw in transcript:
                action = 'deduct'
                break

    if action is None:
        return jsonify({'error': 'No action detected. Say "add" or "deduct/remove".'}), 422

    # ── Quantity word map ────────────────────────────────────────────────────
    quantity_words = {
        'ek': 1, 'do': 2, 'teen': 3, 'char': 4, 'paanch': 5,
        'chhe': 6, 'saat': 7, 'aath': 8, 'nau': 9, 'das': 10,
        'bees': 20, 'tees': 30, 'chalis': 40, 'pachas': 50,
        'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5,
        'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10,
        'eleven': 11, 'twelve': 12, 'fifteen': 15, 'twenty': 20,
        'thirty': 30, 'forty': 40, 'fifty': 50, 'hundred': 100,
        'half': 0.5, 'couple': 2, 'dozen': 12,
    }

    words = transcript.split()
    parsed_qty = 1

    # Try to extract a number (digit or word) from the transcript
    for i, w in enumerate(words):
        if w.isdigit():
            parsed_qty = int(w)
            break
        if w in quantity_words:
            parsed_qty = quantity_words[w]
            break

    # ── Fuzzy-match item name in transcript ──────────────────────────────────
    conn = db()
    cur  = conn.cursor()
    products = get_all_products_with_aliases(cur)

    best_match = None
    best_conf  = 0.0
    for p in products:
        matched, conf = fuzzy_match(transcript, [p], min_confidence=0.45)
        if matched and conf > best_conf:
            best_match = matched
            best_conf  = conf

    if not best_match:
        cur.close(); conn.close()
        return jsonify({'error': 'No matching product found in inventory.'}), 404

    # Fetch current stock
    cur.execute("SELECT current_qty FROM products WHERE id=?", (best_match['id'],))
    row = cur.fetchone()
    current_qty = row['current_qty'] if row else 0
    cur.close(); conn.close()

    new_qty = (current_qty + parsed_qty) if action == 'add' else max(0, current_qty - parsed_qty)

    return jsonify({
        'success': True,
        'data': {
            'items': [{
                'action':       action,
                'product_id':   best_match['id'],
                'product_name': best_match['name'],
                'qty':          parsed_qty,
                'current_qty':  current_qty,
                'new_qty':      new_qty,
                'confidence':   round(best_conf, 3),
            }],
        }
    })


@app.route('/api/asr', methods=['POST'])

def asr_input():
    """
    Voice sale endpoint.
    Single: { name, qty }  OR  Batch: { items:[{name,qty}] }
    NOW FIXED: routes through /api/bills instead of direct stock update
    """
    data = request.json or {}

    items_input = data.get('items') or [
        {'name': data.get('name'), 'qty': data.get('qty', 1)}
    ]

    if not items_input:
        return jsonify({'error': 'No items provided'}), 400

    conn = db()
    cur = conn.cursor()

    products = get_all_products_with_aliases(cur)

    structured_items = []
    total_amount = 0

    for entry in items_input:
        name = str(entry.get('name', '')).strip()
        qty = int(entry.get('qty', 1))

        matched, conf = fuzzy_match(name, products, min_confidence=0.55)

        if not matched:
            continue

        price = matched.get('selling_price', 0) or 0

        structured_items.append({
            "name": matched['name'],
            "qty": qty,
            "price": price,
            "emoji": "🛒"
        })

        total_amount += price * qty

    cur.close()
    conn.close()

    if not structured_items:
        return jsonify({
            'error': 'No valid items matched from voice input'
        }), 400

    # 🔥 ROUTE THROUGH BILL SYSTEM (MAIN FIX)
    with app.test_request_context(
        '/api/bills',
        method='POST',
        json={
            "items": structured_items,
            "total_amount": total_amount,
            "payment_mode": data.get('payment_mode', 'cash'),
            "source": "voice"
        }
    ):
        return save_bill()


# ══════════════════════════════════════════════════════════════════════════════
# OCR SCAN ENDPOINT  (receives image, runs pipeline, returns items)
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/api/ocr/scan', methods=['POST'])
def ocr_scan():
    """
    Accepts an image file, runs the full OCR pipeline, returns structured items.
    Frontend can call this when user scans a receipt.
    """
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400

    f = request.files['file']
    if f.content_type not in {
        'image/jpeg', 'image/jpg', 'image/png',
        'image/webp', 'image/bmp', 'application/pdf'
    }:
        return jsonify({'error': 'Unsupported file type'}), 400

    contents = f.read()
    if len(contents) > 20 * 1024 * 1024:
        return jsonify({'error': 'File too large (max 20MB)'}), 400

    try:
        from orchestrator import process_invoice
        result = process_invoice(contents, f.filename or 'upload')

        # Sanitize numpy types for JSON
        import numpy as np

        def sanitize(obj):
            if isinstance(obj, dict):
                return {k: sanitize(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [sanitize(v) for v in obj]
            if isinstance(obj, np.integer):
                return int(obj)
            if isinstance(obj, np.floating):
                return float(obj)
            if isinstance(obj, np.ndarray):
                return obj.tolist()
            return obj

        return jsonify(sanitize(result))
    except ImportError:
        return jsonify({'error': 'OCR pipeline not available — install paddleocr'}), 503
    except Exception as e:
        logger.error("OCR scan error:\n%s", traceback.format_exc())
        return jsonify({'error': str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════════
# SRE — SMART RECONCILIATION ENGINE
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/api/sre/smart/start', methods=['POST'])
def sre_start():
    data            = request.json or {}
    mismatch_amount = data.get('mismatch_amount')

    if not mismatch_amount or float(mismatch_amount) <= 0:
        return jsonify({'error': 'Valid mismatch_amount required'}), 400

    conn = db(); cur = conn.cursor()
    cur.execute("""
        SELECT p.id, p.name, p.selling_price, p.current_qty,
               COALESCE(c.name,'Unknown') AS category
        FROM products p
        LEFT JOIN categories c ON c.id = p.category_id
        WHERE p.is_active=1 AND p.selling_price > 0
        ORDER BY p.name
    """)
    products = rows_to_list(cur.fetchall())
    cur.close(); conn.close()

    if not products:
        return jsonify({'error': 'No products found'}), 404

    session_id, session = create_session(products, float(mismatch_amount))
    total_combos       = len(session['combos'])

    if total_combos == 0:
        return jsonify({'session_id': session_id, 'status': 'NO_MATCH',
                        'message': f'No combination matches ₹{mismatch_amount}'})

    if total_combos == 1:
        return jsonify({'session_id': session_id, 'status': 'SOLVED',
                        'result': session['combos'][0], 'total_combos': 1,
                        'probabilities': session['probabilities'], 'warm_start': False})

    warm = check_warm_start(float(mismatch_amount), session['combos'])
    if warm:
        return jsonify({'session_id': session_id, 'status': 'SOLVED',
                        'result': warm['combo'], 'total_combos': total_combos,
                        'probabilities': session['probabilities'],
                        'warm_start': True, 'warm_reason': warm['reason']})

    question = generate_best_question(
        session['combos'], session['products'],
        session['asked_products'], session['asked_types'],
        q_number=1,
        relevant_memories=session.get('relevant_memories'),
        history_seeds=session.get('history_seeds'),
        cooccurrence=session.get('cooccurrence'),
    )
    return jsonify({
        'session_id':    session_id, 'status': 'QUESTIONING',
        'total_combos':  total_combos,
        'probabilities': session['probabilities'],
        'question':      question,
        'history_seeds': session.get('history_seeds', []),
    })


@app.route('/api/sre/smart/answer', methods=['POST'])
def sre_answer():
    data          = request.json or {}
    session_id    = data.get('session_id')
    question_dict = data.get('question_dict')
    product       = data.get('product')
    answer        = data.get('answer', '').lower()

    if not session_id or answer not in ('yes', 'no'):
        return jsonify({'error': 'session_id and answer required'}), 400

    if not question_dict and product:
        question_dict = {'type': 'product', 'product': product,
                         'question': f'Was "{product}" part of the mismatch?'}
    if not question_dict:
        return jsonify({'error': 'question_dict required'}), 400

    session, err = answer_question(session_id, question_dict, answer)
    if err:
        return jsonify({'error': err}), 404

    remaining  = len(session['combos'])
    keep_going = should_continue_questioning(session)

    if remaining == 0:
        return jsonify({'session_id': session_id, 'status': 'NO_MATCH',
                        'message': 'No combinations remaining.',
                        'question_count': session['question_count'],
                        'history': session['question_history']})

    if not keep_going:
        best_combo = session['combos'][0] if session['combos'] else []
        return jsonify({'session_id': session_id, 'status': 'SOLVED',
                        'result': best_combo, 'probabilities': session['probabilities'],
                        'question_count': session['question_count'],
                        'history': session['question_history'],
                        'remaining_combos': remaining})

    next_q = get_next_question(session_id)
    return jsonify({'session_id': session_id, 'status': 'QUESTIONING',
                    'remaining_combos': remaining, 'probabilities': session['probabilities'],
                    'question': next_q, 'question_count': session['question_count'],
                    'history': session['question_history']})


@app.route('/api/sre/smart/learn', methods=['POST'])
def sre_learn():
    data            = request.json or {}
    items           = data.get('items', [])
    amount          = data.get('amount', 0)
    session_id      = data.get('session_id')
    question_history= data.get('question_history', [])
    final_probs     = data.get('final_probs', [])
    product_details = data.get('product_details', [])

    if not items:
        return jsonify({'error': 'items required'}), 400
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        amount = 0.0
    if amount <= 0:
        return jsonify({'error': 'valid amount > 0 required'}), 400

    if not question_history and session_id:
        sess = get_session(session_id)
        if sess:
            question_history = sess.get('question_history', [])
            if not product_details:
                product_details = sess.get('products', [])
            if not final_probs:
                final_probs = sess.get('probabilities', [])

    entry = save_learning(items, float(amount),
                          question_history=question_history,
                          final_probs=final_probs,
                          product_details=product_details)
    return jsonify({'success': True, 'entry': entry,
                    'total_learnings': len(get_learning_log())})


@app.route('/api/sre/smart/learning-log', methods=['GET'])
def sre_learning_log():
    log   = get_learning_log()
    stats = get_memory_stats()
    return jsonify({'learning_log': log, **stats})


@app.route('/api/sre/smart/reset', methods=['POST'])
def sre_reset():
    session_id = (request.json or {}).get('session_id')
    if not session_id:
        return jsonify({'error': 'session_id required'}), 400
    clear_session(session_id)
    return jsonify({'success': True})


@app.route('/api/sre/reconcile', methods=['POST'])
def sre_reconcile():
    """Night reconciliation — set products to physical count."""
    data   = request.json or {}
    txn_id = generate_txn_id('SRE')
    conn   = db(); cur = conn.cursor()
    log    = []

    for correction in data.get('corrections', []):
        pid     = correction.get('product_id')
        new_qty = int(correction.get('correct_qty', 0))
        reason  = correction.get('reason', 'SRE reconciliation')
        cur.execute("SELECT current_qty FROM products WHERE id=?", (pid,))
        row = cur.fetchone()
        if row:
            diff = new_qty - row['current_qty']
            ok, result = update_stock(cur, conn, pid, diff, 'adjustment',
                                      'sre', reason, generate_txn_id('SRE'))
            log.append({'product_id': pid, 'old_qty': row['current_qty'],
                        'new_qty': new_qty, 'status': 'corrected'})

    conn.commit(); cur.close(); conn.close()
    return jsonify({'success': True, 'txn_id': txn_id, 'log': log})


@app.route('/api/sre/conflicts', methods=['GET'])
def get_conflicts():
    conn = db(); cur = conn.cursor()
    cur.execute("""
        SELECT vm.*, p.name AS product_name, ct.bill_total
        FROM value_product_mapping vm
        LEFT JOIN products p ON p.id = vm.product_id
        LEFT JOIN calculator_transactions ct ON ct.transaction_id = vm.transaction_id
        WHERE vm.status IN ('pending','uncertain')
        ORDER BY vm.created_at DESC LIMIT 50
    """)
    rows = rows_to_list(cur.fetchall())
    cur.close(); conn.close()
    return jsonify(rows)


@app.route('/api/sre/confirm-mapping', methods=['POST'])
def sre_confirm_mapping():
    data   = request.json or {}
    txn_id = data.get('transaction_id')
    idx    = data.get('value_index')
    pid    = data.get('product_id')
    action = data.get('action', 'confirm')
    conn   = db(); cur = conn.cursor()
    cur.execute(
        "UPDATE value_product_mapping SET product_id=?, status=? WHERE transaction_id=? AND value_index=?",
        (pid, action, txn_id, idx)
    )
    conn.commit(); cur.close(); conn.close()
    return jsonify({'success': True})


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    print("\n✅  KhataSnap — Local Storage Edition")
    print("──────────────────────────────────────")
    print("  Initializing SQLite database...")
    init_db()
    print("  Open: http://127.0.0.1:8000")
    print("  (Share your local IP with phones on same WiFi)")
    print("──────────────────────────────────────\n")
    app.run(debug=True, port=8000, host='0.0.0.0')