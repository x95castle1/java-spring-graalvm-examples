package dev.aotexamples.spring;

import ch.qos.logback.classic.BasicConfigurator;
import ch.qos.logback.classic.util.DefaultJoranConfigurator;
import org.springframework.aot.hint.ExecutableMode;
import org.springframework.aot.hint.MemberCategory;
import org.springframework.aot.hint.RuntimeHints;
import org.springframework.aot.hint.RuntimeHintsRegistrar;

public final class CatalogRuntimeHints implements RuntimeHintsRegistrar {
    @Override
    public void registerHints(RuntimeHints hints, ClassLoader classLoader) {
        hints.resources().registerPattern("catalog.csv");
        // Logback selects these configurators by name before Boot applies logging settings.
        hints.reflection().registerType(BasicConfigurator.class, MemberCategory.INVOKE_PUBLIC_CONSTRUCTORS);
        hints.reflection().registerType(DefaultJoranConfigurator.class, MemberCategory.INVOKE_PUBLIC_CONSTRUCTORS);
        try {
            hints.reflection().registerMethod(DiscountPolicy.class.getMethod("name"), ExecutableMode.INVOKE);
        } catch (NoSuchMethodException exception) {
            throw new IllegalStateException("Discount policy method changed", exception);
        }
    }
}
