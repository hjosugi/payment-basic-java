"""The same black-box recovery contract runs against all three native services."""
import concurrent.futures
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fixtures"))
from provider import Provider

COMMAND = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else ["node", "src/server.ts"]
sys.argv = [sys.argv[0]]


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Contract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.provider = Provider(("127.0.0.1", 0), self.root / "provider.db")
        threading.Thread(target=self.provider.serve_forever, daemon=True).start()
        self.port = free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self.env = dict(os.environ, PORT=str(self.port), DB_PATH=str(self.root / "payments.db"),
                        PROVIDER_URL=f"http://127.0.0.1:{self.provider.server_port}",
                        PROVIDER_TIMEOUT_MS="300", MAX_INFLIGHT="3", ADMIN_TOKEN="test-admin")
        self.log = (self.root / "app.log").open("w+")
        self.proc = None
        self.start()

    def start(self):
        self.proc = subprocess.Popen(COMMAND, env=self.env, stdout=self.log, stderr=self.log)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                self.log.seek(0)
                self.fail(self.log.read())
            try:
                if self.request("GET", "/health")[0] == 200:
                    return
            except (OSError, urllib.error.URLError):
                pass
            time.sleep(.02)
        self.fail("startup timeout")

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait(timeout=5)

    def tearDown(self):
        self.stop()
        self.provider.shutdown(); self.provider.server_close()
        self.log.close(); self.temp.cleanup()

    def request(self, method, path, body=None, key="order-1", merchant="demo", admin="test-admin"):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method, headers={
            "Content-Type": "application/json", "Idempotency-Key": key, "X-Merchant-Id": merchant, "X-Admin-Token": admin})
        try:
            response = urllib.request.urlopen(req, timeout=15)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            raw = response.read().decode()
            value = raw if path == "/metrics" else json.loads(raw)
            return response.status, value, dict(response.headers)

    def create(self, key="order-1", amount=1000, merchant="demo"):
        return self.request("POST", "/payments", {"amount": amount, "currency": "JPY"}, key=key, merchant=merchant)

    def rows(self, sql, provider=False):
        with sqlite3.connect(self.root / ("provider.db" if provider else "payments.db")) as db:
            return db.execute(sql).fetchall()

    def test_success_replay_and_ledger(self):
        code, p, _ = self.create(); self.assertEqual(code, 201); self.assertEqual(p["status"], "SUCCEEDED")
        code, again, _ = self.create(); self.assertEqual(code, 200); self.assertEqual(again, p)
        self.assertEqual(self.provider.posts, 1)
        self.assertEqual(self.rows("SELECT count(*),sum(signed_amount) FROM ledger"), [(2, 0)])

    def test_same_key_different_amount_conflicts(self):
        self.create(); self.assertEqual(self.create(amount=2000)[0], 409); self.assertEqual(self.provider.posts, 1)

    def test_merchant_scope(self):
        first = self.create()[1]; second = self.create(merchant="other")[1]
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(self.request("GET", "/payments/" + first["id"], merchant="other")[0], 404)

    def test_concurrent_replay(self):
        self.provider.scenario("slow_before", .15)
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
            results = list(pool.map(lambda _: self.create(), range(12)))
        self.assertTrue(all(code in (200, 201, 202) for code, _, _ in results), results)
        self.assertEqual(len({p["id"] for _, p, _ in results}), 1)
        self.assertEqual(self.provider.posts, 1)
        self.assertEqual(self.rows("SELECT count(*) FROM ledger"), [(2,)])

    def test_timeout_after_commit_recovers_without_second_charge(self):
        self.provider.scenario("commit_timeout")
        code, p, headers = self.create(); self.assertEqual(code, 202); self.assertEqual(p["status"], "UNKNOWN")
        self.assertEqual(headers.get("Retry-After") or headers.get("Retry-after"), "1")
        self.assertEqual(self.rows("SELECT count(*) FROM charges", True), [(1,)])
        self.provider.scenario()
        self.request("POST", "/admin/reconcile")
        self.assertEqual(self.request("GET", "/payments/" + p["id"])[1]["status"], "SUCCEEDED")
        self.assertEqual(self.provider.posts, 1)
        self.assertEqual(self.rows("SELECT resolved FROM reconciliation_breaks"), [(1,)])

    def test_restart_after_unknown_and_duplicate_reconciliation(self):
        self.provider.scenario("commit_timeout"); _, p, _ = self.create()
        self.stop(); self.provider.scenario(); self.start()
        self.request("POST", "/admin/reconcile"); self.request("POST", "/admin/reconcile")
        self.assertEqual(self.create()[1]["status"], "SUCCEEDED")
        self.assertEqual(self.rows("SELECT count(*),sum(signed_amount) FROM ledger"), [(2, 0)])
        self.assertEqual(self.provider.posts, 1)

    def test_crash_during_inflight_request(self):
        self.provider.scenario("commit_timeout", 1)
        with concurrent.futures.ThreadPoolExecutor() as pool:
            pending = pool.submit(self.create)
            deadline = time.monotonic() + 5
            while not self.rows("SELECT id FROM charges", True):
                self.assertLess(time.monotonic(), deadline); time.sleep(.01)
            self.stop()
            try: pending.result()
            except (OSError, ValueError): pass
        self.assertEqual(self.rows("SELECT status FROM payments"), [("PENDING",)])
        self.provider.scenario(); self.start(); self.request("POST", "/admin/reconcile")
        self.assertEqual(self.rows("SELECT status FROM payments"), [("SUCCEEDED",)])
        self.assertEqual(self.provider.posts, 1)

    def test_missing_provider_record_resubmits_same_id(self):
        self.provider.scenario("unavailable"); _, p, _ = self.create()
        self.provider.scenario(); self.request("POST", "/admin/reconcile")
        self.assertEqual(self.rows("SELECT id FROM charges", True), [(p["id"],)])
        self.assertEqual(self.rows("SELECT status FROM payments"), [("SUCCEEDED",)])

    def test_decline_is_terminal_and_not_breaker_error(self):
        self.provider.scenario("decline")
        for i in range(4): self.assertEqual(self.create(key=f"decline-{i}")[1]["status"], "DECLINED")
        self.assertEqual(self.rows("SELECT count(*) FROM ledger"), [(0,)])
        self.assertIn("payment_circuit_open 0", self.request("GET", "/metrics")[1])

    def test_circuit_opens_and_recovers(self):
        self.provider.scenario("unavailable")
        for i in range(3): self.assertEqual(self.create(key=f"fail-{i}")[0], 202)
        self.assertEqual(self.provider.posts, 3)
        self.create(key="blocked"); self.assertEqual(self.provider.posts, 3)
        self.assertIn("payment_circuit_open 1", self.request("GET", "/metrics")[1])
        self.provider.scenario(); time.sleep(1.05)
        self.assertEqual(self.create(key="probe")[1]["status"], "SUCCEEDED")

    def test_capacity_rejects_excess_work(self):
        self.provider.scenario("slow_before", .25)
        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
            results = list(pool.map(lambda i: self.create(key=f"load-{i}"), range(20)))
        self.assertIn(429, [x[0] for x in results])
        self.assertTrue(all(x[0] in (201, 202, 429) for x in results), results)

    def test_mismatch_is_persisted_and_recoverable(self):
        self.provider.scenario("amount_mismatch"); self.assertEqual(self.create()[1]["status"], "UNKNOWN")
        self.assertEqual(self.rows("SELECT reason,resolved FROM reconciliation_breaks"), [("provider_mismatch", 0)])
        self.assertEqual(self.rows("SELECT count(*) FROM ledger"), [(0,)])
        self.provider.scenario(); self.request("POST", "/admin/reconcile")
        self.assertEqual(self.rows("SELECT count(*) FROM ledger"), [(2,)])

    def test_lookup_failure_does_not_resubmit(self):
        self.provider.scenario("commit_timeout"); self.create(); before = self.provider.posts
        self.provider.scenario("lookup_error"); self.request("POST", "/admin/reconcile")
        self.assertEqual(self.provider.posts, before)
        self.assertEqual(self.rows("SELECT status FROM payments"), [("UNKNOWN",)])

    def test_malformed_and_body_timeout_remain_unknown(self):
        for mode in ("malformed", "body_timeout"):
            self.provider.scenario(mode)
            start = time.monotonic(); code, p, _ = self.create(key=mode)
            self.assertLess(time.monotonic() - start, 1.5)
            self.assertEqual(code, 202); self.assertEqual(p["status"], "UNKNOWN")

    def test_invalid_input_and_admin_access(self):
        for amount in (0, -1, 1.5, True, "1000", 1000000001):
            self.assertEqual(self.create(amount=amount)[0], 400)
        self.assertEqual(self.create(key="")[0], 400)
        self.assertEqual(self.request("POST", "/payments", {"amount": 1, "currency": "EUR"})[0], 400)
        self.assertEqual(self.request("POST", "/payments", {"amount": 1, "currency": "JPY", "extra": 1})[0], 400)
        self.assertEqual(self.request("POST", "/admin/reconcile", admin="bad")[0], 403)
        self.assertEqual(self.provider.posts, 0)

    def test_metrics_and_structured_logs(self):
        self.create(); text = self.request("GET", "/metrics")[1]
        for name in ("payment_http_requests_total", "payment_http_duration_seconds_bucket", "payment_provider_inflight", "payment_unresolved"):
            self.assertIn(name, text)
        self.log.flush(); self.log.seek(0)
        logs = [json.loads(line) for line in self.log.read().splitlines() if line.startswith("{")]
        self.assertTrue(any(x["route"] == "create" and x["request_id"] for x in logs))
        self.assertFalse(any("idem_key" in x or "key" in x for x in logs))

    def test_two_processes_share_database_constraint(self):
        other_port = free_port()
        other = subprocess.Popen(COMMAND, env=dict(self.env, PORT=str(other_port)), stdout=self.log, stderr=self.log)
        try:
            deadline = time.monotonic() + 15
            while True:
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{other_port}/health", timeout=1) as r:
                        if r.status == 200: break
                except OSError:
                    if time.monotonic() > deadline: self.fail("second instance startup timeout")
                    time.sleep(.02)
            self.provider.scenario("slow_before", .15)
            def send(port):
                req = urllib.request.Request(f"http://127.0.0.1:{port}/payments", data=b'{"amount":1000,"currency":"JPY"}',
                    headers={"Content-Type": "application/json", "Idempotency-Key": "shared", "X-Merchant-Id": "demo"})
                with urllib.request.urlopen(req, timeout=5) as response: return json.load(response)
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                items = list(pool.map(send, [self.port, other_port] * 4))
            self.assertEqual(len({p["id"] for p in items}), 1)
            self.assertEqual(self.provider.posts, 1)
            self.assertEqual(self.rows("SELECT count(*) FROM ledger"), [(2,)])
        finally:
            other.kill(); other.wait(timeout=5)

    def test_late_timeout_does_not_reopen_resolved_break(self):
        self.provider.scenario("commit_timeout")
        with concurrent.futures.ThreadPoolExecutor() as pool:
            pending = pool.submit(self.create)
            deadline = time.monotonic() + 5
            while not self.rows("SELECT id FROM charges", True):
                self.assertLess(time.monotonic(), deadline); time.sleep(.01)
            self.provider.scenario()
            self.request("POST", "/admin/reconcile")
            pending.result()
        self.assertEqual(self.rows("SELECT status FROM payments"), [("SUCCEEDED",)])
        self.assertEqual(self.rows("SELECT count(*) FROM reconciliation_breaks WHERE resolved=0"), [(0,)])
        self.assertEqual(self.rows("SELECT count(*) FROM ledger"), [(2,)])

    def test_rate_limit_remains_unknown_and_retries_by_same_id(self):
        self.provider.scenario("rate_limit"); code, p, _ = self.create()
        self.assertEqual(code, 202); self.assertEqual(p["status"], "UNKNOWN")
        self.provider.scenario(); self.request("POST", "/admin/reconcile")
        self.assertEqual(self.rows("SELECT id FROM charges", True), [(p["id"],)])

    def test_settlement_records_all_difference_categories(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
        from settlement import reconcile
        first = self.create(key="one")[1]; self.create(key="two")
        statement = self.root / "statement.csv"
        statement.write_text("id,amount,currency,status\n" +
            f"{first['id']},999,JPY,SUCCEEDED\n{first['id']},999,JPY,SUCCEEDED\nprovider-only,1000,JPY,SUCCEEDED\n")
        report = reconcile(self.root / "payments.db", statement)
        self.assertEqual({p["reason"] for p in report["issues"]},
            {"statement_mismatch", "duplicate_statement_row", "provider_only_record", "missing_provider_record"})
        self.assertEqual(self.rows("SELECT count(*) FROM settlement_runs"), [(1,)])
        self.assertEqual(self.rows("SELECT sum(amount) FROM payments"), [(2000,)])


if __name__ == "__main__":
    unittest.main(verbosity=2)
