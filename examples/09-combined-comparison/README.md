# 09 — Combined Spring, JVM cache and native comparison

This standalone Gradle project compares five deployments of its own Spring Boot 4.1.1 HTTP catalog. It builds separate ordinary and Spring AOT deployments, trains a workload cache against each matching deployment, and compiles the processed application with GraalVM Native Image. Source, resources, tests, wrapper, build configuration and containers belong to this example.

## Setup and changes from the baseline

- **Setup:** One independent Gradle project builds an ordinary deployment with `-Pplain=true` and a processed Spring AOT deployment with the default build. Compose trains a separate HTTP-workload cache against each matching deployment and also compiles the processed application into a native executable. This is a comparison suite with no default application for `make test-app`; use `make bench EXAMPLE=09` to measure all five modes.
- **Baseline:** The reference is this project's own ordinary JVM deployment, following Example 04's service contract and settings. The comparison includes baseline, Spring AOT alone, JVM cache alone, their combined JVM mode, and Spring AOT with native execution. Every mode uses the same business workload and application resource budget.
- **What changes:** Spring AOT adds generated initialization and `-Dspring.aot.enabled=true`. JVM caching adds workload training and strict `-XX:AOTMode=on` with the archive built for the selected JAR. Native execution replaces HotSpot with a GraalVM executable and uses resource/reflection hints. Separate build directories and caches keep the ordinary and processed deployments distinct.
- **Why enable it:** Measure each JVM feature's contribution and whether their combination reduces more startup work. The native row measures the alternative of compiling the processed service ahead of deployment. Native executables run without HotSpot and cannot use its AOT cache, so the supported combinations are Spring AOT plus JVM cache, and Spring AOT plus Native Image.
- **Expected result:** All five modes return the same catalog, quote, computation, and metadata responses. The combined JVM mode is intended to improve readiness beyond either JVM feature alone; native execution is expected to start quickly with lower runtime memory for this service. The benchmark verifies these expectations and reports preparation costs separately. Improvements are workload-dependent, and faster startup does not guarantee lower load latency. Native also changes the collector and Java patch version.

| Benchmark mode | Spring AOT | JVM AOT cache | Runtime |
| --- | --- | --- | --- |
| `baseline` | Off | Off | HotSpot |
| `spring-aot` | On | Off | HotSpot |
| `jvm-cache` | Off | On | HotSpot |
| `spring-aot-cache` | On | On | HotSpot |
| `native` | On | Not applicable | GraalVM native executable |

