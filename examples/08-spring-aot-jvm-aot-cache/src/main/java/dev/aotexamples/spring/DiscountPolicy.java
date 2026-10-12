package dev.aotexamples.spring;

public final class DiscountPolicy {
    private DiscountPolicy() { }

    public static String name() {
        return "ten-percent";
    }
    // Deliberately unregistered: packaged checks use this to diagnose missing metadata.
    public static String unregisteredName() {
        return "ten-percent";
    }
}

