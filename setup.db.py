import os
import sys
from getpass import getpass

import mysql.connector
from mysql.connector import errors

HOST = os.environ.get("DB_HOST", "localhost")
PORT = int(os.environ.get("DB_PORT", 3306))
USER = os.environ.get("DB_USER", "root")

password = os.environ.get("DB_PASSWORD")
if password is None:
    password = getpass(f"MySQL password for user '{USER}' (press Enter if it has none): ")

try:
    conn = mysql.connector.connect(host=HOST, port=PORT, user=USER, password=password)
except errors.Error as err:
    print(f"\nCould not connect to MySQL: {err}")
    print("Check that MySQL is running (start it in XAMPP) and that the password is right.")
    sys.exit(1)

schema_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")
with open(schema_path, encoding="utf-8") as f:
    lines = [line for line in f if not line.strip().startswith("--")]
statements = [s.strip() for s in "".join(lines).split(";") if s.strip()]

cur = conn.cursor()
for statement in statements:
    cur.execute(statement)
conn.commit()

cur.execute("USE craveco")
cur.execute("SHOW TABLES")
tables = [row[0] for row in cur.fetchall()]
cur.execute("SELECT COUNT(*) FROM menu_items")
menu_count = cur.fetchone()[0]

print("\nDone! Database 'craveco' is ready.")
print("Tables:", ", ".join(tables))
print(f"Menu items loaded: {menu_count}")

cur.close()
conn.close()
