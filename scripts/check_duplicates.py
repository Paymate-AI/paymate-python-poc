import sqlite3

db_path = "paymate.db"

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Get all users
cursor.execute("SELECT id, business_name FROM users")
users = cursor.fetchall()

print("Current users:")
for user in users:
    print(f"ID: {user[0]}, Business Name: {user[1]}")

# Find duplicates
cursor.execute("""
    SELECT business_name, COUNT(*) as count
    FROM users
    GROUP BY business_name
    HAVING COUNT(*) > 1
""")
duplicates = cursor.fetchall()

if duplicates:
    print("\nDuplicate business names found:")
    for dup in duplicates:
        print(f"Business Name: {dup[0]}, Count: {dup[1]}")
else:
    print("\nNo duplicate business names found!")

conn.close()
