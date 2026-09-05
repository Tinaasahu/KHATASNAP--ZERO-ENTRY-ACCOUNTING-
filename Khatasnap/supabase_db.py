"""
KhataSnap — Supabase PostgreSQL Database Adapter
Enables seamless switching between local SQLite (khatasnap.db) and Supabase PostgreSQL.
"""
import os
import sqlite3

SUPABASE_DB_URL = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False


def get_connection():
    """
    Returns a database connection.
    If SUPABASE_DB_URL is set, connects to Supabase PostgreSQL.
    Otherwise, defaults to local SQLite (khatasnap.db).
    """
    if SUPABASE_DB_URL and HAS_PSYCOPG2:
        conn = psycopg2.connect(SUPABASE_DB_URL, cursor_factory=RealDictCursor)
        conn.autocommit = True
        return conn, 'postgresql'
    
    # Fallback to local SQLite
    db_path = os.getenv("DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "khatasnap.db"))
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn, 'sqlite'
