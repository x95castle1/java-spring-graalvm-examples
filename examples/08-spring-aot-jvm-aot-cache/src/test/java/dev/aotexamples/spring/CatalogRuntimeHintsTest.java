package dev.aotexamples.spring;

import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.assertFalse;

import org.junit.jupiter.api.Test;
import org.springframework.aot.hint.RuntimeHints;
import org.springframework.aot.hint.predicate.RuntimeHintsPredicates;

class CatalogRuntimeHintsTest {
    @Test
    void registersResourceAndDynamicallySelectedPolicyMethod() throws NoSuchMethodException {
        var hints = new RuntimeHints();
        new CatalogRuntimeHints().registerHints(hints, getClass().getClassLoader());
        assertTrue(RuntimeHintsPredicates.resource().forResource("catalog.csv").test(hints));
        assertTrue(RuntimeHintsPredicates.reflection().onMethodInvocation(DiscountPolicy.class.getMethod("name")).test(hints));
        assertFalse(RuntimeHintsPredicates.reflection().onMethodInvocation(DiscountPolicy.class.getMethod("unregisteredName")).test(hints));
    }
}
