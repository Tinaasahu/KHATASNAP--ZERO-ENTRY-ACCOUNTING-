"""
KhataSnap — SQLite Database Layer
All data stored locally in khatasnap.db — no internet required.
"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "khatasnap.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row          # rows behave like dicts
    conn.execute("PRAGMA journal_mode=WAL") # safe concurrent writes
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_conn()
    cur  = conn.cursor()

    cur.executescript("""
        CREATE TABLE IF NOT EXISTS categories (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT NOT NULL UNIQUE,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS suppliers (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT NOT NULL,
            phone      TEXT,
            address    TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS products (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            name           TEXT NOT NULL,
            category_id    INTEGER REFERENCES categories(id) ON DELETE SET NULL,
            brand          TEXT,
            variant_group_id TEXT,
            variant_label  TEXT,
            sku            TEXT UNIQUE NOT NULL,
            barcode        TEXT,
            purchase_price REAL DEFAULT 0,
            selling_price  REAL DEFAULT 0,
            mrp            REAL DEFAULT 0,
            unit_type      TEXT DEFAULT 'pcs',
            current_qty    INTEGER DEFAULT 0,
            min_stock      INTEGER DEFAULT 5,
            expiry_date    TEXT,
            supplier_id    INTEGER REFERENCES suppliers(id) ON DELETE SET NULL,
            emoji          TEXT DEFAULT '📦',
            notes          TEXT,
            is_active      INTEGER DEFAULT 1,
            created_at     TEXT DEFAULT (datetime('now')),
            updated_at     TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS product_audit_logs (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER REFERENCES products(id) ON DELETE SET NULL,
            action     TEXT NOT NULL, -- create|update|delete|bulk_update
            before_json TEXT,
            after_json  TEXT,
            source      TEXT,
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS ocr_corrections (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            norm_text     TEXT NOT NULL,
            product_id    INTEGER REFERENCES products(id) ON DELETE SET NULL,
            variant_group_id TEXT,
            variant_label TEXT,
            times_used    INTEGER DEFAULT 1,
            last_used_at  TEXT DEFAULT (datetime('now')),
            created_at    TEXT DEFAULT (datetime('now')),
            UNIQUE(norm_text, product_id)
        );

        CREATE TABLE IF NOT EXISTS reconciliation_flags (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            source          TEXT NOT NULL, -- ocr|calculator|manual
            ref_id          TEXT,          -- bill_id/session_id/etc
            flag_type       TEXT NOT NULL, -- mismatch|ambiguous_variant|unknown_item
            severity        TEXT DEFAULT 'info',
            payload_json    TEXT,          -- JSON blob with details + suggestions
            resolution      TEXT DEFAULT 'pending', -- pending|resolved|ignored
            resolved_by     TEXT,
            resolved_at     TEXT,
            created_at      TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS product_aliases (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
            alias      TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS stock_logs (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            transaction_id TEXT UNIQUE NOT NULL,
            product_id     INTEGER REFERENCES products(id) ON DELETE SET NULL,
            product_name   TEXT,
            qty_change     INTEGER NOT NULL,
            action_type    TEXT NOT NULL,
            source         TEXT NOT NULL,
            reason         TEXT,
            old_qty        INTEGER,
            new_qty        INTEGER,
            created_at     TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS calculator_transactions (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            transaction_id TEXT UNIQUE NOT NULL,
            bill_total     REAL,
            values_list    TEXT,            -- JSON stored as text
            created_at     TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS value_product_mapping (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            transaction_id TEXT,
            value          REAL,
            value_index    INTEGER,
            product_id     INTEGER REFERENCES products(id) ON DELETE SET NULL,
            confidence     REAL DEFAULT 0,
            status         TEXT DEFAULT 'pending',
            created_at     TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS processed_transactions (
            transaction_id TEXT PRIMARY KEY,
            source         TEXT,
            processed_at   TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS completed_bills (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            bill_no        TEXT UNIQUE NOT NULL,
            items          TEXT NOT NULL,   -- JSON
            total_amount   REAL NOT NULL,
            payment_mode   TEXT NOT NULL,   -- cash | upi
            source         TEXT DEFAULT 'manual',
            created_at     TEXT DEFAULT (datetime('now'))
        );

        -- ─── Unified tables added by integration layer ───────────────

        CREATE TABLE IF NOT EXISTS confirmed_bills (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            bill_id             TEXT UNIQUE NOT NULL,
            source              TEXT NOT NULL,
            vendor_name         TEXT,
            invoice_no          TEXT,
            invoice_date        TEXT,
            items               TEXT NOT NULL,       -- JSON array
            subtotal            REAL DEFAULT 0,
            tax                 REAL DEFAULT 0,
            total_amount        REAL NOT NULL,
            payment_mode        TEXT DEFAULT 'cash',
            confirmation_status TEXT DEFAULT 'pending',
            raw_data            TEXT,                 -- JSON blob
            sre_flags           TEXT DEFAULT '[]',    -- JSON array
            created_at          TEXT DEFAULT (datetime('now')),
            confirmed_at        TEXT
        );

        CREATE TABLE IF NOT EXISTS sre_flags_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            bill_id         TEXT,
            flag_type       TEXT NOT NULL,
            severity        TEXT DEFAULT 'info',
            field           TEXT,
            expected_val    TEXT,
            actual_val      TEXT,
            message         TEXT,
            confidence      REAL DEFAULT 0,
            resolution      TEXT DEFAULT 'pending',
            corrected_value TEXT,
            created_at      TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS price_item_patterns (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            price             INTEGER NOT NULL,
            item_id           INTEGER REFERENCES products(id),
            item_name         TEXT NOT NULL,
            hour_of_day       INTEGER,
            day_of_week       INTEGER,
            selection_count   INTEGER DEFAULT 0,
            last_selected_at  TEXT,
            created_at        TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS calculator_sessions (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            entries_json      TEXT NOT NULL,
            expression        TEXT NOT NULL,
            result            INTEGER NOT NULL,
            session_date      TEXT NOT NULL,
            session_time      TEXT NOT NULL,
            status            TEXT DEFAULT 'pending' CHECK(status IN ('pending','confirmed','cancelled')),
            spoken_transcript TEXT,
            created_at        TEXT DEFAULT (datetime('now'))
        );


        CREATE TABLE IF NOT EXISTS inventory_deduction_log (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id        INTEGER REFERENCES calculator_sessions(id),
            item_id           INTEGER REFERENCES products(id),
            item_name         TEXT NOT NULL,
            qty_deducted      INTEGER NOT NULL,
            price_at_time     INTEGER NOT NULL,
            deducted_at       TEXT DEFAULT (datetime('now')),
            alias_used        BOOLEAN DEFAULT FALSE
        );

        CREATE TABLE IF NOT EXISTS price_aliases (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id         INTEGER NOT NULL REFERENCES products(id),
            item_name       TEXT NOT NULL,
            alias_price     INTEGER NOT NULL,
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(item_id, alias_price)
        );

        CREATE INDEX IF NOT EXISTS idx_products_name ON products(name);
        CREATE INDEX IF NOT EXISTS idx_products_barcode ON products(barcode);
        CREATE INDEX IF NOT EXISTS idx_stock_logs_created_at ON stock_logs(created_at);
        CREATE INDEX IF NOT EXISTS idx_ocr_corrections_norm ON ocr_corrections(norm_text);
        CREATE INDEX IF NOT EXISTS idx_recon_flags_pending ON reconciliation_flags(resolution, created_at);
    """)

    # Soft migrations
    # Products: add business fields used by shopkeeper dashboard & inventory editor
    try:
        conn.execute("ALTER TABLE products ADD COLUMN gst_rate REAL DEFAULT 0")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE products ADD COLUMN discount_pct REAL DEFAULT 0")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE products ADD COLUMN variant_group_id TEXT")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE products ADD COLUMN variant_label TEXT")
    except Exception:
        pass
    # Indexes that depend on soft-migrated columns
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_products_variant_group ON products(variant_group_id)")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE calculator_sessions ADD COLUMN spoken_transcript TEXT")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE inventory_deduction_log ADD COLUMN alias_used BOOLEAN DEFAULT FALSE")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE calculator_sessions ADD COLUMN unresolved_operands TEXT DEFAULT '[]'")
    except Exception:
        pass

    # Seed default categories
    cats = [
        'Biscuits', 'Chips', 'Beverages', 'Chocolates', 'Noodles',
        'Snacks', 'Dairy', 'Soap & Hygiene', 'Oil & Ghee',
        'Spices', 'Stationery', 'Other'
    ]
    for c in cats:
        cur.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", (c,))

    # Seed demo products matching the mobile UI
    demo_products = [
        ('Parle G',     'Biscuits',  10,  10, 100, '🍪'),
        ('Maggi',       'Noodles',   12,  12,  50, '🍜'),
        ('Coca Cola',   'Beverages', 40,  40,  30, '🥤'),
        ('Lays',        'Chips',     20,  20,  75, '🥔'),
        ('Bourbon',     'Biscuits',  15,  15,   8, '🍫'),
        ('Sprite',      'Beverages', 40,  40,   0, '🫧'),
        ('Kurkure',     'Chips',     20,  20,  60, '🌽'),
        ('Good Day',    'Biscuits',  25,  25,  45, '🍪'),
        ('Dairy Milk',  'Chocolates',20,  20,  35, '🍫'),
        ('Frooti',      'Beverages', 15,  15,  55, '🥭'),
        ('Hide & Seek', 'Biscuits',  30,  30,  28, '🍪'),
        ('Bhujia',      'Snacks',    30,  30,  40, '🫙'),
        ('Nimbooz',     'Beverages', 20,  20,  22, '🍋'),
        ('Monaco',      'Biscuits',  10,  10,  90, '🫓'),
        ('Choco Pie',   'Chocolates',35,  35,  18, '🍫'),
    ]

    for name, cat, buy, sell, qty, emoji in demo_products:
        cur.execute("SELECT id FROM categories WHERE name=?", (cat,))
        cat_row = cur.fetchone()
        cat_id  = cat_row['id'] if cat_row else None
        slug    = ''.join(c for c in name.upper() if c.isalnum())[:6]
        sku     = f"KS-{slug}-001"
        cur.execute("""
            INSERT OR IGNORE INTO products
                (name, category_id, sku, purchase_price, selling_price, mrp,
                 current_qty, min_stock, emoji)
            VALUES (?,?,?,?,?,?,?,5,?)
        """, (name, cat_id, sku, buy, sell, sell, qty, emoji))

    # Seed default suppliers
    default_suppliers = [
        ('Raj Traders',      '+91 98765 43210', 'Gorakhpur Market, UP'),
        ('Sharma Dist.',     '+91 91234 56789', 'Civil Lines, Lucknow'),
        ('Kapoor Wholesale', '+91 99887 65432', 'Varanasi Mandi, UP'),
        ('Singh Suppliers',  '+91 97654 32109', 'Kanpur Road, UP'),
        ('Metro Traders',    '+91 96543 21098', 'Allahabad, UP'),
        ('Gupta & Sons',     '+91 95432 10987', 'Gorakhpur, UP'),
    ]
    for s in default_suppliers:
        cur.execute("INSERT OR IGNORE INTO suppliers (name,phone,address) VALUES (?,?,?)", s)

    conn.commit()
    cur.close()
    conn.close()
    print("[OK] SQLite database ready at", DB_PATH)


if __name__ == '__main__':
    init_db()