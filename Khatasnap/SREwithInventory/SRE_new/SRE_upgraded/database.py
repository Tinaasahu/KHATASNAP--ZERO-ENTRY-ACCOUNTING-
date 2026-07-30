"""
KhataSnap - Database Layer
Connects to Supabase PostgreSQL and manages all tables.
"""

import psycopg2
import psycopg2.extras
import os
from dotenv import load_dotenv

load_dotenv()

PROJECT_REF = 'yftguyzjktenposqfadq'
PASSWORD = os.getenv('DB_PASSWORD', 'Kh@t4Sn4p#2024!')

def get_conn():
    configs = [
    dict(host='aws-1-ap-southeast-1.pooler.supabase.com', port=5432,
         dbname='postgres', user=f'postgres.{PROJECT_REF}',
         password=PASSWORD, sslmode='require'),
    dict(host='aws-1-ap-southeast-1.pooler.supabase.com', port=6543,
         dbname='postgres', user=f'postgres.{PROJECT_REF}',
         password=PASSWORD, sslmode='require'),
]
    last_error = None
    for cfg in configs:
        try:
            conn = psycopg2.connect(**cfg)
            print(f"✅ Connected via {cfg['host']}:{cfg['port']}")
            return conn
        except Exception as e:
            print(f"⚠️  Failed {cfg['host']}:{cfg['port']} — {e}")
            last_error = e
    raise last_error


def init_db():
    """Create all tables if they don't exist."""
    conn = get_conn()
    cur  = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            id          SERIAL PRIMARY KEY,
            name        VARCHAR(100) NOT NULL UNIQUE,
            created_at  TIMESTAMP DEFAULT NOW()
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS suppliers (
            id          SERIAL PRIMARY KEY,
            name        VARCHAR(200) NOT NULL,
            phone       VARCHAR(20),
            address     TEXT,
            created_at  TIMESTAMP DEFAULT NOW()
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id              SERIAL PRIMARY KEY,
            name            VARCHAR(200) NOT NULL,
            category_id     INT REFERENCES categories(id) ON DELETE SET NULL,
            brand           VARCHAR(100),
            sku             VARCHAR(50) UNIQUE NOT NULL,
            barcode         VARCHAR(100),
            purchase_price  NUMERIC(10,2) DEFAULT 0,
            selling_price   NUMERIC(10,2) DEFAULT 0,
            mrp             NUMERIC(10,2) DEFAULT 0,
            unit_type       VARCHAR(20) DEFAULT 'pcs',
            current_qty     INT DEFAULT 0,
            min_stock       INT DEFAULT 5,
            expiry_date     DATE,
            supplier_id     INT REFERENCES suppliers(id) ON DELETE SET NULL,
            notes           TEXT,
            is_active       BOOLEAN DEFAULT TRUE,
            created_at      TIMESTAMP DEFAULT NOW(),
            updated_at      TIMESTAMP DEFAULT NOW()
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS product_aliases (
            id          SERIAL PRIMARY KEY,
            product_id  INT REFERENCES products(id) ON DELETE CASCADE,
            alias       VARCHAR(200) NOT NULL,
            created_at  TIMESTAMP DEFAULT NOW()
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS stock_logs (
            id              SERIAL PRIMARY KEY,
            transaction_id  VARCHAR(100) UNIQUE NOT NULL,
            product_id      INT REFERENCES products(id) ON DELETE SET NULL,
            product_name    VARCHAR(200),
            qty_change      INT NOT NULL,
            action_type     VARCHAR(30) NOT NULL,
            source          VARCHAR(50) NOT NULL,
            reason          TEXT,
            old_qty         INT,
            new_qty         INT,
            created_at      TIMESTAMP DEFAULT NOW()
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS calculator_transactions (
            id              SERIAL PRIMARY KEY,
            transaction_id  VARCHAR(100) UNIQUE NOT NULL,
            bill_total      NUMERIC(10,2),
            values_list     JSONB,
            created_at      TIMESTAMP DEFAULT NOW()
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS value_product_mapping (
            id              SERIAL PRIMARY KEY,
            transaction_id  VARCHAR(100),
            value           NUMERIC(10,2),
            value_index     INT,
            product_id      INT REFERENCES products(id) ON DELETE SET NULL,
            confidence      NUMERIC(4,3) DEFAULT 0,
            status          VARCHAR(20) DEFAULT 'pending',
            created_at      TIMESTAMP DEFAULT NOW()
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS processed_transactions (
            transaction_id  VARCHAR(100) PRIMARY KEY,
            source          VARCHAR(50),
            processed_at    TIMESTAMP DEFAULT NOW()
        );
    """)

    cur.execute("""
        INSERT INTO categories (name) VALUES
            ('Biscuits'), ('Snacks'), ('Beverages'), ('Dairy'),
            ('Soap & Hygiene'), ('Oil & Ghee'), ('Spices'),
            ('Stationery'), ('Frozen'), ('Other')
        ON CONFLICT (name) DO NOTHING;
    """)

    conn.commit()
    cur.close()
    conn.close()
    print("✅ All tables created successfully!")


if __name__ == '__main__':
    init_db()