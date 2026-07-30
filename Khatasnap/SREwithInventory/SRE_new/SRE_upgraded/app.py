"""
KhataSnap - Main Flask Application
Full Inventory Management System for Finals
"""

from flask import Flask, jsonify, request, render_template
from flask_cors import CORS
import psycopg2.extras
from datetime import datetime
from database import get_conn, init_db
from helpers import generate_sku, generate_txn_id, calc_profit_margin, fuzzy_match
from sre_engine import (
    create_session, get_session, answer_question, clear_session,
    generate_best_question, get_next_question, should_continue_questioning,
    save_learning, get_learning_log, find_relevant_memories,
    get_session_memories, get_session_warm_start,
    find_history_seeds, check_warm_start,
    _memory_confidence, _decay_weight
)

app = Flask(__name__)
CORS(app)

# ══════════════════════════════════════════════════════════════════════════════
# UTILITY
# ══════════════════════════════════════════════════════════════════════════════

def db():
    conn = get_conn()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    return conn, cur

def now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def is_duplicate_txn(cur, txn_id):
    cur.execute("SELECT 1 FROM processed_transactions WHERE transaction_id = %s", (txn_id,))
    return cur.fetchone() is not None

def mark_txn_done(cur, txn_id, source):
    cur.execute(
        "INSERT INTO processed_transactions (transaction_id, source) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        (txn_id, source)
    )

def get_all_products_with_aliases(cur):
    cur.execute("""
        SELECT p.id, p.name,
               COALESCE(array_agg(pa.alias) FILTER (WHERE pa.alias IS NOT NULL), '{}') AS aliases
        FROM products p
        LEFT JOIN product_aliases pa ON pa.product_id = p.id
        WHERE p.is_active = TRUE
        GROUP BY p.id, p.name
    """)
    return [dict(r) for r in cur.fetchall()]

