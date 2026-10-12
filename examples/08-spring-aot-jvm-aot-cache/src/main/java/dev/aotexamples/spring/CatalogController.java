package dev.aotexamples.spring;

import dev.aotexamples.core.Catalog;
import dev.aotexamples.core.Product;
import dev.aotexamples.core.Workload;
import java.util.Map;
import org.springframework.aot.AotDetector;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.boot.SpringBootVersion;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@RestController
public class CatalogController {
    private final Catalog catalog;
    private final Workload workload;
    private final Readiness readiness;
    private final String label;

    public CatalogController(Catalog catalog, Workload workload, Readiness readiness,
                             @Qualifier("catalogLabel") String label) {
        this.catalog = catalog;
        this.workload = workload;
        this.readiness = readiness;
        this.label = label;
    }

    @GetMapping("/ready")
    public ResponseEntity<ReadyResponse> ready() {
        var result = new ReadyResponse(readiness.isReady(), catalog.size(), label,
                AotDetector.useGeneratedArtifacts(),
                AotDetector.useGeneratedArtifacts()
                        || CatalogApplication.class.getResource("CatalogApplication__ApplicationContextInitializer.class") != null,
                System.getProperty("java.version"), SpringBootVersion.getVersion());
        return ResponseEntity.status(readiness.isReady() ? HttpStatus.OK : HttpStatus.SERVICE_UNAVAILABLE).body(result);
    }

    @GetMapping("/products/{id}")
    public Product product(@PathVariable int id) {
        try {
            return catalog.product(id);
        } catch (IllegalArgumentException exception) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, exception.getMessage());
        }
    }

    @PostMapping("/quotes")
    public Workload.Quote quote(@RequestBody QuoteRequest request) {
        if (request.quantities() == null || request.quantities().size() > 100
                || request.quantities().entrySet().stream().anyMatch(item -> item.getKey() == null || item.getValue() == null)) {
            throw new IllegalArgumentException("Provide a quantities map with at most 100 items and non-null values");
        }
        return workload.quote(request.quantities());
    }

    @GetMapping("/compute")
    public ComputeResponse compute(@RequestParam(defaultValue = "100000") int iterations) {
        return new ComputeResponse(iterations, Workload.compute(iterations));
    }

    @GetMapping("/native-metadata")
    public Map<String, Object> metadata() throws ReflectiveOperationException {
        String className = System.getProperty("catalog.policyClass", "dev.aotexamples.spring.DiscountPolicy");
        String methodName = System.getProperty("catalog.policyMethod", "name");
        var policy = Class.forName(className).getMethod(methodName).invoke(null);
        return Map.of("policy", policy, "catalogResource", Catalog.class.getResource("/catalog.csv") != null);
    }

    public record QuoteRequest(Map<Integer, Integer> quantities) { }
    public record ComputeResponse(int iterations, long checksum) { }
    public record ReadyResponse(boolean ready, int productCount, String catalogLabel,
                                boolean springAot, boolean generatedInitializer,
                                String javaVersion, String springBootVersion) { }
}
