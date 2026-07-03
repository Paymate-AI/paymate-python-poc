import sqlite3

db_path = "paymate.db"

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Option 1: Clear only the users table
print("Clearing users table...")
cursor.execute("DELETE FROM users")

# If you want to reset the auto-increment ID for users (check if sqlite_sequence exists first):
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sqlite_sequence'")
if cursor.fetchone():
    cursor.execute("DELETE FROM sqlite_sequence WHERE name='users'")

# Option 2: Clear ALL tables (uncomment if you want to reset everything)
# print("Clearing all tables...")
# tables = ["users", "products", "orders", "order_items", "payments", "virtual_accounts"]
# for table in tables:
#     cursor.execute(f"DELETE FROM {table}")
#     # Check if sqlite_sequence exists first
#     cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sqlite_sequence'")
#     if cursor.fetchone():
#         cursor.execute(f"DELETE FROM sqlite_sequence WHERE name='{table}'")

conn.commit()
print("Database cleared!")

conn.close()
