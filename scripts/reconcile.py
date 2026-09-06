"""Run the bounded reconciliation batch with exponential backoff and jitter."""
import argparse
import json
import os
import random
import time
import urllib.error
import urllib.request

parser = argparse.ArgumentParser()
parser.add_argument("--base", default="http://127.0.0.1:8080")
parser.add_argument("--once", action="store_true")
args = parser.parse_args()
attempt = 0
while True:
    req = urllib.request.Request(args.base + "/admin/reconcile", method="POST", data=b"",
                                 headers={"X-Admin-Token": os.environ.get("ADMIN_TOKEN", "local-admin")})
    try:
        with urllib.request.urlopen(req, timeout=75) as response:
            value = json.load(response)
        print(json.dumps(value), flush=True)
        attempt = min(attempt + 1, 6) if value["pending"] else 0
    except (OSError, ValueError) as error:
        if isinstance(error, urllib.error.HTTPError) and error.code in (401, 403):
            raise SystemExit("Invalid ADMIN_TOKEN")
        print(json.dumps({"error": type(error).__name__}), flush=True)
        attempt = min(attempt + 1, 6)
    if args.once:
        break
    time.sleep(random.uniform(1, min(60, 2 ** (attempt + 1))))
