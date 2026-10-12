# 06 — Spring Boot with the JVM AOT cache

This standalone Spring Boot 4.1.1 service runs on pinned HotSpot Java 25 with an application AOT cache. Spring AOT is explicitly disabled throughout packaging, training and execution. The benchmark compares the ordinary JVM with startup-only and HTTP-workload caches using this example's same extracted deployment. Source, fixture, tests, Gradle wrapper, build scripts, Compose file and Dockerfiles belong to this example.

## Setup and changes from the baseline

- **Setup:** This independent Gradle project packages the ordinary Spring catalog service, then Compose trains two HotSpot caches. The short recipe exits after Spring context refresh; the workload recipe reaches HTTP readiness and verifies product, quote, and compute requests before graceful shutdown assembles its archive. Default execution uses the workload cache.
- **Baseline:** Example 04 supplies the ordinary Spring service model. This benchmark compares its own identical JAR and libraries with no application cache, the short cache, and the workload cache. JVM, G1, heap, and container limits are identical in all modes.
- **What changes:** Training adds `-XX:AOTCacheOutput`; execution uses `-XX:AOTCache` with strict `-XX:AOTMode=on`. Spring AOT remains disabled during building, training, and execution, so generated Spring initialization is not part of this comparison. The cache is deployed with its matching application and JVM.
- **Why enable it:** Reuse JVM class-loading and linking work and recorded profiles for the Spring service. Comparing startup-only and HTTP training shows whether exercising useful requests adds value beyond recording context initialization.
- **Expected result:** The same HTTP responses with potentially earlier readiness and lower startup memory than the uncached JVM mode. HTTP training may also help the first useful requests, but its benefit depends on the workload. Training time and cache sizes are extra deployment costs. The load suite measures request latency independently; startup gains need not improve it.

## Test the application and stop

Run from the repository root with Docker running. `make test-app` opens fzf; select `06-spring-jvm-aot-cache`:

```sh
make status EXAMPLE=06
make build EXAMPLE=06
make test-app EXAMPLE=06
make clean EXAMPLE=06
```

The first build packages the service and trains both caches. Unchanged build layers are reused. `make test-app` starts the service with the workload cache, detached, and waits for its health check. Stop another service on port 8080 first, or choose `PORT=8086`. Cleanup preserves results and the Gradle cache volume.

Equivalent Compose commands:

```sh
docker compose -f examples/06-spring-jvm-aot-cache/compose.yaml --profile spring-jvm-cache up --build --detach --wait spring-jvm-cache
docker compose -f examples/06-spring-jvm-aot-cache/compose.yaml --profile spring-jvm-cache down
```

The runtime uses one CPU, 512 MiB container memory, G1 GC and a 256 MiB maximum heap. `/ready` reports `springAot: false` and `generatedInitializer: false`, along with readiness, eight products, the `Catalog` label, and exact Java/Boot versions.

## Application checks

`make test-app EXAMPLE=06` builds and starts this service, waits for readiness, then prints curl commands and formatted JSON and verifies readiness, product, quote and computation responses. Run the same command again to repeat the checks. The app stays running until `make clean`, so you can also execute the printed curl commands yourself. Omit `EXAMPLE` for fzf selection; the picker offers application examples 01–08. Use `PORT` consistently when choosing another host port; `ITERATIONS` changes the sample computation.

## HTTP examples

```sh
curl -s http://localhost:8080/products/1
curl -s -H 'Content-Type: application/json' \
  -d '{"quantities":{"1":2,"2":1}}' http://localhost:8080/quotes
curl -s 'http://localhost:8080/compute?iterations=100000'
```

Expected results are Keyboard at 9900 cents, quote total 20070 cents (22300 subtotal and 2230 discount), and checksum `-7520082499104634107`. `/ready` returns 503 until the application-ready event. Missing products return 404; invalid/malformed quotes and compute inputs return 400. Application source, resources and tests are identical independent copies of example 04.

## Training and verification

