import sqlite3

db_path = "resultsDb.sqlite"
table = "experiment_results"
column = "node_similarity"

conn = sqlite3.connect(db_path)
cur = conn.cursor()

# Delete all rows where node_similarity is NULL
cur.execute(f"DELETE FROM {table} WHERE {column} IS NULL")
deleted_count = cur.rowcount

conn.commit()
conn.close()

print(f"Deleted {deleted_count} rows where {column} IS NULL from {table}.")