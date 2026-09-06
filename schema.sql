PRAGMA journal_mode=WAL;
PRAGMA synchronous=FULL;
PRAGMA busy_timeout=5000;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS payments (
  id TEXT PRIMARY KEY,
  merchant TEXT NOT NULL,
  idem_key TEXT NOT NULL,
  amount INTEGER NOT NULL CHECK(amount BETWEEN 1 AND 1000000000),
  currency TEXT NOT NULL CHECK(currency IN ('JPY', 'USD')),
  status TEXT NOT NULL CHECK(status IN ('PENDING','UNKNOWN','SUCCEEDED','DECLINED')),
  created_at INTEGER NOT NULL,
  UNIQUE(merchant, idem_key)
);
CREATE INDEX IF NOT EXISTS payments_recovery ON payments(status, created_at);
CREATE TABLE IF NOT EXISTS ledger (
  payment_id TEXT NOT NULL REFERENCES payments(id),
  account TEXT NOT NULL CHECK(account IN ('psp_receivable', 'merchant_payable')),
  signed_amount INTEGER NOT NULL,
  currency TEXT NOT NULL,
  PRIMARY KEY(payment_id, account)
);
CREATE TABLE IF NOT EXISTS reconciliation_breaks (
  payment_id TEXT PRIMARY KEY REFERENCES payments(id),
  reason TEXT NOT NULL,
  resolved INTEGER NOT NULL DEFAULT 0 CHECK(resolved IN (0,1)),
  updated_at INTEGER NOT NULL
);
