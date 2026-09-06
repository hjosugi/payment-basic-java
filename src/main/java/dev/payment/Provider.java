package dev.payment;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.ByteArrayOutputStream;
import java.net.URI;
import java.net.http.*;
import java.nio.ByteBuffer;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.concurrent.*;

public final class Provider {
    public final CircuitBreaker breaker = new CircuitBreaker();
    public final int capacity;
    private final Semaphore slots;
    private final HttpClient client;
    private final ObjectMapper json = new ObjectMapper();
    private final String base;
    private final int timeout;
    public Provider(String base, int timeout, int capacity) {
        this.base = base; this.timeout = timeout; this.capacity = capacity;
        slots = new Semaphore(capacity);
        client = HttpClient.newBuilder().connectTimeout(Duration.ofMillis(timeout)).followRedirects(HttpClient.Redirect.NEVER).build();
    }
    public int active() { return capacity - slots.availablePermits(); }
    public JsonNode call(String method, Payment p) throws Exception {
        if (!slots.tryAcquire()) throw new IllegalStateException("capacity");
        Integer token = null; boolean healthy = false;
        CompletableFuture<HttpResponse<byte[]>> future = null;
        try {
            token = breaker.enter();
            var body = method.equals("POST") ? HttpRequest.BodyPublishers.ofString(json.writeValueAsString(Map.of("amount", p.amount(), "currency", p.currency()))) : HttpRequest.BodyPublishers.noBody();
            var request = HttpRequest.newBuilder(URI.create(base + "/charges/" + p.id()))
                .timeout(Duration.ofMillis(timeout)).header("Content-Type", "application/json").header("Idempotency-Key", p.id()).method(method, body).build();
            future = client.sendAsync(request, info -> new LimitedBody());
            // This deadline includes the complete response body, not only the headers.
            var response = future.get(timeout, TimeUnit.MILLISECONDS);
            if (method.equals("GET") && response.statusCode() == 404) { healthy = true; return null; }
            if (response.statusCode() != 200) throw new IllegalStateException("provider_http");
            JsonNode value = json.readTree(response.body());
            if (value == null || !List.of("SUCCEEDED", "DECLINED").contains(value.path("status").asText())) throw new IllegalStateException("provider_payload");
            healthy = true; return value;
        } finally {
            if (future != null && !future.isDone()) future.cancel(true);
            slots.release(); if (token != null) breaker.complete(token, healthy);
        }
    }
    private static final class LimitedBody implements HttpResponse.BodySubscriber<byte[]> {
        private final CompletableFuture<byte[]> done = new CompletableFuture<>();
        private final ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        private Flow.Subscription subscription;
        public CompletionStage<byte[]> getBody() { return done; }
        public void onSubscribe(Flow.Subscription s) { subscription = s; s.request(1); }
        public void onNext(List<ByteBuffer> chunks) {
            for (var chunk : chunks) {
                if (bytes.size() + chunk.remaining() > 16384) { subscription.cancel(); done.completeExceptionally(new IllegalStateException("provider_body")); return; }
                byte[] data = new byte[chunk.remaining()]; chunk.get(data); bytes.writeBytes(data);
            }
            subscription.request(1);
        }
        public void onError(Throwable error) { done.completeExceptionally(error); }
        public void onComplete() { done.complete(bytes.toByteArray()); }
    }
}