```sh
make train EXAMPLE=06
make verify EXAMPLE=06
make train EXAMPLE=06 TRAIN_REQUESTS=1000 TRAIN_ITERATIONS=1000000
```

`make build`, `make test-app` and `make bench` also ensure the caches are built. `make train` uses Docker caching rather than forcing a new recording each invocation.

| Recipe | Training work | Artifact |
| --- | --- | --- |
| Short | Refresh the Spring context, then exit with `spring.context.exit=onRefresh` | `/app/short.aot` |
| Workload | Reach HTTP readiness, verify 200 rotating product/quote/compute requests, then stop Java gracefully | `/app/workload.aot` |

`TRAIN_REQUESTS` controls the total HTTP requests; `TRAIN_ITERATIONS` controls computation in its compute requests. Benchmark `ITERATIONS` is independent. The owned [training client](containers/train.py) checks response contents and waits for Java's child cache assembly during shutdown. Training costs include the JVM run, shutdown and assembly; workload cost also includes its HTTP client. They exclude Gradle and Docker preparation. Peak training RSS is GNU time's process/child maximum, not a sum of concurrent processes.

The [Dockerfile](containers/application.Dockerfile) first extracts the executable Boot JAR with tools mode into `/app/catalog-service.jar` and `/app/lib/`. Training and execution retain the same deployment paths and timestamps. [Spring Boot JVM cache deployment](https://docs.spring.io/spring-boot/reference/packaging/aot-cache.html).

Short training uses:

```sh
java -Xmx256m -XX:+UseG1GC -Dspring.aot.enabled=false \
  -XX:AOTCacheOutput=/app/short.aot -Dspring.context.exit=onRefresh \
  -jar /app/catalog-service.jar
```

Normal execution uses:

```sh
java -Xmx256m -XX:+UseG1GC -Dspring.aot.enabled=false \
  -XX:AOTMode=on -XX:AOTCache=/app/workload.aot \
  -jar /app/catalog-service.jar
```

Strict `AOTMode=on` makes an unusable cache fail. Before timing, the harness verifies `CatalogApplication`, `Catalog` and `Workload` load from each archive. It also requires a missing cache and a modified JAR at the same deployment path to fail, restores the JAR with its timestamps, and rechecks valid execution. Diagnostic logs stay outside measured runs. Dynamic proxies may be skipped during training; the application-class checks establish that the caches are actually used. [Java 25 AOT flags](https://docs.oracle.com/en/java/javase/25/docs/specs/man/java.html).

Deploy archives with their matching application, dependencies, exact JVM image and architecture. Rebuild after changing them. Caches stay inside Docker images and are never committed.

## Benchmark

```sh
make bench EXAMPLE=06
make bench EXAMPLE=06 RUNS=10
make bench EXAMPLE=06 SUITE=load
make bench EXAMPLE=06 SUITE=all
```

Modes are `baseline`, `short-cache`, and `workload-cache`. The default startup suite runs two unmeasured processes per mode, then 30 measured processes per mode, for 90 measured starts. Each round shuffles modes with seed 42 and uses a 100 ms untimed interval before launch. Every mode passes the HTTP contract and strict cache checks first.

The terminal and HTML tables show readiness median/p95, first quote response, readiness RSS, sample counts, and reductions relative to this example's baseline. Positive reductions mean improvement; negative reductions remain visible. Raw records also contain first product response, idle RSS, peak process RSS and startup CPU throttling. Readiness polling is every 20 ms; uncertainty includes the interval and probe time. First useful response timestamps are cumulative since process launch, with product and quote requested sequentially. Peak RSS covers the entire process through shutdown, including verification. All modes use the same Java, JAR, libraries, heap, GC and container limits, with ordinary OS page cache and baseline default CDS.

Optional paced load uses five repetitions per mode, each with 30 seconds warmup and 60 seconds at 100 requests/second. A separate Python client uses one keep-alive connection and a rotating product/quote/compute mix, with its own two-CPU container allowance. Response errors, timeouts or an unsustained offered rate fail the comparison. It measures latency at that rate, not maximum throughput. For a short check, add `LOAD_RUNS=1 LOAD_WARMUP=2 LOAD_SECONDS=5 RATE=50`; short checks do not establish steady-state behavior.

A preparation table shows packaging cost, training/assembly costs and both archive sizes. Packaging includes tests and potentially uncached dependency downloads. Docker may reuse preparation costs from its build layers. Deployment size is the JAR plus libraries, with each cache reported as an additional artifact; the JVM/base image are excluded.

Evidence is permanently ignored under `results/06-spring-jvm-aot-cache/<UTC timestamp>/`: HTML, JSON/CSV, toolchain/configuration and deployment hashes, application/process logs, packaging/training logs, both cache-verification logs, missing-cache/changed-JAR rejection logs, and per-request JSON for load tests. Failed checks write `artifacts/failure.json` without a successful summary.

Memory columns report medians across measured processes or load repetitions, in MiB. Readiness RSS is sampled when the service becomes ready; peak RSS covers the process through shutdown, including functional verification. Load RSS is sampled after each measured load window. RSS includes heap and runtime overhead, rather than the heap limit or total container usage.

Each run directory contains `report.html` and an `artifacts/` subdirectory for all supporting evidence. The report links to the artifacts and its path is printed at completion.

## Observed comparison

A Gradle-built run on October 9, 2026 used Linux aarch64 containers on Docker Desktop with the toolchains and limits above, 100,000 compute iterations, two unmeasured startups and 30 measured startups per mode. Spring AOT stayed disabled; all modes used this example's identical deployment.

| Mode | Readiness median | Readiness p95 | First quote median since launch | Median readiness RSS | Median peak RSS | Readiness reduction | RSS reduction |
| --- | --- | --- | --- | --- | --- | --- | --- |
| baseline | 1993.98 ms | 2235.04 ms | 2075.41 ms | 146.52 MiB | 149.62 MiB | +0.0% | +0.0% |
| short-cache | 1148.53 ms | 1187.96 ms | 1186.33 ms | 123.90 MiB | 141.54 MiB | +42.4% | +15.4% |
| workload-cache | 1057.99 ms | 1145.96 ms | 1073.83 ms | 126.22 MiB | 143.41 MiB | +46.9% | +13.9% |

Three short load repetitions per mode each used 10 seconds of warmup and 10 seconds at 100 requests/second. The values below are medians across repetitions:

| Mode | Requests/second | Latency p95 | Median RSS after load |
| --- | --- | --- | --- |
| baseline | 99.99 | 2.95 ms | 170.66 MiB |
| short-cache | 99.99 | 3.00 ms | 169.88 MiB |
| workload-cache | 99.99 | 2.97 ms | 163.23 MiB |

All 9,000 measured responses passed verification, with no CPU throttling in the client's measured windows. Cache modes' median load p95 was slightly higher than the baseline despite faster startup. These short runs do not establish steady-state capacity. The short cache was 51.19 MiB and took 2.76 seconds to train and assemble; the workload cache was 56.12 MiB and took 3.06 seconds. Gradle packaging took 25.10 seconds including tests and dependency resolution, separate from training. Preparation costs may be reused by Docker. Evidence is ignored at `results/06-spring-jvm-aot-cache/20261009T155849.398408Z/`.

## Build tests and local development

`make build EXAMPLE=06` runs five workload tests and five Java HTTP tests during packaging. `make test-app EXAMPLE=06` verifies sample requests with the workload cache. `make verify EXAMPLE=06` checks cache use and invalid deployments, and the benchmark verifies measured responses in all three modes.

For optional local Java 25 development:

```sh
cd examples/06-spring-jvm-aot-cache
./gradlew build
```

Compose additionally extracts the deployment and trains the archives. The shared [HTTP harness](../../benchmark/http_run.py), [cache checks](../../benchmark/http_cache_check.py), and [load client](../../benchmark/http_load.py) benchmark this example without building or importing another application example.
