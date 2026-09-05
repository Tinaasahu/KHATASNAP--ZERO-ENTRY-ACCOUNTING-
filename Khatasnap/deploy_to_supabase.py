import psycopg2
import urllib.parse
import os
import sys

# Default DB Password provided by user
DB_PASSWORD = os.getenv("SUPABASE_DB_PASSWORD", "khatasnap@2810")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCHEMA_FILE = os.path.join(BASE_DIR, "supabase_schema.sql")
PART1_FILE = os.path.join(BASE_DIR, "supabase_seed_part1.sql")
PART2_FILE = os.path.join(BASE_DIR, "supabase_seed_part2.sql")
PART3_FILE = os.path.join(BASE_DIR, "supabase_seed_part3.sql")

def deploy(project_ref_or_host):
    if not project_ref_or_host:
        print("Usage: python3 deploy_to_supabase.py <project_ref_or_host>")
        print("Example: python3 deploy_to_supabase.py wykkjlzsgcwlewlnuiji")
        return

    host = project_ref_or_host if "." in project_ref_or_host else f"db.{project_ref_or_host}.supabase.co"
    escaped_pass = urllib.parse.quote_plus(DB_PASSWORD)
    db_url = f"postgresql://postgres:{escaped_pass}@{host}:5432/postgres"

    print(f"Connecting to Supabase host: {host}...")
    try:
        conn = psycopg2.connect(db_url, connect_timeout=15)
        conn.autocommit = True
        cur = conn.cursor()
        print("[OK] Connected to Supabase PostgreSQL Database!")
    except Exception as e:
        print(f"[FAIL] Could not connect to Supabase: {e}")
        return

    # Executing Schema
    if os.path.exists(SCHEMA_FILE):
        print("Applying supabase_schema.sql...")
        with open(SCHEMA_FILE, "r", encoding="utf-8") as f:
            cur.execute(f.read())
        print("[OK] Schema created successfully.")

    # Executing Seed Chunks
    for part_file in [PART1_FILE, PART2_FILE, PART3_FILE]:
        if os.path.exists(part_file):
            print(f"Applying {os.path.basename(part_file)}...")
            with open(part_file, "r", encoding="utf-8") as f:
                cur.execute(f.read())
            print(f"[OK] {os.path.basename(part_file)} applied.")

    print("\n🎉 Deployment to Supabase complete!")
    print(f"To connect your backend, update your .env with:")
    print(f"SUPABASE_DB_URL={db_url}")

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else input("Enter your Supabase Project Ref ID (found in Project Settings -> General): ").strip()
    deploy(target)
