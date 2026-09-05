import sqlite3
import json
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "khatasnap.db")
OUTPUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "supabase_seed_data.sql")

def escape_sql_value(val, col_name=None):
    if val is None:
        return "NULL"
    if isinstance(val, bool) or col_name == 'alias_used':
        return "TRUE" if bool(val) else "FALSE"
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, str):
        val_str = val.replace("'", "''")
        return f"'{val_str}'"
    val_str = str(val).replace("'", "''")
    return f"'{val_str}'"

def export_db():
    if not os.path.exists(DB_PATH):
        print(f"Error: {DB_PATH} not found.")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Fetch list of user tables
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
    tables = [row['name'] for row in cur.fetchall()]

    sql_statements = [
        "-- =====================================================================",
        "-- KhataSnap — Supabase Data Seed File",
        "-- Generated automatically from local khatasnap.db",
        "-- Organization: wykkjlzsgcwlewlnuiji",
        "-- =====================================================================\n",
        "SET session_replication_role = 'replica';\n"
    ]

    for table in tables:
        cur.execute(f"SELECT * FROM {table};")
        rows = cur.fetchall()
        if not rows:
            continue

        columns = [description[0] for description in cur.description]
        col_list = ", ".join(columns)

        sql_statements.append(f"-- Data for table: {table}")
        for row in rows:
            values = [escape_sql_value(row[col], col) for col in columns]
            val_list = ", ".join(values)
            sql_statements.append(f"INSERT INTO {table} ({col_list}) VALUES ({val_list}) ON CONFLICT DO NOTHING;")
        sql_statements.append("")

    sql_statements.append("SET session_replication_role = 'origin';")
    
    # Add sequence setval statements for serial auto-increment columns
    seq_tables = ['categories', 'suppliers', 'products', 'product_audit_logs', 'ocr_corrections', 
                  'vendor_layout_memory', 'reconciliation_flags', 'product_aliases', 'stock_logs', 
                  'calculator_transactions', 'value_product_mapping', 'completed_bills', 'confirmed_bills', 
                  'sre_flags_log', 'price_item_patterns', 'calculator_sessions', 'inventory_deduction_log', 
                  'price_aliases', 'night_reconciliation', 'item_co_occurrences']
    
    sql_statements.append("\n-- Sync PostgreSQL Serial Sequences")
    for tbl in seq_tables:
        sql_statements.append(f"SELECT setval(pg_get_serial_sequence('{tbl}', 'id'), COALESCE((SELECT MAX(id) FROM {tbl}), 1));")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(sql_statements))

    print(f"[OK] Supabase seed file successfully generated at {OUTPUT_FILE}")

if __name__ == "__main__":
    export_db()
