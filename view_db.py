import psycopg2
import os

def get_db():
    return psycopg2.connect(os.getenv("DATABASE_URL"))

conn = get_db()
cur = conn.cursor()

cur.execute("SELECT id, phone_number, role, message, timestamp FROM call_history ORDER BY id ASC;")
rows = cur.fetchall()

print("\n===== CALL HISTORY TABLE =====\n")
for row in rows:
    print(row)

cur.close()
conn.close()
