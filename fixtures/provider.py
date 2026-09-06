"""A local payment provider with durable idempotency and controlled failures."""
import argparse
import json
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Provider(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 128

    def __init__(self, address, database):
        super().__init__(address, Handler)
        self.database = str(database)
        self.lock = threading.Lock()
        self.mode = "success"
        self.delay = 0.8
        self.posts = 0
        with sqlite3.connect(self.database) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE IF NOT EXISTS charges(id TEXT PRIMARY KEY, amount INTEGER, currency TEXT, status TEXT)")

    def scenario(self, mode="success", delay=0.8):
        with self.lock:
            self.mode, self.delay = mode, delay


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def respond(self, code, obj):
        data = json.dumps(obj).encode()
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def read_body(self):
        size = int(self.headers.get("Content-Length", "0"))
        if size > 4096:
            raise ValueError("large body")
        return json.loads(self.rfile.read(size))

    def do_GET(self):
        if self.path == "/stats":
            with sqlite3.connect(self.server.database) as db:
                n = db.execute("SELECT count(*) FROM charges WHERE status='SUCCEEDED'").fetchone()[0]
            return self.respond(200, {"charges": n, "posts": self.server.posts})
        self.charge(False)

    def do_POST(self):
        if self.path == "/admin/scenario":
            if self.headers.get("X-Admin-Token") != "local-admin":
                return self.respond(403, {"error": "forbidden"})
            try:
                value = self.read_body()
                modes = {"success", "decline", "unavailable", "rate_limit", "slow_before", "commit_timeout", "malformed", "amount_mismatch", "lookup_error", "body_timeout"}
                if value["mode"] not in modes or not 0 <= float(value.get("delay", .8)) <= 30:
                    raise ValueError("scenario")
                self.server.scenario(value["mode"], float(value.get("delay", .8)))
                return self.respond(200, {"mode": value["mode"]})
            except (ValueError, KeyError, TypeError):
                return self.respond(400, {"error": "invalid_scenario"})
        self.charge(True)

    def charge(self, write):
        if not self.path.startswith("/charges/"):
            return self.respond(404, {"error": "not_found"})
        with self.server.lock:
            mode, delay = self.server.mode, self.server.delay
            if write:
                self.server.posts += 1
        if mode == "unavailable" or (mode == "lookup_error" and not write):
            return self.respond(503, {"error": "unavailable"})
        if mode == "rate_limit":
            return self.respond(429, {"error": "rate_limited"})
        pid = self.path.removeprefix("/charges/")
        if self.headers.get("Idempotency-Key") != pid:
            return self.respond(400, {"error": "key_required"})
        try:
            data = self.read_body() if write else None
            if mode == "slow_before" and write:
                time.sleep(delay)
            with sqlite3.connect(self.server.database, timeout=5) as db:
                db.row_factory = sqlite3.Row
                if write:
                    db.execute("PRAGMA synchronous=FULL")
                    db.execute("INSERT INTO charges VALUES(?,?,?,?) ON CONFLICT DO NOTHING",
                               (pid, data["amount"], data["currency"], "DECLINED" if mode == "decline" else "SUCCEEDED"))
                row = db.execute("SELECT * FROM charges WHERE id=?", (pid,)).fetchone()
                if row is None:
                    return self.respond(404, {"error": "not_found"})
                result = dict(row)
                if write and (result["amount"] != data["amount"] or result["currency"] != data["currency"]):
                    return self.respond(409, {"error": "idempotency_conflict"})
            # The database transaction has committed before the simulated lost response.
            if mode == "commit_timeout" and write:
                time.sleep(delay)
            if mode == "malformed":
                return self.respond(200, {"unexpected": True})
            if mode == "amount_mismatch":
                result["amount"] += 1
            if mode == "body_timeout":
                data = json.dumps(result).encode()
                try:
                    self.send_response(200); self.send_header("Content-Length", str(len(data))); self.end_headers()
                    self.wfile.write(data[:1]); self.wfile.flush(); time.sleep(delay); self.wfile.write(data[1:])
                except (BrokenPipeError, ConnectionResetError):
                    pass
                return
            self.respond(200, result)
        except (ValueError, KeyError, TypeError):
            self.respond(400, {"error": "invalid_request"})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=9090)
    parser.add_argument("--db", default="provider.db")
    args = parser.parse_args()
    Provider(("127.0.0.1", args.port), args.db).serve_forever()
