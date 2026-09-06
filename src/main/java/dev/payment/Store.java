package dev.payment;

import java.nio.charset.StandardCharsets;
import java.sql.*;
import java.util.*;

public final class Store implements AutoCloseable {
    private final Connection db;
    public Store(String path) throws Exception {
        db = DriverManager.getConnection("jdbc:sqlite:" + path);
        try (var in = Store.class.getResourceAsStream("/schema.sql")) {
            if (in == null) throw new IllegalStateException("Missing schema.sql");
            for (String sql : new String(in.readAllBytes(), StandardCharsets.UTF_8).split(";")) {
                if (!sql.isBlank()) try (var statement = db.createStatement()) { statement.execute(sql); }
            }
        }
    }
    private PreparedStatement statement(String sql, Object... args) throws SQLException {
        var s = db.prepareStatement(sql);
        for (int i = 0; i < args.length; i++) s.setObject(i + 1, args[i]);
        return s;
    }
    private int execute(String sql, Object... args) throws SQLException {
        try (var s = statement(sql, args)) { return s.executeUpdate(); }
    }
    private Payment row(ResultSet r) throws SQLException {
        return new Payment(r.getString("id"), r.getString("merchant"), r.getString("idem_key"), r.getLong("amount"),
            r.getString("currency"), r.getString("status"), r.getLong("created_at"));
    }
    public record Reservation(Payment payment, boolean owner) {}
    public synchronized Reservation reserve(String merchant, String key, long amount, String currency) throws SQLException {
        int changed = execute("INSERT INTO payments VALUES(?,?,?,?,?,'PENDING',?) ON CONFLICT(merchant,idem_key) DO NOTHING",
            UUID.randomUUID().toString(), merchant, key, amount, currency, System.currentTimeMillis());
        try (var s = statement("SELECT * FROM payments WHERE merchant=? AND idem_key=?", merchant, key); var r = s.executeQuery()) {
            if (!r.next()) throw new SQLException("Reservation missing");
            return new Reservation(row(r), changed == 1);
        }
    }
    public synchronized Payment get(String id) throws SQLException {
        try (var s = statement("SELECT * FROM payments WHERE id=?", id); var r = s.executeQuery()) {
            return r.next() ? row(r) : null;
        }
    }
    public synchronized List<Payment> pending() throws SQLException {
        var result = new ArrayList<Payment>();
        try (var s = statement("SELECT * FROM payments WHERE status IN ('PENDING','UNKNOWN') ORDER BY created_at LIMIT 100"); var r = s.executeQuery()) {
            while (r.next()) result.add(row(r));
        }
        return result;
    }
    public synchronized void finish(String id, String status) throws SQLException {
        db.setAutoCommit(false);
        try {
            execute("UPDATE payments SET status=? WHERE id=? AND status IN ('PENDING','UNKNOWN')", status, id);
            Payment p = get(id);
            if (p.status().equals("SUCCEEDED")) {
                execute("INSERT INTO ledger VALUES(?,?,?,?) ON CONFLICT DO NOTHING", id, "psp_receivable", p.amount(), p.currency());
                execute("INSERT INTO ledger VALUES(?,?,?,?) ON CONFLICT DO NOTHING", id, "merchant_payable", -p.amount(), p.currency());
            }
            if (Set.of("SUCCEEDED", "DECLINED").contains(p.status()))
                execute("UPDATE reconciliation_breaks SET resolved=1,updated_at=? WHERE payment_id=?", System.currentTimeMillis(), id);
            db.commit();
        } catch (SQLException | RuntimeException error) { db.rollback(); throw error; }
        finally { db.setAutoCommit(true); }
    }
    public synchronized void recordBreak(String id, String reason) throws SQLException {
        execute("INSERT INTO reconciliation_breaks SELECT id,?,0,? FROM payments WHERE id=? AND status IN ('PENDING','UNKNOWN') ON CONFLICT(payment_id) DO UPDATE SET reason=excluded.reason,resolved=0,updated_at=excluded.updated_at",
            reason, System.currentTimeMillis(), id);
    }
    public synchronized int unknownCount() throws SQLException {
        try (var s = statement("SELECT count(*) FROM payments WHERE status IN ('PENDING','UNKNOWN')"); var r = s.executeQuery()) {
            r.next(); return r.getInt(1);
        }
    }
    public synchronized List<Map<String, Object>> breaks() throws SQLException {
        var result = new ArrayList<Map<String, Object>>();
        try (var s = statement("SELECT * FROM reconciliation_breaks"); var r = s.executeQuery()) {
            while (r.next()) result.add(Map.of("payment_id", r.getString("payment_id"), "reason", r.getString("reason"),
                "resolved", r.getInt("resolved"), "updated_at", r.getLong("updated_at")));
        }
        return result;
    }
    public synchronized void close() throws SQLException { db.close(); }
}
