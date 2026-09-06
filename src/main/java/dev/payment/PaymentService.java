package dev.payment;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.Map;
import java.util.Set;

public final class PaymentService {
    private final Store store;
    private final Provider provider;
    public PaymentService(Store store, Provider provider) { this.store = store; this.provider = provider; }
    public void settle(Payment p, boolean lookup) throws Exception {
        JsonNode result;
        try {
            result = lookup ? provider.call("GET", p) : null;
            if (result == null) result = provider.call("POST", p);
        } catch (Exception error) {
            store.finish(p.id(), "UNKNOWN");
            String reason = error instanceof IllegalStateException ? error.getMessage() : "transport_or_timeout";
            store.recordBreak(p.id(), reason); return;
        }
        if (!result.path("id").asText().equals(p.id()) || !result.path("amount").isIntegralNumber() || !result.path("amount").canConvertToLong() || result.path("amount").asLong() != p.amount() || !result.path("currency").asText().equals(p.currency())) {
            store.finish(p.id(), "UNKNOWN"); store.recordBreak(p.id(), "provider_mismatch"); return;
        }
        store.finish(p.id(), result.get("status").asText());
    }
    public record Response(int code, Object body) {}
    public Response create(String merchant, String key, long amount, String currency) throws Exception {
        var reservation = store.reserve(merchant, key, amount, currency); var p = reservation.payment();
        if (p.amount() != amount || !p.currency().equals(currency)) return new Response(409, Map.of("error", "idempotency_conflict"));
        if (reservation.owner()) settle(p, false);
        p = store.get(p.id());
        int code = Set.of("PENDING", "UNKNOWN").contains(p.status()) ? 202 : reservation.owner() ? 201 : 200;
        return new Response(code, p.view());
    }
    public Object reconcile() throws Exception {
        var items = store.pending(); for (var p : items) settle(p, true);
        return Map.of("checked", items.size(), "pending", store.unknownCount());
    }
}
