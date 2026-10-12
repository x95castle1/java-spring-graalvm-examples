package dev.aotexamples.core;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import java.util.Map;
import org.junit.jupiter.api.Test;

class WorkloadTest {
    private final Catalog catalog = new Catalog();
    private final Workload workload = new Workload(catalog);

    @Test
    void loadsPackagedCatalog() {
        assertEquals(8, catalog.size());
        assertEquals(new Product(1, "Keyboard", 9900), catalog.product(1));
    }

    @Test
    void appliesDiscountAtTheThreshold() {
        assertEquals(new Workload.Quote(22_300, 2230, 20_070), workload.quote(Map.of(1, 2, 2, 1)));
        assertEquals(new Workload.Quote(9900, 0, 9900), workload.quote(Map.of(1, 1)));
        assertEquals(new Workload.Quote(20_000, 2000, 18_000), workload.quote(Map.of(2, 8)));
    }

    @Test
    void rejectsInvalidOrders() {
        assertThrows(IllegalArgumentException.class, () -> workload.quote(Map.of()));
        assertThrows(IllegalArgumentException.class, () -> workload.quote(Map.of(99, 1)));
        assertThrows(IllegalArgumentException.class, () -> workload.quote(Map.of(1, 0)));
        assertThrows(IllegalArgumentException.class, () -> workload.quote(Map.of(1, 101)));
    }

    @Test
    void producesTheExpectedChecksum() {
        assertEquals(325410109145977306L, Workload.compute(1));
        assertEquals(-7896971328211040135L, Workload.compute(2));
        assertEquals(-7520082499104634107L, Workload.compute(100_000));
    }

    @Test
    void rejectsUnboundedComputeWork() {
        assertThrows(IllegalArgumentException.class, () -> Workload.compute(0));
        assertThrows(IllegalArgumentException.class, () -> Workload.compute(Workload.MAX_ITERATIONS + 1));
    }
}
