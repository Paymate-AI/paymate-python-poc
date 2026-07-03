import sqlite3

db_path = "paymate.db"

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

try:
    cursor.execute("DROP TABLE IF EXISTS _alembic_tmp_users")
    conn.commit()
    print("Successfully dropped _alembic_tmp_users!")
except Exception as e:
    print(f"Error: {e}")
finally:
    conn.close()
