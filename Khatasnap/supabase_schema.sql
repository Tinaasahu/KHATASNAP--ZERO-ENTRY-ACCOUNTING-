-- =====================================================================
-- KhataSnap — Supabase PostgreSQL Database Schema
-- Organization URL: https://supabase.com/dashboard/org/wykkjlzsgcwlewlnuiji
-- Direct execution ready for Supabase Dashboard SQL Editor
-- =====================================================================

-- Enable UUID extension if needed
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 1. Categories Table
CREATE TABLE IF NOT EXISTS categories (
    id         SERIAL PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 2. Suppliers Table
CREATE TABLE IF NOT EXISTS suppliers (
    id         SERIAL PRIMARY KEY,
    name       TEXT NOT NULL,
    phone      TEXT,
    address    TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 3. Products Table
CREATE TABLE IF NOT EXISTS products (
    id               SERIAL PRIMARY KEY,
    name             TEXT NOT NULL,
    category_id      INT REFERENCES categories(id) ON DELETE SET NULL,
    brand            TEXT,
    variant_group_id TEXT,
    variant_label    TEXT,
    sku              TEXT UNIQUE NOT NULL,
    barcode          TEXT,
    purchase_price   NUMERIC(12, 2) DEFAULT 0,
    selling_price    NUMERIC(12, 2) DEFAULT 0,
    mrp              NUMERIC(12, 2) DEFAULT 0,
    unit_type        TEXT DEFAULT 'pcs',
    current_qty      INT DEFAULT 0,
    min_stock        INT DEFAULT 5,
    expiry_date      TEXT,
    supplier_id      INT REFERENCES suppliers(id) ON DELETE SET NULL,
    emoji            TEXT DEFAULT '📦',
    notes            TEXT,
    is_active        INT DEFAULT 1,
    gst_rate         NUMERIC(5, 2) DEFAULT 0,
    discount_pct     NUMERIC(5, 2) DEFAULT 0,
    created_at       TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at       TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 4. Product Audit Logs
CREATE TABLE IF NOT EXISTS product_audit_logs (
    id         SERIAL PRIMARY KEY,
    product_id INT REFERENCES products(id) ON DELETE SET NULL,
    action     TEXT NOT NULL, -- create|update|delete|bulk_update
    before_json JSONB,
    after_json  JSONB,
    source      TEXT,
    created_at  TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 5. OCR Corrections Table
CREATE TABLE IF NOT EXISTS ocr_corrections (
    id               SERIAL PRIMARY KEY,
    norm_text        TEXT,
    incorrect_value  TEXT,
    correct_value    TEXT,
    vendor           TEXT,
    invoice_layout   TEXT,
    product_id       INT REFERENCES products(id) ON DELETE SET NULL,
    variant_group_id TEXT,
    variant_label    TEXT,
    times_used       INT DEFAULT 1,
    last_used_at     TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    created_at       TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 6. Vendor Layout Memory Table
CREATE TABLE IF NOT EXISTS vendor_layout_memory (
    id               SERIAL PRIMARY KEY,
    vendor_name      TEXT NOT NULL,
    gstin            TEXT,
    layout_template  TEXT NOT NULL,
    column_positions TEXT NOT NULL,
    confidence       NUMERIC(5, 2) DEFAULT 1.0,
    last_used        TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    created_at       TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_vendor_layout UNIQUE(vendor_name, gstin)
);

-- 7. Reconciliation Flags Table
CREATE TABLE IF NOT EXISTS reconciliation_flags (
    id              SERIAL PRIMARY KEY,
    source          TEXT NOT NULL, -- ocr|calculator|manual
    ref_id          TEXT,          -- bill_id/session_id/etc
    flag_type       TEXT NOT NULL, -- mismatch|ambiguous_variant|unknown_item
    severity        TEXT DEFAULT 'info',
    payload_json    JSONB,          -- JSON blob with details + suggestions
    resolution      TEXT DEFAULT 'pending', -- pending|resolved|ignored
    resolved_by     TEXT,
    resolved_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 8. Product Aliases Table
CREATE TABLE IF NOT EXISTS product_aliases (
    id         SERIAL PRIMARY KEY,
    product_id INT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    alias      TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 9. Stock Logs Table
CREATE TABLE IF NOT EXISTS stock_logs (
    id             SERIAL PRIMARY KEY,
    transaction_id TEXT UNIQUE NOT NULL,
    product_id     INT REFERENCES products(id) ON DELETE SET NULL,
    product_name   TEXT,
    qty_change     INT NOT NULL,
    action_type    TEXT NOT NULL,
    source         TEXT NOT NULL,
    reason         TEXT,
    old_qty        INT,
    new_qty        INT,
    created_at     TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 10. Calculator Transactions Table
CREATE TABLE IF NOT EXISTS calculator_transactions (
    id             SERIAL PRIMARY KEY,
    transaction_id TEXT UNIQUE NOT NULL,
    bill_total     NUMERIC(12, 2),
    values_list    JSONB,            -- JSON array of values
    created_at     TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 11. Value Product Mapping Table
CREATE TABLE IF NOT EXISTS value_product_mapping (
    id             SERIAL PRIMARY KEY,
    transaction_id TEXT,
    value          NUMERIC(12, 2),
    value_index    INT,
    product_id     INT REFERENCES products(id) ON DELETE SET NULL,
    confidence     NUMERIC(5, 2) DEFAULT 0,
    status         TEXT DEFAULT 'pending',
    created_at     TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 12. Processed Transactions Table
CREATE TABLE IF NOT EXISTS processed_transactions (
    transaction_id TEXT PRIMARY KEY,
    source         TEXT,
    processed_at   TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 13. Completed Bills Table
CREATE TABLE IF NOT EXISTS completed_bills (
    id             SERIAL PRIMARY KEY,
    bill_no        TEXT UNIQUE NOT NULL,
    items          JSONB NOT NULL,   -- JSON array
    total_amount   NUMERIC(12, 2) NOT NULL,
    payment_mode   TEXT NOT NULL,   -- cash | upi
    source         TEXT DEFAULT 'manual',
    created_at     TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 14. Confirmed Bills Table
CREATE TABLE IF NOT EXISTS confirmed_bills (
    id                  SERIAL PRIMARY KEY,
    bill_id             TEXT UNIQUE NOT NULL,
    source              TEXT NOT NULL,
    vendor_name         TEXT,
    invoice_no          TEXT,
    invoice_date        TEXT,
    items               JSONB NOT NULL,       -- JSON array
    subtotal            NUMERIC(12, 2) DEFAULT 0,
    tax                 NUMERIC(12, 2) DEFAULT 0,
    total_amount        NUMERIC(12, 2) NOT NULL,
    payment_mode        TEXT DEFAULT 'cash',
    confirmation_status TEXT DEFAULT 'pending',
    raw_data            JSONB,                 -- JSON blob
    sre_flags           JSONB DEFAULT '[]'::jsonb, -- JSON array
    created_at          TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    confirmed_at        TIMESTAMPTZ
);

-- 15. SRE Flags Log Table
CREATE TABLE IF NOT EXISTS sre_flags_log (
    id              SERIAL PRIMARY KEY,
    bill_id         TEXT,
    flag_type       TEXT NOT NULL,
    severity        TEXT DEFAULT 'info',
    field           TEXT,
    expected_val    TEXT,
    actual_val      TEXT,
    message         TEXT,
    confidence      NUMERIC(5, 2) DEFAULT 0,
    resolution      TEXT DEFAULT 'pending',
    corrected_value TEXT,
    created_at      TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 16. Price Item Patterns Table
CREATE TABLE IF NOT EXISTS price_item_patterns (
    id                SERIAL PRIMARY KEY,
    price             INT NOT NULL,
    item_id           INT REFERENCES products(id),
    item_name         TEXT NOT NULL,
    hour_of_day       INT,
    day_of_week       INT,
    selection_count   INT DEFAULT 0,
    last_selected_at  TIMESTAMPTZ,
    created_at        TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 17. Calculator Sessions Table
CREATE TABLE IF NOT EXISTS calculator_sessions (
    id                 SERIAL PRIMARY KEY,
    entries_json       JSONB NOT NULL,
    expression         TEXT NOT NULL,
    result             NUMERIC(12, 2) NOT NULL,
    session_date       TEXT NOT NULL,
    session_time       TEXT NOT NULL,
    status             TEXT DEFAULT 'pending',
    spoken_transcript  TEXT,
    unresolved_operands JSONB DEFAULT '[]'::jsonb,
    created_at         TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 18. Inventory Deduction Log Table
CREATE TABLE IF NOT EXISTS inventory_deduction_log (
    id                SERIAL PRIMARY KEY,
    session_id        INT REFERENCES calculator_sessions(id),
    item_id           INT REFERENCES products(id),
    item_name         TEXT NOT NULL,
    qty_deducted      INT NOT NULL,
    price_at_time     NUMERIC(12, 2) NOT NULL,
    deducted_at       TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    alias_used        BOOLEAN DEFAULT FALSE
);

-- 19. Price Aliases Table
CREATE TABLE IF NOT EXISTS price_aliases (
    id              SERIAL PRIMARY KEY,
    item_id         INT NOT NULL REFERENCES products(id),
    item_name       TEXT NOT NULL,
    alias_price     NUMERIC(12, 2) NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_price_alias UNIQUE(item_id, alias_price)
);

-- 20. Staged Transactions Table
CREATE TABLE IF NOT EXISTS staged_transactions (
    txn_id           TEXT PRIMARY KEY,
    asr_buffer       JSONB DEFAULT '[]'::jsonb,
    calc_amounts     JSONB DEFAULT '[]'::jsonb,
    matched_items    JSONB DEFAULT '[]'::jsonb,
    confidence_score NUMERIC(5, 2) DEFAULT 0,
    decision         TEXT DEFAULT 'pending',
    status           TEXT DEFAULT 'pending',
    created_at       TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    committed_at     TIMESTAMPTZ,
    flagged_at       TIMESTAMPTZ
);

-- 21. Night Reconciliation Table
CREATE TABLE IF NOT EXISTS night_reconciliation (
    id               SERIAL PRIMARY KEY,
    txn_id           TEXT,
    session_id       INT REFERENCES calculator_sessions(id),
    reason           TEXT NOT NULL,
    confidence_score NUMERIC(5, 2) DEFAULT 0,
    payload_json     JSONB,
    status           TEXT DEFAULT 'pending',
    notes            TEXT,
    reviewed_at      TIMESTAMPTZ,
    created_at       TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 22. Item Co-occurrences Table
CREATE TABLE IF NOT EXISTS item_co_occurrences (
    id                SERIAL PRIMARY KEY,
    item_a_id         INT NOT NULL,
    item_b_id         INT NOT NULL,
    co_count          INT DEFAULT 1,
    last_seen_at      TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_co_occurrence UNIQUE(item_a_id, item_b_id)
);
CREATE INDEX IF NOT EXISTS idx_co_item_a ON item_co_occurrences(item_a_id);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_products_name ON products(name);
CREATE INDEX IF NOT EXISTS idx_products_barcode ON products(barcode);
CREATE INDEX IF NOT EXISTS idx_products_variant_group ON products(variant_group_id);
CREATE INDEX IF NOT EXISTS idx_stock_logs_created_at ON stock_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_ocr_corrections_norm ON ocr_corrections(norm_text);
CREATE INDEX IF NOT EXISTS idx_recon_flags_pending ON reconciliation_flags(resolution, created_at);
CREATE INDEX IF NOT EXISTS idx_staged_txn_status ON staged_transactions(status, created_at);
CREATE INDEX IF NOT EXISTS idx_night_recon_status ON night_reconciliation(status, created_at);

-- Enable Row Level Security (RLS) policies for Supabase security best practices
ALTER TABLE categories ENABLE ROW LEVEL SECURITY;
ALTER TABLE suppliers ENABLE ROW LEVEL SECURITY;
ALTER TABLE products ENABLE ROW LEVEL SECURITY;
ALTER TABLE calculator_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE completed_bills ENABLE ROW LEVEL SECURITY;
ALTER TABLE confirmed_bills ENABLE ROW LEVEL SECURITY;

-- Allow public access for anon/authenticated API service roles (customizable in Supabase Dashboard)
DROP POLICY IF EXISTS "Allow public select" ON categories;
CREATE POLICY "Allow public select" ON categories FOR SELECT USING (true);

DROP POLICY IF EXISTS "Allow public select" ON suppliers;
CREATE POLICY "Allow public select" ON suppliers FOR SELECT USING (true);

DROP POLICY IF EXISTS "Allow public select" ON products;
CREATE POLICY "Allow public select" ON products FOR SELECT USING (true);
