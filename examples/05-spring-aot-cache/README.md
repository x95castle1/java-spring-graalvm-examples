# 05 — Spring AOT on the JVM

Despite the directory name, Spring AOT generates initialization code rather than a HotSpot cache archive.

This standalone Spring Boot 4.1.1 project processes its catalog application during the build and runs the generated initialization code on HotSpot Java 25. The benchmark compares Spring AOT disabled and enabled using this example's same extracted JAR, libraries, JVM settings, and container limits. It owns its source, fixture, tests, Gradle wrapper, build scripts, Compose file, and Dockerfiles, independently of example 04.

## Setup and changes from the baseline

- **Setup:** This independent Gradle project owns the Spring catalog service and uses Spring Boot's AOT build plugin to generate initialization code during `processAot`. Compose packages the processed application and runs it on HotSpot Java 25 with Spring AOT enabled.
- **Baseline:** Example 04 defines the ordinary Spring service. To isolate execution of generated initialization code, this benchmark uses its own identical processed JAR and libraries for both modes, with `spring.aot.enabled` switched off or on. JVM, G1, heap, and container limits stay the same.
- **What changes:** The build adds generated Spring initialization and bean-registration code; execution opts into that code with `-Dspring.aot.enabled=true`. Despite the directory name, this creates no HotSpot `.aot` cache archive and performs no GraalVM native compilation.
- **Why enable it:** Move Spring bean analysis and generation of initialization code into the build, reducing the discovery work needed when the application starts. The Java application still runs on HotSpot and uses runtime JIT compilation.
- **Expected result:** The same HTTP contract with potentially faster readiness and lower startup memory. The AOT mode uses beans selected by the build-time profile, which the example checks explicitly. Packaging does more work and includes generated code. Faster startup does not guarantee better request latency; the optional load suite measures that separately.

## Test the application and stop

Run from the repository root with Docker running. `make test-app` opens fzf; select `05-spring-aot-cache`:

```sh
make status EXAMPLE=05
make build EXAMPLE=05
make test-app EXAMPLE=05
make clean EXAMPLE=05
```

The service starts detached and `make test-app` waits for readiness. Stop another service using port 8080 before starting it, or use `PORT=8085`. `make clean` preserves results and Gradle's cache volume.

Equivalent Compose commands:

```sh
docker compose -f examples/05-spring-aot-cache/compose.yaml --profile spring-aot up --build --detach --wait spring-aot
docker compose -f examples/05-spring-aot-cache/compose.yaml --profile spring-aot down
```

`/ready` reports:

```json
{"ready":true,"productCount":8,"catalogLabel":"Catalog","springAot":true,"generatedInitializer":true,"javaVersion":"25.0.4.1","springBootVersion":"4.1.1"}
```

## Application checks

`make test-app EXAMPLE=05` builds and starts this service, waits for readiness, then prints curl commands and formatted JSON and verifies readiness, product, quote and computation responses. Run the same command again to repeat the checks. The app stays running until `make clean`, so you can also execute the printed curl commands yourself. Omit `EXAMPLE` for fzf selection; the picker offers application examples 01–08. Use `PORT` consistently when choosing another host port; `ITERATIONS` changes the sample computation.

## HTTP examples

```sh
curl -s http://localhost:8080/products/1
curl -s -H 'Content-Type: application/json' \
  -d '{"quantities":{"1":2,"2":1}}' http://localhost:8080/quotes
curl -s 'http://localhost:8080/compute?iterations=100000'
```

These return the Keyboard product (9900 cents), the fixed quote (22300 subtotal, 2230 discount, 20070 total), and checksum `-7520082499104634107`. `/ready` returns 503 until the application-ready event. Missing products return 404; malformed/invalid quotes and compute inputs return 400. The source and HTTP contract match examples 04 and 06.

## Build and generated artifacts

The [Gradle build](build.gradle) applies Spring Boot's `org.springframework.boot.aot` plugin, which runs `processAot` during packaging. The [Dockerfile](containers/application.Dockerfile) builds with `./gradlew build`, then extracts the JAR. Runtime enables generated initialization with `-Dspring.aot.enabled=true`. Both JVM comparison modes use this AOT-processed JAR. [Spring AOT Gradle configuration](https://docs.spring.io/spring-boot/gradle-plugin/aot.html), [JVM execution of Spring AOT](https://docs.spring.io/spring-boot/reference/packaging/aot.html).

Generated Java is under `build/generated/aotSources/` in a local build, including `CatalogApplication__ApplicationContextInitializer` and bean registration/supplier code. The benchmark verifies the application initializer is present and saves the whole `build/generated/` tree, including application and test AOT outputs as `spring-aot-sources.zip` in results. The whole Gradle packaging cost is reported separately from runtime gains; it includes tests and AOT processing, and may include uncached downloads. It does not isolate the incremental cost of AOT alone.

