"""Demonstrate timeout, durable UNKNOWN state, and reconciliation."""
import json
import os
import urllib.request
import uuid

base = os.environ.get("PAYMENT_URL", "http://127.0.0.1:8080")
provider = os.environ.get("PROVIDER_URL", "http://127.0.0.1:9090")

def call(url, body=None, key="demo"):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", "Idempotency-Key": key,
        "X-Merchant-Id": "demo", "X-Admin-Token": os.environ.get("ADMIN_TOKEN", "local-admin")})
    with urllib.request.urlopen(req, timeout=75) as r:
        value = json.load(r); print(r.status, json.dumps(value), flush=True); return value

call(provider + "/admin/scenario", {"mode": "commit_timeout", "delay": .8})
try:
    key = str(uuid.uuid4())
    payment = call(base + "/payments", {"amount": 1000, "currency": "JPY"}, key)
    call(base + "/payments", {"amount": 1000, "currency": "JPY"}, key)
finally:
    call(provider + "/admin/scenario", {"mode": "success"})
call(base + "/admin/reconcile", {})
call(base + "/payments/" + payment["id"])
call(provider + "/stats")
