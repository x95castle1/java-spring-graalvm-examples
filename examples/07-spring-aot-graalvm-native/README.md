# 07 — Spring AOT with GraalVM Native Image

This standalone Gradle project compiles its Spring Boot 4.1.1 catalog service into a Linux native executable. Spring AOT generates initialization code and runtime hints before GraalVM compiles the application. The production container runs without Java installed. Its benchmark compares ordinary JVM execution (Spring AOT disabled) against native execution using this project's own processed deployment as the input.

## Setup and changes from the baseline

- **Setup:** This independent Gradle project generates Spring AOT initialization and compiles its Spring Boot catalog service with GraalVM Native Image. Compose runs the Linux executable as user `10001` in an Oracle Linux production image without Java. Runtime hints include the catalog resource and dynamic reflection used by `/native-metadata`.
- **Baseline:** Example 04 establishes ordinary Spring HTTP execution. This project's benchmark runs its own processed JAR on HotSpot with Spring AOT disabled, then compares the native executable compiled from that deployment. Both receive the same application resource limits and heap budget; their collectors and Java patch versions differ.
- **What changes:** The build applies Native Build Tools, generates Spring initialization and reachability metadata, and compiles reachable code into `/app/catalog-service`. Production executes that binary instead of a JAR. Spring AOT is active in native execution, and explicit hints support the reflection/resource path. No HotSpot AOT cache is used.
- **Why enable it:** Prepare Spring initialization and application machine code before deployment so the service can start with much less runtime initialization work. The metadata example demonstrates what a dynamic code path needs when compiled into a native executable.
- **Expected result:** The same catalog HTTP contract with substantially faster readiness and potentially lower process memory for this service. Native builds require more time and memory, and dynamic reflection needs appropriate metadata. The executable targets a specific OS and architecture. Request latency is measured separately, and the comparison includes the effects of Serial GC and the native runtime as well as Spring AOT.

## Test the application and stop

From the repository root with Docker running:

```sh
make status EXAMPLE=07
make build EXAMPLE=07
make test-app EXAMPLE=07
make clean EXAMPLE=07
```

Omit `EXAMPLE` to select with fzf. The first build includes native compilation and may take several minutes. Provide Docker with at least 8 GiB of available memory; the compiler uses two threads and a 4 GiB maximum heap. Build layers are reused when inputs have not changed. `PORT=8087` changes the host port. Cleanup preserves results and Gradle's cache volume.

Equivalent Compose commands:

```sh
docker compose -f examples/07-spring-aot-graalvm-native/compose.yaml --profile spring-native up --build --detach --wait spring-native
docker compose -f examples/07-spring-aot-graalvm-native/compose.yaml --profile '*' down --remove-orphans
```

The service has one CPU and 512 MiB container memory. Native execution uses Serial GC and a 256 MiB maximum heap; the JVM comparison uses G1 and the same heap limit. `/ready` reports `springAot: true`, `generatedInitializer: true`, eight products and the exact Java/Boot versions. Native production runs as user 10001 on Oracle Linux.

## Application checks

`make test-app EXAMPLE=07` builds and starts this service, waits for readiness, then prints curl commands and formatted JSON and verifies readiness, product, quote and computation responses. It also checks the resource/reflection endpoint. Run the same command again to repeat the checks. The app stays running until `make clean`, so you can also execute the printed curl commands yourself. Omit `EXAMPLE` for fzf selection; the picker offers application examples 01–08. Use `PORT` consistently when choosing another host port; `ITERATIONS` changes the sample computation.

## HTTP examples and runtime hints

```sh
curl -s http://localhost:8080/products/1
curl -s -H 'Content-Type: application/json' \
  -d '{"quantities":{"1":2,"2":1}}' http://localhost:8080/quotes
curl -s 'http://localhost:8080/compute?iterations=100000'
curl -s http://localhost:8080/native-metadata
```

Responses match earlier examples: Keyboard at 9900 cents, quote total 20070 cents, and checksum `-7520082499104634107`. Invalid inputs return 400 and absent products/routes return 404. The metadata endpoint returns `{"policy":"ten-percent","catalogResource":true}`.

[CatalogRuntimeHints](src/main/java/dev/aotexamples/spring/CatalogRuntimeHints.java) registers `catalog.csv` and reflective invocation of `DiscountPolicy.name()`. It also registers constructors for the two Logback configurators selected by class name. The endpoint selects its class and method through runtime system properties, making the reflection registration meaningful. [CatalogApplication](src/main/java/dev/aotexamples/spring/CatalogApplication.java) imports the registrar. Spring generates JSON/record and framework hints during `processAot`. The default profile's bean selection is fixed into generated initialization; packaged checks show ordinary JVM execution can select the alternate profile while native execution retains the build-time beans.