The service includes a concrete profile example in [CatalogConfiguration](src/main/java/dev/aotexamples/spring/CatalogConfiguration.java). The `alternate` profile selects the `Alternate catalog` label on an ordinary JVM. AOT processing uses the default profile and fixes the bean graph, so the AOT mode retains the `Catalog` bean when `alternate` is selected at runtime. The packaged [profile checks](../../benchmark/http_smoke.py) verify both cases. [Spring AOT profile restrictions](https://docs.spring.io/spring-boot/reference/packaging/aot.html).

To try the AOT case after stopping the detached service:

```sh
make clean EXAMPLE=05
docker compose -f examples/05-spring-aot-cache/compose.yaml --profile spring-aot \
  run --rm --service-ports -e SPRING_PROFILES_ACTIVE=alternate spring-aot
```

From another terminal, `curl -s http://localhost:8080/ready` still shows `catalogLabel: "Catalog"`. Stop the foreground service with Ctrl+C.

## Benchmark

```sh
make bench EXAMPLE=05
make bench EXAMPLE=05 RUNS=10
make bench EXAMPLE=05 SUITE=load
make bench EXAMPLE=05 SUITE=all
```

Modes are `baseline` (Spring AOT disabled) and `spring-aot` (enabled). Both use one CPU, 512 MiB container memory, G1 GC, and a 256 MiB maximum heap. Default CDS stays enabled; application JVM caches are absent. The default startup suite performs two unmeasured processes per mode, then 30 measured processes per mode. Each round shuffles mode order with seed 42, with an untimed 100 ms launch interval.

Tables show readiness median/p95, first quote response, readiness RSS, sample counts, and reductions against the baseline. Raw records also include first product response, idle RSS, peak process RSS, and startup CPU throttling. Readiness polling is every 20 ms; uncertainty includes the polling interval and probe time. First product/quote timestamps are cumulative since process launch, with requests made sequentially after readiness. Peak RSS includes the whole process and functional verification through shutdown. The OS page cache is ordinary. Container launch and build/diagnostic checks are excluded from startup measurements.

Optional load tests use five repetitions per mode, each with 30 seconds of warmup and 60 seconds at 100 requests/second. A separate Python process rotates product/quote/compute requests on one keep-alive connection, with its own two-CPU container allowance. Every response must be correct. Tables show completed requests/second, latency percentiles and RSS after load. This compares latency at a fixed offered rate rather than maximum capacity. Errors, timeouts and an unsustained rate stop the comparison.

For a short check, add `LOAD_RUNS=1 LOAD_WARMUP=2 LOAD_SECONDS=5 RATE=50`. Short checks do not establish steady-state behavior. Change CPU work using `ITERATIONS=1000000`.

Evidence is permanently ignored under `results/05-spring-aot-cache/<UTC timestamp>/`: HTML, JSON/CSV, environment/deployment hashes, generated-source ZIP, packaging log, process/application logs, and load-request JSON. Artifact size includes JAR/libraries, excluding the JVM, base image and source evidence. Build-layer reuse may reuse preparation costs. Any verification failure writes `artifacts/failure.json` without a successful summary.

Memory columns report medians across measured processes or load repetitions, in MiB. Readiness RSS is sampled when the service becomes ready; peak RSS covers the process through shutdown, including functional verification. Load RSS is sampled after each measured load window. RSS includes heap and runtime overhead, rather than the heap limit or total container usage.

Each run directory contains `report.html` and an `artifacts/` subdirectory for all supporting evidence. The report links to the artifacts and its path is printed at completion.

## Observed comparison

A Gradle-built run on October 9, 2026 used Linux aarch64 containers on Docker Desktop with the toolchains and limits above, 100,000 compute iterations, two unmeasured startups and 30 measured startups per mode. Both modes used the same AOT-processed deployment.

| Mode | Readiness median | Readiness p95 | First quote median since launch | Median readiness RSS | Median peak RSS | Readiness reduction | RSS reduction |
| --- | --- | --- | --- | --- | --- | --- | --- |
| baseline | 2053.81 ms | 2306.46 ms | 2133.13 ms | 146.07 MiB | 151.55 MiB | +0.0% | +0.0% |
| spring-aot | 1691.30 ms | 1849.99 ms | 1770.81 ms | 133.66 MiB | 136.75 MiB | +17.7% | +8.5% |

Three short load repetitions per mode each used 10 seconds of warmup and 10 seconds at 100 requests/second. The values below are medians across repetitions:

| Mode | Requests/second | Latency p95 | Median RSS after load |
| --- | --- | --- | --- |
| baseline | 100.00 | 2.95 ms | 176.07 MiB |
| spring-aot | 99.99 | 2.89 ms | 151.15 MiB |

All 6,000 measured responses passed verification, and neither client's measured windows had CPU throttling. The latency difference is small; these short runs do not establish steady-state capacity. Gradle packaging, tests and Spring AOT processing took 28.74 seconds, with 482.84 MiB process/child peak RSS. Deployment JAR/libraries totalled 18.88 MiB. Packaging cost may be reused by Docker and does not isolate AOT's incremental cost. Evidence is ignored at `results/05-spring-aot-cache/20261009T155348.841230Z/`.

## Build tests and local development

```sh
make build EXAMPLE=05
```

Image builds run the five workload tests and five Java HTTP tests and generate Spring AOT initialization. `make test-app EXAMPLE=05` verifies the packaged API with Spring AOT enabled; `/ready` must confirm generated initialization is active. The benchmark verifies both execution modes.

For optional local Java 25 development:

```sh
cd examples/05-spring-aot-cache
./gradlew build
java -Xmx256m -XX:+UseG1GC -Dspring.aot.enabled=true -jar build/libs/catalog-service.jar
```