Spring AOT combines with either HotSpot's AOT cache or GraalVM Native Image. The native executable runs without HotSpot, so it cannot consume HotSpot's cache. All three technologies are represented through these two supported combinations. The first four rows compare the individual JVM features and their combined effect; the native row compares the complete deployment alternative. [Spring AOT execution](https://docs.spring.io/spring-framework/reference/core/aot.html).

## Build and compare

Run from the repository root with Docker running:

```sh
make status EXAMPLE=09
make build EXAMPLE=09
make bench EXAMPLE=09
make bench EXAMPLE=09 SUITE=all
make clean EXAMPLE=09
```

`make build` prepares the comparison image, including both JVM deployments, both matching caches, and the native executable. `make bench` launches fresh processes for all five modes and writes the comparison report. It returns when the measurements finish. This suite has no default application: `make test-app EXAMPLE=09` exits with a message directing you to `make bench EXAMPLE=09`. To try the combined JVM service interactively, use [Example 08](../08-spring-aot-jvm-aot-cache/README.md).

Omit `EXAMPLE` from `make bench` to select with fzf. The `make test-app` picker excludes this suite. Compose includes individual runtime profiles for packaged diagnostics; they do not define a default `make test-app` behavior.

Every measured application has one CPU, 512 MiB container memory and a 256 MiB maximum heap. HotSpot uses G1; native uses Serial GC and an Oracle Linux production image without Java, running as user 10001. Native builds use two compiler threads and a 4 GiB compiler heap; allow at least 8 GiB available Docker memory. The first native build may take several minutes.

## Matching deployments and caches

`./gradlew -Pplain=true build` creates an ordinary deployment under `build/plain/`. `./gradlew build` performs Spring AOT and creates a processed deployment under `build/aot/`. Distinct output trees keep their artifacts independent. The container extracts them to `/app/plain/` and `/app/aot/`, then keeps those paths and timestamps consistent throughout cache training and execution.

| Cache | Training and execution deployment | Spring AOT |
| --- | --- | --- |
| `/app/jvm-cache.aot` | `/app/plain/catalog-service.jar` and its libraries | Disabled |
| `/app/spring-aot-cache.aot` | `/app/aot/catalog-service.jar` and its libraries | Enabled |

Both cache recipes reach HTTP readiness, verify 200 rotating product/quote/compute requests, then shut down gracefully so Java assembles the archive. The owned [training client](containers/train.py) checks responses and waits for assembly. `TRAIN_REQUESTS` and `TRAIN_ITERATIONS` change training work; benchmark `ITERATIONS` is independent. Unchanged Docker training layers are reused.

```sh
make train EXAMPLE=09
make verify EXAMPLE=09
make train EXAMPLE=09 TRAIN_REQUESTS=1000 TRAIN_ITERATIONS=1000000
```

Execution requires strict `-XX:AOTMode=on`. Verification proves `CatalogApplication`, `Catalog` and `Workload` load from each archive, plus the generated initializer for the combined cache. Missing caches, a modified JAR at the same path, and a cache paired with the other deployment must fail. The original JAR and timestamps are restored, then valid execution is checked again. Diagnostics are excluded from timing. Deploy caches with their exact JVM, application, dependencies and architecture. [Java 25 AOT flags](https://docs.oracle.com/en/java/javase/25/docs/specs/man/java.html).

## HTTP and native metadata examples

```sh
curl -s http://localhost:8080/products/1
curl -s -H 'Content-Type: application/json' \
  -d '{"quantities":{"1":2,"2":1}}' http://localhost:8080/quotes
curl -s 'http://localhost:8080/compute?iterations=100000'
curl -s http://localhost:8080/native-metadata
```

Every mode returns Keyboard at 9900 cents, quote total 20070 cents, checksum `-7520082499104634107`, and metadata `{"policy":"ten-percent","catalogResource":true}`. Invalid inputs return 400 and absent products/routes return 404. Ordinary JVM modes can select the alternate runtime profile; Spring AOT modes retain beans chosen by the default build-time profile.

This project's own [CatalogRuntimeHints](src/main/java/dev/aotexamples/spring/CatalogRuntimeHints.java) registers the catalog resource and reflective invocation of `DiscountPolicy.name()`, plus constructors for Logback's configurators selected by class name. The metadata endpoint selects the class/method through runtime properties. Packaged native checks deliberately select the unregistered `unregisteredName()` method, require HTTP 500 with a `MissingReflectionRegistrationError` diagnostic naming that method, then verify normal execution. [GraalVM metadata](https://www.graalvm.org/jdk25/reference-manual/native-image/metadata/).

Builds use the pinned Gradle 9.1.0 wrapper, Java 25, Spring Boot 4.1.1 and Native Build Tools 1.1.8. Both deployment builds use GraalVM Community 25.0.2's JDK; JVM execution/cache training uses pinned Temurin 25.0.4.1. Native compilation uses no fallback, compatibility CPU instructions, Serial GC and GraalVM's default metadata behavior. Reachability metadata repository 1.0.9 supplies third-party hints alongside Spring-generated hints and metadata embedded in dependencies. GraalVM's default metadata behavior permits Spring's expected probes for optional classes. The separate missing-hint check demonstrates a failure in the application's dynamic reflection path without changing the benchmark mode. The full packaged contract validates this configuration.

## Benchmark

```sh
make bench EXAMPLE=09
make bench EXAMPLE=09 SUITE=all
make bench EXAMPLE=09 SUITE=all LOAD_RUNS=3 LOAD_WARMUP=10 LOAD_SECONDS=10
```

The default benchmark measures 30 fresh startups per mode (150 measured starts), after two unmeasured processes per mode. Each round shuffles mode order with seed 42. Terminal output and the HTML report start with a compact comparison using readable mode names, median startup in milliseconds, and median process memory at readiness in MiB:

```text
Mode                     Median startup   Median memory
──────────────────────   ──────────────   ─────────────
Baseline                       1,996 ms      151.13 MiB
──────────────────────   ──────────────   ─────────────
Spring AOT                     1,669 ms      132.29 MiB
──────────────────────   ──────────────   ─────────────
JVM cache                      1,063 ms      129.48 MiB
──────────────────────   ──────────────   ─────────────
Spring AOT + JVM cache           804 ms      122.32 MiB
──────────────────────   ──────────────   ─────────────
Native                            46 ms       86.43 MiB
```

These values illustrate the recorded run below; each benchmark prints its own measurements. Detailed tables follow with readiness median/p95, first quote response, median readiness/peak RSS and percentage reductions relative to the ordinary deployment. Raw records also include first product response, idle RSS and CPU throttling. Runtime timing excludes container launch and all preparation/diagnostic work. Readiness polling every 20 ms adds uncertainty, particularly for native startup. Processes share ordinary OS page cache. A load-only run prints load and preparation tables because it does not collect startup samples.

Optional paced load runs over one keep-alive connection from a separate two-CPU, 256 MiB client container at 100 requests/second. Defaults are five repetitions, 30 seconds warmup and 60 seconds measurement. Every response must pass verification and the offered rate must be sustained. Reports measure latency at the offered rate rather than maximum capacity. Shorter checks do not establish steady-state behavior.

Separate preparation rows show ordinary packaging, AOT packaging, both cache training/assembly costs and sizes, and native compilation cost/executable size. Packaging includes tests and potentially uncached downloads; AOT packaging also includes generated initialization. Native cost includes the Gradle invocation and compiler children, excluding initial packaging and Docker preparation. Build costs may be reused from image layers. Artifact sizes exclude the JVM, runtime/base images and shared libraries. Exact toolchain versions, collectors, limits, commands and hashes identify the differences between deployments.

All evidence is permanently ignored under `results/09-combined-comparison/<UTC timestamp>/`: HTML, JSON/CSV/JSONL, ordinary/AOT deployment hashes, native hash/size, generated sources, cache verification and rejection logs, missing-hint diagnostic, build/training logs, and optional per-request load records. Failures write `artifacts/failure.json` without a successful summary.

Memory columns report medians across measured processes or load repetitions, in MiB. Readiness RSS is sampled when the service becomes ready; peak RSS covers the process through shutdown, including functional verification. Load RSS is sampled after each measured load window. RSS includes heap and runtime overhead, rather than the heap limit or total container usage.

Each run directory contains `report.html` and an `artifacts/` subdirectory for all supporting evidence. The report links to the artifacts and its path is printed at completion.

## Observed comparison

A Docker Desktop run on Apple Silicon on October 9, 2026, recorded when this suite was numbered 08, measured 30 fresh starts per mode after two warmups, followed by three load repetitions per mode with 10 seconds warmup and 10 seconds measurement at 100 requests/second. Each application had one CPU, 512 MiB container memory and a 256 MiB maximum heap. Compute requests used 100,000 iterations.

| Mode | Ready median ms | Ready p95 ms | First quote median ms | Median ready RSS MiB | Median peak RSS MiB | Startup reduction |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `baseline` | 1995.64 | 2371.13 | 2070.19 | 151.13 | 155.65 | 0.0% |
| `spring-aot` | 1668.62 | 2025.49 | 1720.20 | 132.29 | 136.45 | 16.4% |
| `jvm-cache` | 1062.52 | 1215.72 | 1078.57 | 129.48 | 145.58 | 46.8% |
| `spring-aot-cache` | 804.42 | 965.45 | 862.23 | 122.32 | 126.43 | 59.7% |
| `native` | 46.13 | 68.48 | 47.46 | 86.43 | 88.47 | 97.7% |

The combined JVM mode reduced readiness RSS by 19.1%; native reduced it by 42.8%. These are process startup measurements with ordinary OS page cache. The 20 ms readiness polling interval is significant relative to native startup.

| Mode | Requests/s | Median run p95 ms | Median load RSS MiB | p95 reduction |
| --- | ---: | ---: | ---: | ---: |
| `baseline` | 99.99 | 2.92 | 166.70 | 0.0% |
| `spring-aot` | 99.99 | 3.28 | 148.87 | -12.3% |
| `jvm-cache` | 99.99 | 3.19 | 169.94 | -9.2% |
| `spring-aot-cache` | 99.98 | 3.13 | 149.59 | -7.2% |
| `native` | 99.99 | 2.86 | 115.05 | 1.9% |

All 15,000 measured responses passed verification with zero errors and the separate client sustained the offered rate. The JVM optimizations improved startup but showed slightly higher p95 latency in this short load check. These samples do not establish steady-state behavior or maximum capacity. Native also changes the JDK patch version and garbage collector, so its comparison measures the deployment alternative as a whole.

| Preparation | Seconds | Peak RSS MiB | Artifact MiB |
| --- | ---: | ---: | ---: |
| Ordinary Gradle packaging | 7.67 | 442.50 | 18.75 |
| Gradle packaging with Spring AOT | 10.58 | 521.75 | 18.93 |
| Native compilation | 124.28 | 3628.54 | 83.07 |
| JVM cache training and assembly | 7.00 | 377.84 | 56.12 |
| Combined cache training and assembly | 4.24 | 351.14 | 53.75 |

Preparation measurements come from image builds with reusable dependency caches. Builds for Example 07 and this suite shared host resources, so these costs are illustrative rather than isolated trials. The report records the exact commands, hashes and toolchain differences alongside cache rejection checks and the missing native reflection hint diagnostic.

The historical report and raw evidence were moved to `results/09-combined-comparison/20261009T182130.663629Z/`. Original JSON and logs retain their recorded example name and hashes; their measurements have not been relabeled as new runs. Run `make bench EXAMPLE=09 SUITE=all` to collect your own comparison with the longer default load windows.

## Build tests and local development

`make build EXAMPLE=09` runs Java tests in both Gradle configurations while preparing the comparison image. `make verify EXAMPLE=09` checks both caches and invalid deployments. `make bench EXAMPLE=09` verifies responses across all five modes, cache use and native metadata before reporting measurements. The native production image contains the executable without Java or an application JAR.

For local Java 25 development, run `./gradlew -Pplain=true build` or `./gradlew build` here. `./gradlew nativeCompile` needs GraalVM 25 and a C toolchain; Compose supplies these. The shared [harness](../../benchmark/http_run.py) measures this independent project without building or importing any other application example.
