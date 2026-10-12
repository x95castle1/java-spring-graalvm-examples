package dev.aotexamples.cli;

import dev.aotexamples.core.Catalog;
import dev.aotexamples.core.Workload;
import java.util.Locale;
import java.util.Map;

public final class CatalogCli {
    private CatalogCli() {
    }

    public static void main(String[] args) {
        try {
            if (args.length == 1 && "--help".equals(args[0])) {
                System.out.println("Usage: java -jar plain-java.jar [--iterations 1..10000000]");
                return;
            }
            int iterations = Workload.DEFAULT_ITERATIONS;
            if (args.length != 0) {
                if (args.length != 2 || !"--iterations".equals(args[0])) {
                    throw new IllegalArgumentException("Expected --iterations NUMBER, or --help");
                }
                iterations = Integer.parseInt(args[1]);
            }
            var catalog = new Catalog();
            var quote = new Workload(catalog).quote(Map.of(1, 2, 2, 1));
            long checksum = Workload.compute(iterations);
            System.out.printf(Locale.ROOT,
                    "{\"application\":\"catalog-cli\",\"javaVersion\":\"%s\","
                            + "\"iterations\":%d,\"productCount\":%d,\"subtotalCents\":%d,"
                            + "\"discountCents\":%d,\"totalCents\":%d,\"checksum\":%d}%n",
                    System.getProperty("java.version"), iterations, catalog.size(),
                    quote.subtotalCents(), quote.discountCents(), quote.totalCents(), checksum);
        } catch (IllegalArgumentException exception) {
            System.err.println(exception.getMessage());
            System.exit(2);
        }
    }
}
