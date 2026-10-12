package dev.aotexamples.core;

import java.util.Map;

public final class Workload {
    public static final int DEFAULT_ITERATIONS = 100_000;
    public static final int MAX_ITERATIONS = 10_000_000;
    private final Catalog catalog;

    public Workload(Catalog catalog) {
        this.catalog = catalog;
    }

    public Quote quote(Map<Integer, Integer> quantities) {
        if (quantities.isEmpty()) {
            throw new IllegalArgumentException("A quote needs at least one item");
        }
        long subtotal = 0;
        for (var item : quantities.entrySet()) {
            if (item.getValue() < 1 || item.getValue() > 100) {
                throw new IllegalArgumentException("Quantity must be between 1 and 100");
            }
            subtotal = Math.addExact(subtotal,
                    Math.multiplyExact(catalog.product(item.getKey()).priceCents(), item.getValue()));
        }
        long discount = subtotal >= 20_000 ? subtotal / 10 : 0;
        return new Quote(subtotal, discount, subtotal - discount);
    }

    public static long compute(int iterations) {
        if (iterations < 1 || iterations > MAX_ITERATIONS) {
            throw new IllegalArgumentException("Iterations must be between 1 and " + MAX_ITERATIONS);
        }
        long checksum = 0x1234abcdL;
        for (int i = 0; i < iterations; i++) {
            checksum ^= checksum << 13;
            checksum ^= checksum >>> 7;
            checksum ^= checksum << 17;
        }
        return checksum;
    }

    public record Quote(long subtotalCents, long discountCents, long totalCents) {
    }
}
