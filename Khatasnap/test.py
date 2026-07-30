import sqlite3
conn = sqlite3.connect('khatasnap.db')
cur = conn.cursor()
cur.execute("SELECT id, name, selling_price, current_qty FROM products WHERE name LIKE '%toffee%'")
print(cur.fetchall())
