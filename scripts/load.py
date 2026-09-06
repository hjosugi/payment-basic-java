"""Closed-loop load generator: reports outcomes separately from infrastructure errors."""
import argparse
import concurrent.futures
import json
import math
import statistics
import time
import urllib.error
import urllib.request
import uuid
from collections import Counter

parser = argparse.ArgumentParser()
parser.add_argument("--base", default="http://127.0.0.1:8080")
parser.add_argument("--requests", type=int, default=100)
parser.add_argument("--concurrency", type=int, default=8)
args = parser.parse_args()
if args.requests < 1 or args.concurrency < 1:
    parser.error("requests and concurrency must be positive")

def send(_):
    start = time.monotonic()
    req = urllib.request.Request(args.base + "/payments", method="POST", data=b'{"amount":1000,"currency":"JPY"}',
        headers={"Content-Type": "application/json", "X-Merchant-Id": "load-test", "Idempotency-Key": str(uuid.uuid4())})
    try:
        try: response = urllib.request.urlopen(req, timeout=5)
        except urllib.error.HTTPError as error: response = error
        with response:
            code = response.status
            status = json.load(response).get("status", "rejected")
    except (OSError, ValueError):
        code, status = 0, "transport_error"
    return time.monotonic() - start, code, status

start = time.monotonic()
with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
    results = list(pool.map(send, range(args.requests)))
elapsed = time.monotonic() - start
durations = sorted(x[0] for x in results)
percentile = lambda q: round(durations[max(0, math.ceil(q * len(durations)) - 1)] * 1000, 2)
print(json.dumps({"requests": len(results), "concurrency": args.concurrency, "elapsed_seconds": round(elapsed, 3),
    "completed_rps": round(len(results) / elapsed, 2), "p50_ms": percentile(.5), "p95_ms": percentile(.95), "p99_ms": percentile(.99),
    "mean_ms": round(statistics.mean(durations) * 1000, 2),
    "http_statuses": dict(Counter(str(x[1]) for x in results)), "payment_states": dict(Counter(x[2] for x in results))}, indent=2))