`DiscountPolicy.unregisteredName()` intentionally has no invocation hint. Packaged checks select it with `-Dcatalog.policyMethod=unregisteredName` and require HTTP 500 with a `MissingReflectionRegistrationError` naming the omitted method, then verify the normal executable again. The same unregistered method succeeds on the JVM, establishing that the native failure comes from the missing invocation hint. This diagnostic stays outside timing. [GraalVM reachability metadata](https://www.graalvm.org/jdk25/reference-manual/native-image/metadata/).

## Build and benchmark

```sh
make bench EXAMPLE=07
make bench EXAMPLE=07 SUITE=all
make bench EXAMPLE=07 SUITE=all LOAD_RUNS=3 LOAD_WARMUP=10 LOAD_SECONDS=10
```

The independent Gradle 9.1.0 wrapper uses Java 25, Spring Boot 4.1.1 and Native Build Tools 1.1.8. `build` runs Java tests and Spring AOT; `nativeCompile` creates the executable. The pinned compiler is GraalVM Community 25.0.2, with no fallback, Serial GC, compatibility CPU instructions, two compilation threads and a 4 GiB compiler heap. The pinned JVM runtime is Temurin 25.0.4.1. Versions and image digests are recorded: these are deployment comparisons with different patch releases and collectors.

Reachability metadata repository 1.0.9 supplies third-party hints alongside Spring-generated hints and metadata embedded in dependencies. GraalVM's default metadata behavior permits Spring's expected probes for optional classes. The separate missing-hint check demonstrates a failure in the application's dynamic reflection path without changing the benchmark mode. Full packaged contract checks verify resources, reflection and invalid inputs. [Native Build Tools repository configuration](https://github.com/graalvm/native-build-tools/blob/1.1.8/native-gradle-plugin/src/main/java/org/graalvm/buildtools/gradle/dsl/GraalVMReachabilityMetadataRepositoryExtension.java).

The default benchmark measures 30 fresh processes per mode after two unmeasured processes per mode, in a seeded shuffled order. It prints readiness median/p95, first quote response, process RSS, reductions, preparation costs and artifact sizes. Readiness is probed every 20 ms; very fast native startup has proportionally more polling uncertainty. First useful response timestamps are cumulative since launch. Runtime timing excludes Docker launch, packaging, compilation and diagnostic checks. Processes share ordinary OS page cache.

Optional paced load runs in a separate two-CPU, 256 MiB client container at 100 requests/second over one keep-alive connection. Defaults are five repetitions, 30 seconds warmup and 60 seconds measurement. Every response is verified; errors, timeouts or an unsustained rate fail the comparison. Short runs are checks of latency at the offered rate and do not establish maximum capacity or steady-state performance.

A separate preparation table records Gradle packaging (tests and Spring AOT included), native compilation and executable size. Compilation cost includes the Gradle invocation and children, excluding initial packaging and Docker preparation. Uncached dependencies may affect preparation measurements; Docker may reuse them. JAR/library and executable sizes exclude runtime/base images and shared libraries.

Evidence is permanently ignored at `results/07-spring-aot-graalvm-native/<UTC timestamp>/`: HTML, JSON/CSV/JSONL, exact commands/versions, artifact hashes, generated Spring sources, application/process logs, the missing-hint diagnostic and preparation logs. Failure writes `artifacts/failure.json` without a successful summary.

Memory columns report medians across measured processes or load repetitions, in MiB. Readiness RSS is sampled when the service becomes ready; peak RSS covers the process through shutdown, including functional verification. Load RSS is sampled after each measured load window. RSS includes heap and runtime overhead, rather than the heap limit or total container usage.

Each run directory contains `report.html` and an `artifacts/` subdirectory for all supporting evidence. The report links to the artifacts and its path is printed at completion.

## Observed comparison

A run on October 9, 2026 used Linux aarch64 containers on Docker Desktop, the pinned toolchains and limits above, 100,000 compute iterations, two unmeasured starts and 30 measured starts per mode. Both modes passed the same HTTP contract; the native production container also passed health/resource checks without Java installed.

| Mode | Readiness median | Readiness p95 | First quote median since launch | Median readiness RSS | Median peak RSS | Readiness reduction | RSS reduction |
| --- | --- | --- | --- | --- | --- | --- | --- |
| baseline | 2189.21 ms | 2565.30 ms | 2280.54 ms | 146.95 MiB | 149.38 MiB | +0.0% | +0.0% |
| native | 56.93 ms | 68.83 ms | 58.34 ms | 86.26 MiB | 88.29 MiB | +97.4% | +41.3% |

Three short load repetitions per mode each used 10 seconds warmup and 10 seconds at 100 requests/second. Values below are medians across repetitions:

| Mode | Requests/second | Latency p95 | Median RSS after load |
| --- | --- | --- | --- |
| baseline | 99.99 | 3.00 ms | 171.98 MiB |
| native | 99.99 | 2.63 ms | 114.80 MiB |

All 6,000 measured responses passed verification. Native load p95 was 12.5% lower; these short checks do not establish steady-state behavior or maximum capacity. Startup polling adds uncertainty to the very short native times, and JVM/native patch versions and collectors differ.

Gradle packaging including tests and Spring AOT took 10.52 seconds. Native compilation took 125.90 seconds and recorded 3648.40 MiB peak RSS; its executable was 83.07 MiB versus 18.93 MiB for the JVM JAR/libraries. Preparation measurements came from Docker build layers, with the two new example builds sharing host resources; they are illustrative costs rather than isolated comparative trials. Sizes exclude the required JVM/base images and system libraries. Spring generated 115 Java files, including test generation. Evidence is ignored at `results/07-spring-aot-graalvm-native/20261009T181623.848539Z/`.

## Build tests and local development

`make build EXAMPLE=07` runs workload, HTTP and runtime-hint Java tests before native compilation. `make test-app EXAMPLE=07` checks the packaged native API, including resource/reflection behavior. The benchmark verifies both modes and native metadata. The production image contains the executable without Java or an application JAR.

For local development with Java 25, run `./gradlew build` here. Native compilation requires GraalVM 25 and its C toolchain: `./gradlew nativeCompile`. Compose supplies them without host installations. This project builds no other example.
