package dev.payment;

import java.util.function.LongSupplier;

public final class CircuitBreaker {
    private int failures, generation;
    private long openedAt;
    private boolean open, probe;
    private final LongSupplier clock;
    public CircuitBreaker() { this(System::nanoTime); }
    public CircuitBreaker(LongSupplier clock) { this.clock = clock; }
    public synchronized int enter() {
        if (open) {
            if (clock.getAsLong() - openedAt < 1_000_000_000L || probe) throw new IllegalStateException("circuit_open");
            probe = true;
        }
        return generation;
    }
    public synchronized void complete(int token, boolean healthy) {
        if (token != generation) return;
        if (healthy) { failures = 0; open = false; probe = false; }
        else if (probe || ++failures >= 3) {
            open = true; openedAt = clock.getAsLong(); probe = false; generation++;
        }
    }
    public synchronized int isOpen() { return open ? 1 : 0; }
}
