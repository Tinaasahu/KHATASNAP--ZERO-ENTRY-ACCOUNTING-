import sqlite3, json
c = sqlite3.connect('khatasnap.db').cursor()
print(c.execute("select * from calculator_sessions order by id desc limit 2").fetchall())
