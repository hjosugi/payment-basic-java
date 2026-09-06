package dev.payment;

import java.util.*;

public final class Metrics {
    private static final double[] BOUNDS = {.005, .01, .05, .1, .5, 1, 5};
    private final Map<String, Long> counts = new TreeMap<>();
    private final Map<String, double[]> hist = new TreeMap<>();
    public synchronized void observe(String route, int code, double seconds) {
        if (List.of("health", "metrics").contains(route)) return;
        counts.merge("route=\"" + route + "\",status=\"" + code + "\"", 1L, Long::sum);
        String outcome = code >= 500 ? "error" : code == 202 ? "pending" : code >= 400 ? "rejected" : "ok";
        var h = hist.computeIfAbsent(outcome, key -> new double[9]);
        for (int i = 0; i < BOUNDS.length; i++) if (seconds <= BOUNDS[i]) h[i]++;
        h[7]++; h[8] += seconds;
    }
    public synchronized String render(Provider provider, int unresolved) {
        var text = new StringBuilder();
        counts.forEach((k, v) -> text.append("payment_http_requests_total{").append(k).append("} ").append(v).append('\n'));
        hist.forEach((outcome, h) -> {
            for (int i = 0; i < BOUNDS.length; i++) text.append("payment_http_duration_seconds_bucket{outcome=\"").append(outcome).append("\",le=\"").append(BOUNDS[i]).append("\"} ").append((long) h[i]).append('\n');
            text.append("payment_http_duration_seconds_bucket{outcome=\"").append(outcome).append("\",le=\"+Inf\"} ").append((long) h[7]).append('\n');
            text.append("payment_http_duration_seconds_count{outcome=\"").append(outcome).append("\"} ").append((long) h[7]).append('\n');
            text.append("payment_http_duration_seconds_sum{outcome=\"").append(outcome).append("\"} ").append(h[8]).append('\n');
        });
        return text + "payment_provider_inflight " + provider.active() + "\npayment_provider_capacity " + provider.capacity + "\npayment_circuit_open " + provider.breaker.isOpen() + "\npayment_unresolved " + unresolved + "\n";
    }
}
