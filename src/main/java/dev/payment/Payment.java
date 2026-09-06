package dev.payment;

import java.util.Map;

public record Payment(String id, String merchant, String key, long amount, String currency, String status, long createdAt) {
    public Map<String, Object> view() {
        return Map.of("id", id, "amount", amount, "currency", currency, "status", status);
    }
}
