import psycopg2
import os

conn = psycopg2.connect(os.environ["DATABASE_URL"])
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS call_history (
    id SERIAL PRIMARY KEY,
    phone_number VARCHAR(30) DEFAULT 'unknown',
    role VARCHAR(20) DEFAULT 'user',
    message TEXT DEFAULT '',
    timestamp TIMESTAMP DEFAULT NOW()
);
""")

conn.commit()
cur.close()
conn.close()

print("Table created!")
