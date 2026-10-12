# 08 — Spring AOT with the JVM AOT cache

This standalone Gradle project runs its Spring Boot 4.1.1 catalog service with both Spring AOT initialization and a matching HotSpot AOT cache. It owns its source, resources, tests, wrapper, build configuration, training client and containers. Its benchmark compares the ordinary JVM baseline with this combined JVM deployment. [Example 09](../09-combined-comparison/README.md) compares all five execution strategies.

## Setup and changes from the baseline

- **Setup:** Compose builds an ordinary deployment with `-Pplain=true` and a Spring AOT deployment with the default Gradle build. It trains one HTTP-workload cache against the processed deployment. Normal execution runs that processed JAR with both features enabled on pinned Temurin Java 25.
- **Baseline:** The reference is this project's ordinary deployment, following Example 04's service contract and settings. Both benchmark modes use G1, a 256 MiB maximum heap, one CPU and 512 MiB container memory. The baseline has Spring AOT disabled and no application cache.
- **What changes:** The build enables Spring Boot's AOT plugin and generates initialization code. Training uses `-XX:AOTCacheOutput` with `-Dspring.aot.enabled=true`. Execution enables the same generated initialization with `-Dspring.aot.enabled=true` and requires its cache with `-XX:AOTMode=on` and `-XX:AOTCache`.
- **Why enable it:** Spring AOT reduces runtime bean discovery work; the JVM cache reuses class-loading and linking work and recorded profiles from training. Combining them prepares both Spring initialization and JVM startup work before deployment while retaining HotSpot and runtime JIT compilation.
- **Expected result:** Identical catalog, quote, computation and metadata responses, with potentially faster readiness and lower startup memory than the ordinary JVM baseline. Build-time bean selection and a cache tied to its exact deployment are the tradeoffs. Build and training costs are recorded separately; startup gains do not guarantee lower request latency.

## Test the application and stop

From the repository root with Docker running:

```sh
make status EXAMPLE=08
make build EXAMPLE=08
make test-app EXAMPLE=08
make clean EXAMPLE=08
```

`make test-app` always starts the `spring-combined` service: Spring AOT plus its JVM workload cache. `/ready` reports `springAot: true`, `generatedInitializer: true`, eight products and the exact Java/Boot versions. Choose `PORT=8088` if another service uses port 8080. Omit `EXAMPLE` to select with fzf.

Equivalent Compose commands:

```sh
docker compose -f examples/08-spring-aot-jvm-aot-cache/compose.yaml --profile spring-combined up --build --detach --wait spring-combined
docker compose -f examples/08-spring-aot-jvm-aot-cache/compose.yaml --profile '*' down --remove-orphans
```

The first build packages the two JVM deployments and trains the combined cache. Unchanged layers are reused. Java and Gradle run in containers, so host installations are optional. This example's build, application-check and benchmark commands use JVM deployments throughout.

## Matching the processed deployment and cache

`./gradlew -Pplain=true build` writes the ordinary build under `build/plain/`; `./gradlew build` generates Spring initialization and writes the processed build under `build/aot/`. Containers extract these to `/app/plain/` and `/app/aot/` respectively.

