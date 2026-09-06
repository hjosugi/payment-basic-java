"""Compare a complete provider statement with the local payment database."""
import argparse
import csv
import hashlib
import io
import json
import sqlite3
import time
import uuid
from pathlib import Path


def reconcile(db_path, statement):
    raw = Path(statement).read_bytes()
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    if reader.fieldnames != ["id", "amount", "currency", "status"]:
        raise ValueError("Expected id,amount,currency,status")
    provider = {}; issues = []
    for row in reader:
        row["amount"] = int(row["amount"])
        if row["id"] in provider:
            issues.append((row["id"], "duplicate_statement_row"))
        provider[row["id"]] = row
    run_id = str(uuid.uuid4())
    with sqlite3.connect(db_path) as db:
        db.row_factory = sqlite3.Row
        local = {r["id"]: dict(r) for r in db.execute("SELECT * FROM payments")}
        for pid, payment in local.items():
            external = provider.get(pid)
            if external is None:
                issues.append((pid, "missing_provider_record"))
            elif any(payment[k] != external[k] for k in ("amount", "currency", "status")):
                issues.append((pid, "statement_mismatch"))
        for pid in provider.keys() - local.keys():
            issues.append((pid, "provider_only_record"))
        db.execute("CREATE TABLE IF NOT EXISTS settlement_runs(run_id TEXT PRIMARY KEY, created_at INTEGER, statement_sha256 TEXT, issue_count INTEGER)")
        db.execute("CREATE TABLE IF NOT EXISTS settlement_breaks(run_id TEXT, item_id TEXT, reason TEXT)")
        db.execute("INSERT INTO settlement_runs VALUES(?,?,?,?)", (run_id, int(time.time() * 1000), hashlib.sha256(raw).hexdigest(), len(issues)))
        db.executemany("INSERT INTO settlement_breaks VALUES(?,?,?)", [(run_id, pid, reason) for pid, reason in issues])
    return {"run_id": run_id, "issues": [{"id": pid, "reason": reason} for pid, reason in issues], "local_records": len(local), "provider_records": len(provider)}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Input must be a complete statement for this entire demo database.")
    p.add_argument("--db", default="payments.db"); p.add_argument("--statement", required=True)
    args = p.parse_args(); report = reconcile(args.db, args.statement)
    print(json.dumps(report, indent=2)); raise SystemExit(2 if report["issues"] else 0)