def update_stock(cur, conn, product_id, qty_change, action_type, source, reason='', txn_id=None):
    """Central stock update engine — validates, updates, logs."""
    cur.execute("SELECT id, name, current_qty FROM products WHERE id = %s AND is_active = TRUE", (product_id,))
    product = cur.fetchone()
    if not product:
        return False, "Product not found"

    old_qty = product['current_qty']
    new_qty = max(0, old_qty + qty_change)  # prevent negative stock

    cur.execute("UPDATE products SET current_qty = %s, updated_at = NOW() WHERE id = %s",
                (new_qty, product_id))

    txn = txn_id or generate_txn_id(source)
    cur.execute("""
        INSERT INTO stock_logs
            (transaction_id, product_id, product_name, qty_change, action_type, source, reason, old_qty, new_qty)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (txn, product_id, product['name'], qty_change, action_type, source, reason, old_qty, new_qty))

    conn.commit()
    return True, {'old_qty': old_qty, 'new_qty': new_qty, 'product': product['name']}

# ══════════════════════════════════════════════════════════════════════════════
# SERVE HTML PAGES
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/')
def index():
    return render_template('dashboard.html')

@app.route('/products')
def products_page():
    return render_template('products.html')

@app.route('/add-product')
def add_product_page():
    return render_template('add_product.html')

@app.route('/stock')
def stock_page():
    return render_template('stock.html')

@app.route('/history')
def history_page():
    return render_template('history.html')

@app.route('/low-stock')
def low_stock_page():
    return render_template('low_stock.html')

@app.route('/suppliers')
def suppliers_page():
    return render_template('suppliers.html')
@app.route('/test')
def test_page():
    return render_template('test.html')

@app.route('/sre')
def sre_page():
    return render_template('sre.html')

@app.route('/api-docs')
def api_docs_page():
    return render_template('api_docs.html')

@app.route('/categories')
def categories_page():
    return render_template('categories.html')

# ══════════════════════════════════════════════════════════════════════════════
# CATEGORIES API
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/api/categories', methods=['GET'])
def get_categories():
    conn, cur = db()
    cur.execute("SELECT * FROM categories ORDER BY name")
    rows = cur.fetchall()
    cur.close(); conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/categories', methods=['POST'])
def add_category():
    data = request.json
    name = data.get('name', '').strip()
    if not name:
        return jsonify({'error': 'Name is required'}), 400
    conn, cur = db()
    try:
        cur.execute("INSERT INTO categories (name) VALUES (%s) RETURNING *", (name,))
        row = cur.fetchone()
        conn.commit()
        return jsonify(dict(row)), 201
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 400
    finally:
        cur.close(); conn.close()

@app.route('/api/categories/<int:cat_id>', methods=['PUT'])
def edit_category(cat_id):
    data = request.json
    conn, cur = db()
    cur.execute("UPDATE categories SET name = %s WHERE id = %s RETURNING *",
                (data['name'], cat_id))
    row = cur.fetchone()
    conn.commit(); cur.close(); conn.close()
    return jsonify(dict(row))

@app.route('/api/categories/<int:cat_id>', methods=['DELETE'])
def delete_category(cat_id):
    conn, cur = db()
    cur.execute("DELETE FROM categories WHERE id = %s", (cat_id,))
    conn.commit(); cur.close(); conn.close()
    return jsonify({'success': True})

# ══════════════════════════════════════════════════════════════════════════════
# SUPPLIERS API
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/api/suppliers', methods=['GET'])
def get_suppliers():
    conn, cur = db()
    cur.execute("SELECT * FROM suppliers ORDER BY name")
    rows = cur.fetchall()
    cur.close(); conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/suppliers', methods=['POST'])
def add_supplier():
    data = request.json
    conn, cur = db()
    cur.execute("""
        INSERT INTO suppliers (name, phone, address)
        VALUES (%s, %s, %s) RETURNING *
    """, (data['name'], data.get('phone'), data.get('address')))
    row = cur.fetchone()
    conn.commit(); cur.close(); conn.close()
    return jsonify(dict(row)), 201

@app.route('/api/suppliers/<int:sup_id>', methods=['PUT'])
def edit_supplier(sup_id):
    data = request.json
    conn, cur = db()
    cur.execute("""
        UPDATE suppliers SET name=%s, phone=%s, address=%s WHERE id=%s RETURNING *
    """, (data['name'], data.get('phone'), data.get('address'), sup_id))
    row = cur.fetchone()
    conn.commit(); cur.close(); conn.close()
    return jsonify(dict(row))

@app.route('/api/suppliers/<int:sup_id>', methods=['DELETE'])
def delete_supplier(sup_id):
    conn, cur = db()
    cur.execute("DELETE FROM suppliers WHERE id = %s", (sup_id,))
    conn.commit(); cur.close(); conn.close()
    return jsonify({'success': True})

# ══════════════════════════════════════════════════════════════════════════════
# PRODUCTS API
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/api/products', methods=['GET'])
def get_products():
    conn, cur = db()
    cur.execute("""
        SELECT p.*,
               c.name AS category_name,
               s.name AS supplier_name,
               ROUND(((p.selling_price - p.purchase_price) / NULLIF(p.purchase_price,0)) * 100, 2) AS profit_margin,
               COALESCE(array_agg(pa.alias) FILTER (WHERE pa.alias IS NOT NULL), '{}') AS aliases
        FROM products p
        LEFT JOIN categories c ON c.id = p.category_id
        LEFT JOIN suppliers  s ON s.id = p.supplier_id
        LEFT JOIN product_aliases pa ON pa.product_id = p.id
        WHERE p.is_active = TRUE
        GROUP BY p.id, c.name, s.name
        ORDER BY p.name
    """)
    rows = cur.fetchall()
    cur.close(); conn.close()
    result = []
    for r in rows:
        d = dict(r)
        d['aliases'] = list(d['aliases']) if d['aliases'] else []
        result.append(d)
    return jsonify(result)

@app.route('/api/products', methods=['POST'])
def add_product():
    data = request.json
    name = data.get('name', '').strip()
    if not name:
        return jsonify({'error': 'Product name is required'}), 400

    conn, cur = db()

    # Duplicate name check
    cur.execute("SELECT id FROM products WHERE LOWER(name) = LOWER(%s) AND is_active = TRUE", (name,))
    if cur.fetchone():
        cur.close(); conn.close()
        return jsonify({'error': f'Product "{name}" already exists'}), 409

    sku = data.get('sku') or generate_sku(name, data.get('brand', ''))

    # Unique SKU check
    cur.execute("SELECT id FROM products WHERE sku = %s", (sku,))
    if cur.fetchone():
        sku = generate_sku(name, data.get('brand', ''))  # regenerate

    try:
        cur.execute("""
            INSERT INTO products
                (name, category_id, brand, sku, barcode, purchase_price, selling_price, mrp,
                 unit_type, current_qty, min_stock, expiry_date, supplier_id, notes)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *
        """, (
            name, data.get('category_id'), data.get('brand'), sku,
            data.get('barcode'), data.get('purchase_price', 0),
            data.get('selling_price', 0), data.get('mrp', 0),
            data.get('unit_type', 'pcs'), data.get('current_qty', 0),
            data.get('min_stock', 5), data.get('expiry_date') or None,
            data.get('supplier_id'), data.get('notes')
        ))
        product = dict(cur.fetchone())

        # Log initial stock if qty > 0
        if product['current_qty'] > 0:
            txn = generate_txn_id('ADD')
            cur.execute("""
                INSERT INTO stock_logs
                    (transaction_id, product_id, product_name, qty_change, action_type, source, old_qty, new_qty)
                VALUES (%s,%s,%s,%s,'stock_in','manual',0,%s)
            """, (txn, product['id'], product['name'], product['current_qty'], product['current_qty']))

        conn.commit()
        return jsonify(product), 201
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 400
    finally:
        cur.close(); conn.close()

@app.route('/api/products/<int:pid>', methods=['GET'])
def get_product(pid):
    conn, cur = db()
    cur.execute("""
        SELECT p.*, c.name AS category_name, s.name AS supplier_name,
               COALESCE(array_agg(pa.alias) FILTER (WHERE pa.alias IS NOT NULL), '{}') AS aliases,
               COALESCE(array_agg(pa.id)    FILTER (WHERE pa.id    IS NOT NULL), '{}') AS alias_ids
        FROM products p
        LEFT JOIN categories c ON c.id = p.category_id
        LEFT JOIN suppliers  s ON s.id = p.supplier_id
        LEFT JOIN product_aliases pa ON pa.product_id = p.id
        WHERE p.id = %s GROUP BY p.id, c.name, s.name
    """, (pid,))
    row = cur.fetchone()
    cur.close(); conn.close()
    if not row:
        return jsonify({'error': 'Product not found'}), 404
    d = dict(row)
    d['aliases']   = list(d['aliases'])   if d['aliases']   else []
    d['alias_ids'] = list(d['alias_ids']) if d['alias_ids'] else []
    return jsonify(d)

@app.route('/api/products/<int:pid>', methods=['PUT'])
def edit_product(pid):
    data = request.json
    conn, cur = db()
    cur.execute("""
        UPDATE products SET
            name=%s, category_id=%s, brand=%s, barcode=%s,
            purchase_price=%s, selling_price=%s, mrp=%s,
            unit_type=%s, min_stock=%s, expiry_date=%s,
            supplier_id=%s, notes=%s, updated_at=NOW()
        WHERE id=%s RETURNING *
    """, (
        data['name'], data.get('category_id'), data.get('brand'), data.get('barcode'),
        data.get('purchase_price', 0), data.get('selling_price', 0), data.get('mrp', 0),
        data.get('unit_type', 'pcs'), data.get('min_stock', 5),
        data.get('expiry_date') or None, data.get('supplier_id'),
        data.get('notes'), pid
    ))
    row = cur.fetchone()
    conn.commit(); cur.close(); conn.close()
    return jsonify(dict(row))

@app.route('/api/products/<int:pid>', methods=['DELETE'])
def delete_product(pid):
    conn, cur = db()
    cur.execute("UPDATE products SET is_active = FALSE WHERE id = %s", (pid,))
    conn.commit(); cur.close(); conn.close()
    return jsonify({'success': True})

# ── ALIASES ───────────────────────────────────────────────────────────────────
@app.route('/api/products/<int:pid>/aliases', methods=['POST'])
def add_alias(pid):
    alias = request.json.get('alias', '').strip()
    conn, cur = db()
    cur.execute("INSERT INTO product_aliases (product_id, alias) VALUES (%s,%s) RETURNING *",
                (pid, alias))
    row = cur.fetchone()
    conn.commit(); cur.close(); conn.close()
    return jsonify(dict(row)), 201

@app.route('/api/aliases/<int:alias_id>', methods=['DELETE'])
def delete_alias(alias_id):
    conn, cur = db()
    cur.execute("DELETE FROM product_aliases WHERE id = %s", (alias_id,))
    conn.commit(); cur.close(); conn.close()
    return jsonify({'success': True})

# ══════════════════════════════════════════════════════════════════════════════
# STOCK APIs
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/api/stock/add', methods=['POST'])
def stock_add():
    """Manually add stock."""
    data    = request.json
    pid     = data.get('product_id')
    qty     = int(data.get('qty', 0))
    reason  = data.get('reason', '')
    txn     = generate_txn_id('ADD')
    conn, cur = db()
    ok, result = update_stock(cur, conn, pid, qty, 'stock_in', 'manual', reason, txn)
    cur.close(); conn.close()
    if ok:
        return jsonify({'success': True, 'txn_id': txn, **result})
    return jsonify({'error': result}), 400

@app.route('/api/stock/remove', methods=['POST'])
def stock_remove():
    """Manually remove stock."""
    data    = request.json
    pid     = data.get('product_id')
    qty     = int(data.get('qty', 0))
    reason  = data.get('reason', '')
    txn     = generate_txn_id('REM')
    conn, cur = db()
    ok, result = update_stock(cur, conn, pid, -qty, 'stock_out', 'manual', reason, txn)
    cur.close(); conn.close()
    if ok:
        return jsonify({'success': True, 'txn_id': txn, **result})
    return jsonify({'error': result}), 400

@app.route('/api/stock/adjust', methods=['POST'])
def stock_adjust():
    """Adjust stock — damaged, expired, correction."""
    data       = request.json
    pid        = data.get('product_id')
    new_qty    = int(data.get('new_qty', 0))
    reason     = data.get('reason', 'correction')
    txn        = generate_txn_id('ADJ')
    conn, cur  = db()
    cur.execute("SELECT current_qty FROM products WHERE id = %s", (pid,))
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
# INVENTORY APIs
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/api/inventory', methods=['GET'])
def get_inventory():
    conn, cur = db()
    cur.execute("""
        SELECT p.id, p.name, p.sku, p.current_qty, p.min_stock,
               p.selling_price, p.purchase_price, p.unit_type,
               c.name AS category,
               CASE
                 WHEN p.current_qty = 0 THEN 'out'
                 WHEN p.current_qty <= p.min_stock THEN 'low'
                 ELSE 'ok'
               END AS stock_status
        FROM products p
        LEFT JOIN categories c ON c.id = p.category_id
        WHERE p.is_active = TRUE
        ORDER BY p.name
    """)
    rows = cur.fetchall()
    cur.close(); conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/inventory/logs', methods=['GET'])
def get_logs():
    limit  = request.args.get('limit', 100)
    source = request.args.get('source')
    conn, cur = db()
    if source:
        cur.execute("""
            SELECT * FROM stock_logs WHERE source = %s
            ORDER BY created_at DESC LIMIT %s
        """, (source, limit))
    else:
        cur.execute("SELECT * FROM stock_logs ORDER BY created_at DESC LIMIT %s", (limit,))
    rows = cur.fetchall()
    cur.close(); conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/inventory/low-stock', methods=['GET'])
def get_low_stock():
    conn, cur = db()
    cur.execute("""
        SELECT p.*, c.name AS category_name
        FROM products p
        LEFT JOIN categories c ON c.id = p.category_id
        WHERE p.is_active = TRUE AND p.current_qty <= p.min_stock
        ORDER BY p.current_qty ASC
    """)
    rows = cur.fetchall()
    cur.close(); conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/inventory/value', methods=['GET'])
def get_inventory_value():
    conn, cur = db()
    cur.execute("""
        SELECT
            COUNT(*) AS total_products,
            SUM(current_qty * purchase_price) AS total_purchase_value,
            SUM(current_qty * selling_price)  AS total_selling_value,
            COUNT(*) FILTER (WHERE current_qty = 0) AS out_of_stock,
            COUNT(*) FILTER (WHERE current_qty > 0 AND current_qty <= min_stock) AS low_stock,
            COUNT(*) FILTER (WHERE current_qty > min_stock) AS in_stock
        FROM products WHERE is_active = TRUE
    """)
    row = cur.fetchone()
    cur.close(); conn.close()
    return jsonify(dict(row))

# ══════════════════════════════════════════════════════════════════════════════
# CALCULATOR INTEGRATION
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/api/calculator', methods=['POST'])
def calculator_input():
    """
    Calculator team POSTs predicted items here.
    {
      "transaction_id": "CALC-XXXX",
      "bill_total": 150,
      "items": [
        { "name": "Parle-G", "qty": 3, "price": 10, "confidence": 0.95 }
      ]
    }
    confidence >= 0.75 → deduct immediately
    confidence 0.50–0.74 → deduct + flag uncertain
    confidence < 0.50 → skip
    """
    data   = request.json
    txn_id = data.get('transaction_id') or generate_txn_id('CALC')
    conn, cur = db()

    # Duplicate protection
    if is_duplicate_txn(cur, txn_id):
        cur.close(); conn.close()
        return jsonify({'error': 'Duplicate transaction', 'txn_id': txn_id}), 409

    # Store calculator transaction
    cur.execute("""
        INSERT INTO calculator_transactions (transaction_id, bill_total, values_list)
        VALUES (%s, %s, %s) ON CONFLICT DO NOTHING
    """, (txn_id, data.get('bill_total'), psycopg2.extras.Json(data.get('items', []))))

    log = []
    products   = get_all_products_with_aliases(cur)
    items_data = data.get('items', [])
    bill_total = float(data.get('bill_total') or 0)

    # ── AMOUNT-ONLY TRANSACTION (core KhataSnap use-case) ──────────────────
    # Shopkeeper enters only a total (no item names). Save entire bill_total
    # as a single pending mapping so SRE can auto-detect it at night.
    has_named_items = any(str(e.get('name', '')).strip() for e in items_data)
    if bill_total > 0 and not has_named_items:
        cur.execute("""
            INSERT INTO value_product_mapping
                (transaction_id, value, value_index, product_id, confidence, status)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (txn_id, bill_total, 0, None, 0.0, 'pending'))
        mark_txn_done(cur, txn_id, 'calculator')
        conn.commit(); cur.close(); conn.close()
        return jsonify({
            'success': True,
            'txn_id':  txn_id,
            'log': [{'status': 'pending_sre', 'amount': bill_total,
                     'message': f'Amount ₹{bill_total} saved — auto-loaded in Smart SRE for night reconciliation'}]
        })
    # ── END AMOUNT-ONLY BLOCK ───────────────────────────────────────────────

    for i, entry in enumerate(items_data):
        name       = str(entry.get('name', '')).strip()
        qty        = int(entry.get('qty', 0))
        price      = float(entry.get('price', 0))
        confidence = float(entry.get('confidence', 0))

        matched, conf = fuzzy_match(name, products)

        # Store value mapping
        cur.execute("""
            INSERT INTO value_product_mapping
                (transaction_id, value, value_index, product_id, confidence, status)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (txn_id, price, i, matched['id'] if matched else None, confidence, 'pending'))

        if confidence < 0.50:
            log.append({'status': 'skipped', 'name': name, 'confidence': confidence,
                        'message': f"'{name}' skipped — confidence too low ({confidence:.0%})"})
            continue

        if matched and qty > 0:
            src    = 'calculator-high' if confidence >= 0.75 else 'calculator-uncertain'
            status = 'applied' if confidence >= 0.75 else 'uncertain'
            ok, result = update_stock(cur, conn, matched['id'], -qty, 'stock_out', src,
                                      f"Calculator prediction (conf {confidence:.0%})", txn_id)
            cur.execute("UPDATE value_product_mapping SET status=%s WHERE transaction_id=%s AND value_index=%s",
                        (status, txn_id, i))
            log.append({'status': status, 'name': matched['name'], 'qty': qty,
                        'confidence': confidence, 'message': result.get('product', name) if ok else result})
        else:
            log.append({'status': 'not_found', 'name': name,
                        'message': f"'{name}' not found in inventory"})

    mark_txn_done(cur, txn_id, 'calculator')
    conn.commit(); cur.close(); conn.close()
    return jsonify({'success': True, 'txn_id': txn_id, 'log': log})

# ══════════════════════════════════════════════════════════════════════════════
# OCR INTEGRATION
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/api/ocr1', methods=['POST'])
def ocr1_input():
    """OCR1 — Sales bill → DEDUCT stock."""
    data   = request.json
    txn_id = data.get('transaction_id') or generate_txn_id('OCR1')
    conn, cur = db()

    if is_duplicate_txn(cur, txn_id):
        cur.close(); conn.close()
        return jsonify({'error': 'Duplicate transaction'}), 409

    products = get_all_products_with_aliases(cur)
    log = []

    for entry in data.get('items', []):
        name = str(entry.get('name', '')).strip()
        qty  = int(entry.get('qty', 0))
        matched, conf = fuzzy_match(name, products)

        if matched:
            ok, result = update_stock(cur, conn, matched['id'], -qty, 'stock_out',
                                      'ocr1', 'OCR1 sales bill', txn_id)
            log.append({'status': 'deducted' if ok else 'error',
                        'name': matched['name'], 'qty': qty, 'confidence': conf,
                        'message': f"Deducted {qty} from '{matched['name']}'"})
        else:
            log.append({'status': 'not_found', 'name': name,
                        'message': f"'{name}' not found — skipped"})

    mark_txn_done(cur, txn_id, 'ocr1')
    conn.commit(); cur.close(); conn.close()
    return jsonify({'success': True, 'txn_id': txn_id, 'log': log})

@app.route('/api/ocr2', methods=['POST'])
def ocr2_input():
    """OCR2 — Distributor bill → ADD stock."""
    data   = request.json
    txn_id = data.get('transaction_id') or generate_txn_id('OCR2')
    conn, cur = db()

    if is_duplicate_txn(cur, txn_id):
        cur.close(); conn.close()
        return jsonify({'error': 'Duplicate transaction'}), 409

    products = get_all_products_with_aliases(cur)
    log = []

    for entry in data.get('items', []):
        name = str(entry.get('name', '')).strip()
        qty  = int(entry.get('qty', 0))
        matched, conf = fuzzy_match(name, products)

        if matched:
            ok, result = update_stock(cur, conn, matched['id'], qty, 'stock_in',
                                      'ocr2', 'OCR2 distributor bill', txn_id)
            log.append({'status': 'added', 'name': matched['name'], 'qty': qty,
                        'message': f"Added {qty} to '{matched['name']}'"})
        else:
            # Auto-create new product
            sku = generate_sku(name)
            cur.execute("""
                INSERT INTO products (name, sku, current_qty, min_stock)
                VALUES (%s, %s, %s, 5) RETURNING id, name
            """, (name, sku, qty))
            new_p = cur.fetchone()
            txn2  = generate_txn_id('OCR2')
            cur.execute("""
                INSERT INTO stock_logs
                    (transaction_id, product_id, product_name, qty_change, action_type, source, old_qty, new_qty)
                VALUES (%s,%s,%s,%s,'stock_in','ocr2',0,%s)
            """, (txn2, new_p['id'], new_p['name'], qty, qty))
            log.append({'status': 'created', 'name': name, 'qty': qty,
                        'message': f"New product '{name}' created with qty {qty}"})

    mark_txn_done(cur, txn_id, 'ocr2')
    conn.commit(); cur.close(); conn.close()
    return jsonify({'success': True, 'txn_id': txn_id, 'log': log})

# ══════════════════════════════════════════════════════════════════════════════
# VOICE / ASR INTEGRATION
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/api/asr', methods=['POST'])
def asr_input():
    """
    ASR/Voice sale.
    Single item: { "name": "Parle-G", "qty": 5 }
    OR batch: { "items": [{ "name": "Parle-G", "qty": 5 }] }
    """
    data     = request.json
    txn_id   = data.get('transaction_id') or generate_txn_id('ASR')
    conn, cur = db()

    if is_duplicate_txn(cur, txn_id):
        cur.close(); conn.close()
        return jsonify({'error': 'Duplicate transaction'}), 409

    products = get_all_products_with_aliases(cur)
    items    = data.get('items') or [{'name': data.get('name'), 'qty': data.get('qty', 1)}]
    log      = []

    for entry in items:
        name = str(entry.get('name', '')).strip()
        qty  = int(entry.get('qty', 1))
        matched, conf = fuzzy_match(name, products)

        if matched:
            ok, result = update_stock(cur, conn, matched['id'], -qty, 'stock_out',
                                      'voice', 'Voice sale', txn_id)
            log.append({'status': 'deducted', 'name': matched['name'], 'qty': qty,
                        'confidence': conf, 'message': f"Sold {qty} × '{matched['name']}'"})
        else:
            log.append({'status': 'not_found', 'name': name,
                        'message': f"'{name}' not found in inventory"})

    mark_txn_done(cur, txn_id, 'asr')
    conn.commit(); cur.close(); conn.close()
    return jsonify({'success': True, 'txn_id': txn_id, 'log': log})

# ══════════════════════════════════════════════════════════════════════════════
# SRE — SMART RECONCILIATION ENGINE (Full Bayesian + Decision Tree)
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/sre/smart')
def sre_smart_page():
    return render_template('sre_smart.html')


@app.route('/api/sre/smart/start', methods=['POST'])
def sre_smart_start():
    """
    Start a smart reconciliation session.
    Loads all active products from DB, finds combinations, returns first question.
    Body: { "mismatch_amount": 150.00 }
    """
    data            = request.json
    mismatch_amount = data.get('mismatch_amount')

    if not mismatch_amount or float(mismatch_amount) <= 0:
        return jsonify({'error': 'Valid mismatch_amount is required'}), 400

    conn, cur = db()
    cur.execute("""
        SELECT p.id, p.name, p.selling_price, p.current_qty,
               COALESCE(c.name, 'Unknown') AS category
        FROM products p
        LEFT JOIN categories c ON c.id = p.category_id
        WHERE p.is_active = TRUE AND p.selling_price > 0
        ORDER BY p.name
    """)
    products = [dict(r) for r in cur.fetchall()]
    cur.close(); conn.close()

    if not products:
        return jsonify({'error': 'No active products found in database'}), 404

    session_id, session = create_session(products, float(mismatch_amount))
    total_combos = len(session['combos'])

    if total_combos == 0:
        return jsonify({
            'session_id':   session_id,
            'status':       'NO_MATCH',
            'message':      f'No product combination matches Rs.{mismatch_amount}',
            'total_combos': 0
        })

    if total_combos == 1:
        return jsonify({
            'session_id':    session_id,
            'status':        'SOLVED',
            'result':        session['combos'][0],
            'total_combos':  1,
            'probabilities': session['probabilities'],
            'warm_start':    False
        })

    # Warm Start: skip questions if memory is confident enough
    warm = check_warm_start(float(mismatch_amount), session['combos'])
    if warm:
        return jsonify({
            'session_id':    session_id,
            'status':        'SOLVED',
            'result':        warm['combo'],
            'total_combos':  total_combos,
            'probabilities': session['probabilities'],
            'warm_start':    True,
            'warm_reason':   warm['reason']
        })

    question = generate_best_question(
        session['combos'], session['products'],
        session['asked_products'], session['asked_types'],
        q_number=1,
        relevant_memories=session.get('relevant_memories'),
        history_seeds=session.get('history_seeds'),
        cooccurrence=session.get('cooccurrence')
    )
    return jsonify({
        'session_id':    session_id,
        'status':        'QUESTIONING',
        'total_combos':  total_combos,
        'probabilities': session['probabilities'],
        'question':      question,
        'history_seeds': session.get('history_seeds', [])
    })


@app.route('/api/sre/smart/answer', methods=['POST'])
def sre_smart_answer():
    """
    Answer a yes/no question to narrow down combinations.
    Body: { "session_id": "SRE-XXX", "product": "Parle-G", "answer": "yes" }
    """
    data          = request.json
    session_id    = data.get('session_id')
    question_dict = data.get('question_dict')  # full question object
    product       = data.get('product')         # legacy fallback
    answer        = data.get('answer', '').lower()

    if not session_id or answer not in ('yes', 'no'):
        return jsonify({'error': 'session_id and answer (yes/no) are required'}), 400

    # Build question_dict from legacy product field if needed
    if not question_dict and product:
        question_dict = {'type': 'product', 'product': product, 'question': f'Was "{product}" part of the mismatch?'}
    if not question_dict:
        return jsonify({'error': 'question_dict or product is required'}), 400

    session, err = answer_question(session_id, question_dict, answer)
    if err:
        return jsonify({'error': err}), 404

    remaining  = len(session['combos'])
    keep_going = should_continue_questioning(session)

    if remaining == 0:
        return jsonify({
            'session_id':     session_id,
            'status':         'NO_MATCH',
            'message':        'No combinations remaining after filtering.',
            'question_count': session['question_count'],
            'history':        session['question_history']
        })

    if not keep_going:
        # Return best guess (highest probability combo)
        best_combo = session['combos'][0] if session['combos'] else []
        return jsonify({
            'session_id':     session_id,
            'status':         'SOLVED',
            'result':         best_combo,
            'probabilities':  session['probabilities'],
            'question_count': session['question_count'],
            'history':        session['question_history'],
            'remaining_combos': remaining
        })

    next_q = get_next_question(session_id)
    return jsonify({
        'session_id':        session_id,
        'status':            'QUESTIONING',
        'remaining_combos':  remaining,
        'probabilities':     session['probabilities'],
        'question':          next_q,
        'question_count':    session['question_count'],
        'history':           session['question_history']
    })


@app.route('/api/sre/smart/session/<session_id>', methods=['GET'])
def sre_smart_session(session_id):
    """Get current state of a reconciliation session."""
    session = get_session(session_id)
    if not session:
        return jsonify({'error': 'Session not found'}), 404
    return jsonify({
        'session_id':       session_id,
        'mismatch_amount':  session['mismatch_amount'],
        'remaining_combos': len(session['combos']),
        'probabilities':    session['probabilities'],
        'question_count':   session['question_count'],
        'created_at':       session['created_at']
    })


@app.route('/api/sre/smart/learn', methods=['POST'])
def sre_smart_learn():
    """
    Save a confirmed correct result with rich metadata.
    Body: {
      "items": ["Parle-G"],
      "amount": 20.00,
      "session_id": "SRE-XXX",           -- optional, used to pull question_history
      "question_history": [...],          -- optional Q&A path
      "final_probs": [...],               -- optional final probability snapshot
      "product_details": [...]            -- optional [{name, selling_price, category}]
    }
    """
    data            = request.json
    items           = data.get('items', [])
    amount          = data.get('amount', 0)
    session_id      = data.get('session_id')
    question_history= data.get('question_history', [])
    final_probs     = data.get('final_probs', [])
    product_details = data.get('product_details', [])

    if not items:
        return jsonify({'error': 'items list is required'}), 400
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        amount = 0.0
    if amount <= 0:
        return jsonify({'error': 'valid amount > 0 is required'}), 400

    # Pull question_history from live session if available and not provided
    if not question_history and session_id:
        from sre_engine import get_session as _gs
        sess = _gs(session_id)
        if sess:
            question_history = sess.get('question_history', [])
            if not product_details:
                product_details = sess.get('products', [])
            if not final_probs:
                final_probs = sess.get('probabilities', [])

    entry = save_learning(
        items, float(amount),
        question_history=question_history,
        final_probs=final_probs,
        product_details=product_details
    )
    return jsonify({'success': True, 'entry': entry, 'total_learnings': len(get_learning_log())})


@app.route('/api/sre/smart/learning-log', methods=['GET'])
def sre_smart_learning_log():
    """Get full learning log sorted by frequency with summary stats."""
    from sre_engine import get_memory_stats
    log   = get_learning_log()
    stats = get_memory_stats()
    return jsonify({
        'learning_log':        log,
        'total':               stats['total'],
        'total_sessions':      stats['total_sessions'],
        'top_items':           stats['top_items'],
        'avg_confidence':      stats['avg_confidence'],
        'avg_frequency':       stats['avg_frequency'],
        'warm_start_eligible': stats['warm_start_eligible'],
    })


@app.route('/api/sre/smart/session-memories/<session_id>', methods=['GET'])
def sre_session_memories(session_id):
    """Get pattern-matched past memories relevant to this session."""
    memories = get_session_memories(session_id)
    return jsonify({'memories': memories, 'total': len(memories)})


@app.route('/api/sre/smart/reset', methods=['POST'])
def sre_smart_reset():
    """Clear a session."""
    session_id = request.json.get('session_id')
    if not session_id:
        return jsonify({'error': 'session_id required'}), 400
    clear_session(session_id)
    return jsonify({'success': True})


@app.route('/api/sre/smart/pending-mismatches', methods=['GET'])
def sre_pending_mismatches():
    """
    Auto-detect pending/uncertain transactions that need reconciliation.
    Covers three cases:
      1. value_product_mapping rows with status = 'pending' or 'uncertain'
         (items the calculator could not identify confidently)
      2. Amount-only transactions saved by the calculator with no item names
      3. stock_logs rows with source = 'calculator-uncertain' from last 7 days
    Returns a list of pending transactions with their mismatch amounts,
    ready for auto-population in the Smart SRE page.
    """
    conn, cur = db()
    from collections import defaultdict

    # ── 1. Fetch all pending/uncertain value mappings ──────────────────────
    cur.execute("""
        SELECT
            vm.transaction_id,
            vm.value,
            vm.value_index,
            vm.confidence,
            vm.status,
            vm.created_at,
            ct.bill_total,
            ct.values_list,
            p.name AS matched_product_name
        FROM value_product_mapping vm
        LEFT JOIN calculator_transactions ct ON ct.transaction_id = vm.transaction_id
        LEFT JOIN products p ON p.id = vm.product_id
        WHERE vm.status IN ('pending', 'uncertain')
        ORDER BY vm.created_at DESC
        LIMIT 100
    """)
    raw_mappings = [dict(r) for r in cur.fetchall()]

    # Group by transaction_id
    txn_groups = defaultdict(list)
    for row in raw_mappings:
        txn_groups[row['transaction_id']].append(row)

    pending_list = []
    for txn_id, items in txn_groups.items():
        mismatch_total = sum(float(i['value'] or 0) for i in items)
        bill_total     = float(items[0]['bill_total'] or 0) if items[0]['bill_total'] else None
        created_at     = items[0]['created_at']

        item_descriptions = []
        for i in items:
            desc = {
                'value':       float(i['value'] or 0),
                'status':      i['status'],
                'confidence':  float(i['confidence'] or 0),
                'product':     i['matched_product_name'],
                'value_index': i['value_index']
            }
            # Try to get original item name from values_list JSON
            vl  = i['values_list'] if isinstance(i.get('values_list'), list) else []
            idx = i['value_index']
            if idx is not None and vl and 0 <= idx < len(vl):
                desc['original_name'] = vl[idx].get('name', '')
                desc['original_qty']  = vl[idx].get('qty', 1)
            item_descriptions.append(desc)

        pending_list.append({
            'transaction_id':  txn_id,
            'mismatch_amount': round(mismatch_total, 2),
            'bill_total':      bill_total,
            'item_count':      len(items),
            'items':           item_descriptions,
            'created_at':      str(created_at),
            'source':          'calculator'
        })

    # ── 2. Detect stock_logs with calculator-uncertain (last 7 days) ───────
    cur.execute("""
        SELECT
            sl.transaction_id,
            sl.product_name,
            ABS(sl.qty_change) AS qty,
            sl.created_at,
            p.selling_price
        FROM stock_logs sl
        LEFT JOIN products p ON p.id = sl.product_id
        WHERE sl.source = 'calculator-uncertain'
          AND sl.created_at > NOW() - INTERVAL '7 days'
        ORDER BY sl.created_at DESC
        LIMIT 50
    """)
    uncertain_logs = [dict(r) for r in cur.fetchall()]

    existing_ids = {p['transaction_id'] for p in pending_list}
    uncertain_txns = defaultdict(list)
    for row in uncertain_logs:
        uncertain_txns[row['transaction_id']].append(row)

    for txn_id, items in uncertain_txns.items():
        if txn_id in existing_ids:
            continue
        mismatch_total = sum(
            float(i['qty'] or 0) * float(i['selling_price'] or 0) for i in items
        )
        if mismatch_total <= 0:
            continue
        pending_list.append({
            'transaction_id':  txn_id,
            'mismatch_amount': round(mismatch_total, 2),
            'bill_total':      None,
            'item_count':      len(items),
            'items': [{
                'value':         float(i['qty'] or 0) * float(i['selling_price'] or 0),
                'status':        'uncertain',
                'confidence':    0,
                'product':       i['product_name'],
                'original_name': i['product_name'],
                'original_qty':  int(i['qty'] or 0)
            } for i in items],
            'created_at': str(items[0]['created_at']),
            'source':     'calculator-uncertain'
        })

    cur.close(); conn.close()

    # Sort by most recent first
    pending_list.sort(key=lambda x: x['created_at'], reverse=True)
    total_mismatch = sum(p['mismatch_amount'] for p in pending_list)

    return jsonify({
        'pending':        pending_list,
        'total_count':    len(pending_list),
        'total_mismatch': round(total_mismatch, 2)
    })


@app.route('/api/sre/reconcile', methods=['POST'])
def sre_reconcile():
    """
    Night reconciliation — correct inventory mismatches.
    {
      "corrections": [
        { "product_id": 1, "correct_qty": 45, "reason": "physical count" }
      ]
    }
    """
    data    = request.json
    txn_id  = generate_txn_id('SRE')
    conn, cur = db()
    log     = []

    for correction in data.get('corrections', []):
        pid       = correction.get('product_id')
        new_qty   = int(correction.get('correct_qty', 0))
        reason    = correction.get('reason', 'SRE reconciliation')
        cur.execute("SELECT current_qty FROM products WHERE id = %s", (pid,))
        row = cur.fetchone()
        if row:
            diff = new_qty - row['current_qty']
            ok, result = update_stock(cur, conn, pid, diff, 'adjustment', 'sre', reason, generate_txn_id('SRE'))
            log.append({'product_id': pid, 'old_qty': row['current_qty'],
                        'new_qty': new_qty, 'status': 'corrected'})

    conn.commit(); cur.close(); conn.close()
    return jsonify({'success': True, 'txn_id': txn_id, 'log': log})

@app.route('/api/sre/confirm-mapping', methods=['POST'])
def sre_confirm_mapping():
    """
    SRE confirms/corrects calculator value → product mapping.
    { "transaction_id": "CALC-XXX", "value_index": 0, "product_id": 5, "action": "confirm|correct|ignore" }
    """
    data   = request.json
    txn_id = data.get('transaction_id')
    idx    = data.get('value_index')
    pid    = data.get('product_id')
    action = data.get('action', 'confirm')
    conn, cur = db()

    cur.execute("""
        UPDATE value_product_mapping SET product_id=%s, status=%s
        WHERE transaction_id=%s AND value_index=%s
    """, (pid, action, txn_id, idx))

    conn.commit(); cur.close(); conn.close()
    return jsonify({'success': True})

@app.route('/api/sre/conflicts', methods=['GET'])
def get_conflicts():
    """Get all uncertain/pending mappings that need SRE review."""
    conn, cur = db()
    cur.execute("""
        SELECT vm.*, p.name AS product_name, ct.bill_total
        FROM value_product_mapping vm
        LEFT JOIN products p ON p.id = vm.product_id
        LEFT JOIN calculator_transactions ct ON ct.transaction_id = vm.transaction_id
        WHERE vm.status IN ('pending', 'uncertain')
        ORDER BY vm.created_at DESC
        LIMIT 50
    """)
    rows = cur.fetchall()
    cur.close(); conn.close()
    return jsonify([dict(r) for r in rows])


# ══════════════════════════════════════════════════════════════════════════════
# DASHBOARD STATS
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/api/dashboard', methods=['GET'])
def dashboard():
    conn, cur = db()

    cur.execute("""
        SELECT
            COUNT(*) AS total_products,
            SUM(current_qty * purchase_price) AS total_purchase_value,
            SUM(current_qty * selling_price)  AS total_selling_value,
            COUNT(*) FILTER (WHERE current_qty = 0) AS out_of_stock,
            COUNT(*) FILTER (WHERE current_qty > 0 AND current_qty <= min_stock) AS low_stock,
            COUNT(*) FILTER (WHERE current_qty > min_stock) AS in_stock
        FROM products WHERE is_active = TRUE
    """)
    stats = dict(cur.fetchone())

    cur.execute("""
        SELECT p.name, p.current_qty, p.min_stock, c.name AS category
        FROM products p LEFT JOIN categories c ON c.id = p.category_id
        WHERE p.is_active = TRUE AND p.current_qty <= p.min_stock
        ORDER BY p.current_qty ASC LIMIT 5
    """)
    stats['low_stock_items'] = [dict(r) for r in cur.fetchall()]

    cur.execute("""
        SELECT sl.product_name, sl.qty_change, sl.action_type, sl.source, sl.created_at
        FROM stock_logs sl ORDER BY sl.created_at DESC LIMIT 10
    """)
    stats['recent_activity'] = [dict(r) for r in cur.fetchall()]

    cur.close(); conn.close()
    return jsonify(stats)


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    print("\n✅  KhataSnap Inventory Server (Finals)")
    print("─────────────────────────────────────────")
    print("  Initializing database...")
    init_db()
    print("  Open: http://127.0.0.1:8000")
    print("─────────────────────────────────────────\n")
    app.run(debug=True, port=8000, host='127.0.0.1')