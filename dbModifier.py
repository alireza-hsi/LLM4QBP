import sqlite3

db_path = "resultsDb.sqlite"
table = "experiment_results"
rows_to_delete = 3

conn = sqlite3.connect(db_path)
cur = conn.cursor()

# Find the IDs of the last 6 rows
cur.execute(f"SELECT id FROM {table} ORDER BY id DESC LIMIT ?", (rows_to_delete,))
ids = [row[0] for row in cur.fetchall()]

if ids:
    # Delete those rows
    cur.execute(f"DELETE FROM {table} WHERE id IN ({','.join(['?']*len(ids))})", ids)
    print(f"Deleted rows with ids: {ids}")
else:
    print("No rows to delete.")

conn.commit()
conn.close()