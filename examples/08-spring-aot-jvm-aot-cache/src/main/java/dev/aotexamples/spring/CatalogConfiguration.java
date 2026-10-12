package dev.aotexamples.spring;

import dev.aotexamples.core.Catalog;
import dev.aotexamples.core.Workload;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Profile;

@Configuration(proxyBeanMethods = false)
public class CatalogConfiguration {
    @Bean
    public Catalog catalog() {
        return new Catalog();
    }

    @Bean
    public Workload workload(Catalog catalog) {
        return new Workload(catalog);
    }

    @Bean("catalogLabel")
    @Profile("!alternate")
    public String defaultLabel() {
        return "Catalog";
    }

    @Bean("catalogLabel")
    @Profile("alternate")
    public String alternateLabel() {
        return "Alternate catalog";
    }
}
