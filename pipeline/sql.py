"""
sql.py - run any SQL query against the database and print the result.

Usage:
  python pipeline/sql.py "SELECT lang, COUNT(*) FROM articles GROUP BY lang ORDER BY 2 DESC"

The database is opened read-only, so nothing you type here can change or delete data.
"""
import sqlite3
import sys

from store import DB_PATH

if len(sys.argv) != 2:
    sys.exit(__doc__)

conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
try:
    cur = conn.execute(sys.argv[1])
except sqlite3.Error as ex:
    sys.exit(f"SQL error: {ex}")
print(" | ".join(d[0] for d in cur.description))
for row in cur.fetchmany(100):
    print(" | ".join("" if v is None else str(v) for v in row))
