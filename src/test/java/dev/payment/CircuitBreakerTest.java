package dev.payment;

import org.junit.jupiter.api.Test;
import java.util.concurrent.atomic.AtomicLong;
import static org.junit.jupiter.api.Assertions.*;

class CircuitBreakerTest {
    @Test void staleCompletionAndSingleProbe() {
        var now = new AtomicLong(); var b = new CircuitBreaker(now::get); int stale = b.enter();
        for (int i = 0; i < 3; i++) b.complete(b.enter(), false);
        b.complete(stale, true); assertThrows(IllegalStateException.class, b::enter);
        now.set(2_000_000_000L); int probe = b.enter(); assertThrows(IllegalStateException.class, b::enter);
        b.complete(probe, true); assertEquals(0, b.isOpen());
    }
    @Test void failedProbe() {
        var now = new AtomicLong(); var b = new CircuitBreaker(now::get);
        for (int i = 0; i < 3; i++) b.complete(b.enter(), false);
        now.set(2_000_000_000L); b.complete(b.enter(), false); assertThrows(IllegalStateException.class, b::enter);
    }
}
