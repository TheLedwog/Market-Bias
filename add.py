import sqlite3
conn = sqlite3.connect("memory/daily_log.db")
c = conn.cursor()

try:
    c.execute("ALTER TABLE log ADD COLUMN eval_attempts INTEGER DEFAULT 0")
    conn.commit()
    print("Column added")
except Exception as e:
    print("Already exists:", e)

conn.close()
