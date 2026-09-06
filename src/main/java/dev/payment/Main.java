package dev.payment;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;

public final class Main {
    private static String env(String name, String value) { return System.getenv().getOrDefault(name, value); }
    private static int number(String name, int fallback) {
        int n = Integer.parseInt(env(name, "" + fallback)); if (n <= 0) throw new IllegalArgumentException(name); return n;
    }
    private static boolean identifier(String value) { return value != null && value.matches("[A-Za-z0-9_-]{1,100}"); }
    public static void main(String[] args) throws Exception {
        var store = new Store(env("DB_PATH", "payments.db"));
        var provider = new Provider(env("PROVIDER_URL", "http://127.0.0.1:9090"), number("PROVIDER_TIMEOUT_MS", 300), number("MAX_INFLIGHT", 8));
        var service = new PaymentService(store, provider); var json = new ObjectMapper(); var metrics = new Metrics(); var reconciling = new AtomicBoolean();
        var server = HttpServer.create(new InetSocketAddress("127.0.0.1", number("PORT", 8080)), 64);
        server.setExecutor(Executors.newVirtualThreadPerTaskExecutor());
        server.createContext("/", exchange -> {
            long start = System.nanoTime(); String requestId = UUID.randomUUID().toString();
            int code = 404; String route = "other"; Object result = Map.of("error", "not_found"); boolean plain = false;
            String path = exchange.getRequestURI().getPath(), method = exchange.getRequestMethod(); var headers = exchange.getRequestHeaders();
            try {
                if (method.equals("GET") && path.equals("/health")) { route = "health"; code = 200; result = Map.of("status", "ok"); }
                else if (method.equals("GET") && path.equals("/metrics")) { route = "metrics"; code = 200; plain = true; result = metrics.render(provider, store.unknownCount()); }
                else if (path.startsWith("/admin/")) {
                    route = "admin";
                    if (!env("ADMIN_TOKEN", "local-admin").equals(headers.getFirst("X-Admin-Token"))) { code = 403; result = Map.of("error", "forbidden"); }
                    else if (method.equals("GET") && path.equals("/admin/breaks")) { code = 200; result = store.breaks(); }
                    else if (method.equals("POST") && path.equals("/admin/reconcile")) {
                        if (!reconciling.compareAndSet(false, true)) { code = 429; result = Map.of("error", "reconciliation_busy"); }
                        else { try { result = service.reconcile(); code = 200; } finally { reconciling.set(false); } }
                    }
                } else if (method.equals("POST") && path.equals("/payments")) {
                    route = "create"; code = 400; result = Map.of("error", "invalid_request");
                    byte[] data = exchange.getRequestBody().readNBytes(4097);
                    com.fasterxml.jackson.databind.JsonNode value = null;
                    try { if (data.length <= 4096) value = json.readTree(data); } catch (Exception ignored) { }
                    if (value != null && value.isObject() && value.size() == 2 && value.has("amount") && value.has("currency") &&
                        value.get("amount").isIntegralNumber() && value.get("amount").canConvertToLong() && value.get("amount").asLong() >= 1 && value.get("amount").asLong() <= 1_000_000_000 &&
                        value.get("currency").isTextual() && Set.of("JPY", "USD").contains(value.get("currency").asText()) && identifier(headers.getFirst("X-Merchant-Id")) && identifier(headers.getFirst("Idempotency-Key"))) {
                        if (provider.active() >= provider.capacity) { code = 429; result = Map.of("error", "capacity"); }
                        else { var response = service.create(headers.getFirst("X-Merchant-Id"), headers.getFirst("Idempotency-Key"), value.get("amount").asLong(), value.get("currency").asText()); code = response.code(); result = response.body(); }
                    }
                } else if (method.equals("GET") && path.matches("/payments/[a-f0-9-]{36}")) {
                    route = "get"; var p = store.get(path.substring("/payments/".length()));
                    if (p != null && p.merchant().equals(headers.getFirst("X-Merchant-Id"))) { code = 200; result = p.view(); }
                }
            } catch (Exception error) { code = 500; plain = false; result = Map.of("error", "storage_or_internal_error"); }
            var responseHeaders = exchange.getResponseHeaders(); responseHeaders.set("Content-Type", plain ? "text/plain; version=0.0.4" : "application/json"); responseHeaders.set("X-Request-Id", requestId);
            if (code == 202 || code == 429) responseHeaders.set("Retry-After", "1");
            String paymentId = result instanceof Map<?, ?> map && map.containsKey("id") ? map.get("id").toString() : "";
            if (!paymentId.isEmpty()) responseHeaders.set("Location", "/payments/" + paymentId);
            byte[] bytes = plain ? result.toString().getBytes(StandardCharsets.UTF_8) : json.writeValueAsBytes(result);
            try { exchange.sendResponseHeaders(code, bytes.length); exchange.getResponseBody().write(bytes); } finally { exchange.close(); }
            double elapsed = (System.nanoTime() - start) / 1e9; metrics.observe(route, code, elapsed);
            System.out.println(json.writeValueAsString(Map.of("event", "http_request", "request_id", requestId, "route", route, "status", code, "duration_ms", (long) (elapsed * 1000), "payment_id", paymentId)));
        });
        Runtime.getRuntime().addShutdownHook(new Thread(() -> { server.stop(1); try { store.close(); } catch (Exception ignored) { } }));
        server.start();
    }
}
