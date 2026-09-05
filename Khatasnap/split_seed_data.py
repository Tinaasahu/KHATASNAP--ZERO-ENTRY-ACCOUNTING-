import os

SEED_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "supabase_seed_data.sql")
CHUNK_SIZE_BYTES = 400 * 1024  # ~400 KB per chunk

def split_seed_file():
    if not os.path.exists(SEED_FILE):
        print(f"Error: {SEED_FILE} not found.")
        return

    with open(SEED_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()

    chunk_idx = 1
    current_chunk = []
    current_size = 0
    generated_files = []

    for line in lines:
        if line.strip().startswith("SET session_replication_role"):
            continue
        line_bytes = len(line.encode("utf-8"))
        if current_size + line_bytes > CHUNK_SIZE_BYTES and current_chunk:
            part_filename = f"supabase_seed_part{chunk_idx}.sql"
            part_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), part_filename)
            with open(part_path, "w", encoding="utf-8") as pf:
                pf.write("SET session_replication_role = 'replica';\n\n")
                pf.writelines(current_chunk)
                pf.write("\nSET session_replication_role = 'origin';\n")
            generated_files.append(part_filename)
            chunk_idx += 1
            current_chunk = []
            current_size = 0

        current_chunk.append(line)
        current_size += line_bytes

    if current_chunk:
        part_filename = f"supabase_seed_part{chunk_idx}.sql"
        part_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), part_filename)
        with open(part_path, "w", encoding="utf-8") as pf:
            pf.write("SET session_replication_role = 'replica';\n\n")
            pf.writelines(current_chunk)
            pf.write("\nSET session_replication_role = 'origin';\n")
        generated_files.append(part_filename)

    print(f"[OK] Split {SEED_FILE} into {len(generated_files)} chunks:")
    for gf in generated_files:
        filepath = os.path.join(os.path.dirname(os.path.abspath(__file__)), gf)
        size_kb = os.path.getsize(filepath) / 1024
        print(f"  - {gf} ({size_kb:.1f} KB)")

if __name__ == "__main__":
    split_seed_file()
