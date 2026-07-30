"""
KhataSnap — Database Migration Script
Imports products from the Express backend's products.json into SQLite.
Deduplicates by name (case-insensitive).

Usage:  python migrate.py
"""

import os
import sys
import json
import sqlite3

# Add current dir to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from database import init_db, get_conn, DB_PATH

# Path to the Express backend's products
EXPRESS_PRODUCTS = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "khatasnap (5)", "khatasnap (2)", "khatasnap",
    "backend", "data", "products.json"
)


def migrate_express_products():
    """Import products from Express JSON into SQLite, skipping duplicates."""
    if not os.path.exists(EXPRESS_PRODUCTS):
        print(f"[WARN] Express products file not found: {EXPRESS_PRODUCTS}")
        return 0

    with open(EXPRESS_PRODUCTS, "r", encoding="utf-8") as f:
        products = json.load(f)

    conn = get_conn()
    imported = 0
    skipped = 0

    for p in products:
        name = p.get("name", "").strip()
        if not name:
            continue

        # Check if product already exists (case-insensitive)
        existing = conn.execute(
            "SELECT id FROM products WHERE LOWER(name) = LOWER(?)", (name,)
        ).fetchone()

        if existing:
            skipped += 1
            continue

        # Find or create category
        cat_name = p.get("category", "Other")
        conn.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", (cat_name,))
        cat_row = conn.execute("SELECT id FROM categories WHERE name=?", (cat_name,)).fetchone()
        cat_id = cat_row["id"] if cat_row else None

        # Generate SKU
        slug = ''.join(c for c in name.upper() if c.isalnum())[:6]
        sku = f"KS-{slug}-{p.get('id', '').replace('local-', '')[:3] or '000'}"

        # Check SKU uniqueness
        sku_exists = conn.execute("SELECT id FROM products WHERE sku=?", (sku,)).fetchone()
        if sku_exists:
            sku = f"KS-{slug}-M{imported:02d}"

        price = float(p.get("price", 0))
        stock = int(p.get("stock", 0))

        try:
            conn.execute("""
                INSERT INTO products
                    (name, category_id, sku, purchase_price, selling_price, mrp,
                     current_qty, min_stock, emoji)
                VALUES (?,?,?,?,?,?,?,5,'📦')
            """, (name, cat_id, sku, price, price, price, stock))
            imported += 1
        except sqlite3.IntegrityError as e:
            skipped += 1
            print(f"  [WARN] SKU conflict for '{name}': {e}")

    conn.commit()
    conn.close()

    return imported, skipped


def main():
    print("================================================")
    print("     KhataSnap Database Migration Tool           ")
    print("================================================")
    print()

    # Step 1: Initialize database (creates tables if needed)
    print("Step 1: Initializing database schema...")
    init_db()
    print(f"  [OK] Database ready at: {DB_PATH}")
    print()

    # Step 2: Import Express products
    print("Step 2: Importing products from Express backend...")
    print(f"  Source: {EXPRESS_PRODUCTS}")
    result = migrate_express_products()
    if isinstance(result, tuple):
        imported, skipped = result
        print(f"  [OK] Imported: {imported} new products")
        print(f"  [--] Skipped: {skipped} duplicates")
    else:
        print(f"  [WARN] Import returned: {result}")
    print()

    # Step 3: Summary
    conn = get_conn()
    total = conn.execute("SELECT COUNT(*) FROM products WHERE is_active=1").fetchone()[0]
    cats = conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0]
    conn.close()

    print("================================================")
    print(f"  Total products in database: {total}")
    print(f"  Total categories:           {cats}")
    print("================================================")
    print()
    print("[OK] Migration complete!")


if __name__ == "__main__":
    main()
