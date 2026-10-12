package dev.aotexamples.core;

public record Product(int id, String name, long priceCents) {
    public Product {
        if (id < 1 || name == null || name.isBlank() || priceCents < 0) {
            throw new IllegalArgumentException("Invalid product");
        }
    }
}