The owned [training client](containers/train.py) launches `/app/aot/catalog-service.jar` with Spring AOT enabled, reaches readiness, verifies 200 rotating product/quote/compute requests by default, and shuts down gracefully to assemble `/app/spring-aot-cache.aot`. Training and execution retain identical JAR/library paths and timestamps. [Java 25 AOT flags](https://docs.oracle.com/en/java/javase/25/docs/specs/man/java.html).

```sh
make train EXAMPLE=08
make verify EXAMPLE=08
make train EXAMPLE=08 TRAIN_REQUESTS=1000 TRAIN_ITERATIONS=1000000
```

Training is part of the image build. `make train` ensures the image is built; Docker may reuse unchanged training layers. `TRAIN_REQUESTS` and `TRAIN_ITERATIONS` control recorded work, independently of benchmark `ITERATIONS`.

Verification requires `CatalogApplication`, `Catalog`, `Workload` and the generated Spring application initializer to load from the archive. Missing caches, a modified JAR at the same path, and pairing the cache with the ordinary deployment must fail in strict mode. Verification restores the original JAR and timestamps, then rechecks valid execution. These diagnostics are excluded from timing. Rebuild the cache when its application, dependencies, JVM, architecture or deployment layout changes.

## Application checks

`make test-app EXAMPLE=08` builds and starts this service, waits for readiness, then prints curl commands and formatted JSON and verifies readiness, product, quote and computation responses. It also checks the resource/reflection endpoint. Run the same command again to repeat the checks. The app stays running until `make clean`, so you can also execute the printed curl commands yourself. Omit `EXAMPLE` for fzf selection; the picker offers application examples 01–08. Use `PORT` consistently when choosing another host port; `ITERATIONS` changes the sample computation.

## HTTP examples

```sh
curl -s http://localhost:8080/products/1
curl -s -H 'Content-Type: application/json' \
  -d '{"quantities":{"1":2,"2":1}}' http://localhost:8080/quotes
curl -s 'http://localhost:8080/compute?iterations=100000'
curl -s http://localhost:8080/native-metadata
```

Expected results are Keyboard at 9900 cents, quote total 20070 cents, checksum `-7520082499104634107`, and metadata `{"policy":"ten-percent","catalogResource":true}`. The metadata endpoint exercises the same resource/reflection path as Example 09 on the JVM. Invalid inputs return 400; absent products/routes return 404. Ordinary execution can select the alternate profile at runtime; Spring AOT retains beans selected by the default build-time profile.

## Benchmark and reports

```sh
make bench EXAMPLE=08
make bench EXAMPLE=08 SUITE=all
make bench EXAMPLE=08 SUITE=all LOAD_RUNS=3 LOAD_WARMUP=10 LOAD_SECONDS=10
```

| Mode | Deployment | Spring AOT | JVM AOT cache |
| --- | --- | --- | --- |
| `baseline` | Ordinary JAR and libraries | Off | Off |
| `spring-aot-cache` | Processed JAR and libraries | On | Matching workload cache |

The default startup suite measures 30 fresh processes per mode after two unmeasured processes per mode, in a seeded shuffled order: 60 measured starts in total. The compact terminal and HTML summaries compare median startup and median process memory at readiness. Detailed tables add readiness p95, first quote, median peak process memory, sample counts and reductions against the baseline. Preparation tables show ordinary/AOT packaging, cache training and artifact size.

Runtime timing excludes container launch, packaging, training and verification. Readiness polling every 20 ms adds uncertainty. Processes share ordinary OS page cache; peak RSS includes functional verification and shutdown. RSS includes heap and runtime overhead rather than the configured heap limit or total container memory.

Optional paced HTTP load uses a separate two-CPU, 256 MiB client, one keep-alive connection and 100 requests/second. Defaults are five repetitions, 30 seconds warmup and 60 seconds measurement. Every response must be correct and the offered rate sustained. Reports describe latency at that offered rate, rather than maximum server capacity; short checks do not establish steady-state behavior.

Each run creates the permanently ignored `results/08-spring-aot-jvm-aot-cache/<UTC timestamp>/` containing `report.html` and an `artifacts/` subdirectory. Artifacts include JSON/CSV/JSONL, deployment/cache hashes, generated Spring sources, preparation logs, positive cache verification and rejection diagnostics. The terminal ends with a clickable host `file://` report URL. Failed runs write `artifacts/failure.json` without a successful summary.

The five-mode report belongs to Example 09. Use `make bench EXAMPLE=09` when comparing Spring AOT alone, JVM cache alone and native execution alongside the combination.

## Observed comparison

A run on October 12, 2026 used Linux aarch64 containers on Docker Desktop, the pinned Temurin Java 25 runtime, one CPU, 512 MiB container memory and a 256 MiB maximum heap. It measured 30 fresh starts per mode after two unmeasured starts per mode, with 100,000 computation iterations.

| Mode | Ready median ms | Ready p95 ms | First quote median ms | Median ready RSS MiB | Median peak RSS MiB |
| --- | ---: | ---: | ---: | ---: | ---: |
| Ordinary JVM baseline | 1918.10 | 2236.12 | 1975.13 | 147.00 | 150.46 |
| Spring AOT + JVM cache | 776.04 | 888.32 | 802.47 | 121.89 | 126.05 |

The combined mode reduced median readiness time by 59.5% and readiness RSS by 17.1% in this run. These are process measurements with ordinary OS page cache; readiness polling adds uncertainty. Ordinary packaging took 5.58 seconds, AOT packaging 8.75 seconds, and cache training/assembly 2.72 seconds. The cache was 53.69 MiB. Preparation costs come from image-build measurements and may be reused from cached layers.

An additional load smoke check used one repetition per mode, one second of warmup and two seconds at 50 requests/second. All 200 measured responses passed verification and the client sustained the offered rate. That short check verifies the load/report path rather than establishing request-performance or capacity gains; use the default longer load windows for comparisons.

The ignored report and raw evidence are under `results/08-spring-aot-jvm-aot-cache/20261012T184548.662105Z/`.

## Build tests and local development

```sh
make build EXAMPLE=08
```

`make build EXAMPLE=08` runs the Java tests in both Gradle configurations during packaging. `make test-app EXAMPLE=08` verifies sample API requests with both AOT features enabled; `make verify EXAMPLE=08` checks cache use and invalid deployments. The benchmark verifies responses in both modes. The project uses Gradle 9.1.0, Java 25 and Spring Boot 4.1.1.

For optional local Java 25 development, run `./gradlew -Pplain=true build` or `./gradlew build` here. The shared [harness](../../benchmark/http_run.py) measures this independent project without building another application example.
