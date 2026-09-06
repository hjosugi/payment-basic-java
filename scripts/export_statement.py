"""Export the local mock provider database as a complete statement."""
import argparse
import csv
import sqlite3

p = argparse.ArgumentParser(); p.add_argument("--db", default="provider.db"); p.add_argument("--output", default="statement.csv")
args = p.parse_args()
with sqlite3.connect(args.db) as db, open(args.output, "w", newline="", encoding="utf-8") as output:
    writer = csv.writer(output); writer.writerow(["id", "amount", "currency", "status"])
    writer.writerows(db.execute("SELECT id,amount,currency,status FROM charges ORDER BY id"))
