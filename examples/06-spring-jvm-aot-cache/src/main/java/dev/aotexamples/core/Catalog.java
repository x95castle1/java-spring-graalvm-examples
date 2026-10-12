package dev.aotexamples.core;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.Map;

public final class Catalog {
    private final Map<Integer, Product> products;

    public Catalog() {
        var stream = Catalog.class.getResourceAsStream("/catalog.csv");
        if (stream == null) {
            throw new IllegalStateException("Missing catalog.csv resource");
        }
        var loaded = new LinkedHashMap<Integer, Product>();
        try (var reader = new BufferedReader(new InputStreamReader(stream, StandardCharsets.UTF_8))) {
            for (String line; (line = reader.readLine()) != null;) {
                if (line.isBlank()) {
                    continue;
                }
                var fields = line.split(",", -1);
                if (fields.length != 3) {
                    throw new IllegalStateException("Invalid catalog row");
                }
                var product = new Product(Integer.parseInt(fields[0]), fields[1], Long.parseLong(fields[2]));
                if (loaded.putIfAbsent(product.id(), product) != null) {
                    throw new IllegalStateException("Duplicate product: " + product.id());
                }
            }
        } catch (IOException exception) {
            throw new IllegalStateException("Cannot read catalog", exception);
        }
        products = Map.copyOf(loaded);
    }

    public Product product(int id) {
        var product = products.get(id);
        if (product == null) {
            throw new IllegalArgumentException("Unknown product: " + id);
        }
        return product;
    }

    public int size() {
        return products.size();
    }
}
