# 04 — Spring Boot JVM baseline

A Spring Boot 4.1.1 catalog HTTP service runs on pinned Temurin Java 25. This example owns its source, fixture, tests, Gradle wrapper, build scripts, Compose file, and Dockerfiles. It establishes the HTTP baseline for Spring AOT and JVM cache comparisons.

## Setup and changes from the baseline

- **Setup:** A standalone Gradle project packages a Spring Boot 4.1.1 catalog service with an embedded HTTP server. Compose runs it on pinned Temurin Java 25 with G1, a 256 MiB maximum heap, one CPU, and 512 MiB container memory. Product, quote, computation, and readiness endpoints use the in-memory catalog.
- **Baseline:** This example establishes the Spring HTTP baseline for Examples 05–09. Example 01 is the separate CLI baseline; its process completion time is a different measurement from service readiness or request latency.
- **What changes:** The CLI's business workload becomes a long-running Spring service with routing, dependency injection, and JSON handling. Spring AOT is disabled with `-Dspring.aot.enabled=false`, and there is no application JVM AOT cache or native compilation. Ordinary default CDS remains enabled.
- **Why this setup:** Include realistic Spring and HTTP initialization costs before measuring how build-time initialization, JVM caching, or native compilation changes them. This supplies a common service contract and resource budget for the Spring comparisons.
- **Expected result:** A ready HTTP service returning the same catalog, quote, and deterministic computation results. The benchmark establishes readiness time, first useful response time, median process memory, and optional paced request latency. It makes no optimization claim; the later examples compare their execution modes against this kind of ordinary JVM deployment.

## Test the application and stop

Run from the repository root with Docker running. `make test-app` opens fzf; select `04-spring-java-baseline`. Explicit commands skip the picker:

```sh
make status EXAMPLE=04
make build EXAMPLE=04
make test-app EXAMPLE=04
make clean EXAMPLE=04
```

`make test-app` starts a detached service and waits for its health check. Stop it before running another example on the same port, or choose `make test-app EXAMPLE=04 PORT=8084`. `make clean` preserves results and the Gradle cache volume.

Equivalent Compose commands:

```sh
docker compose -f examples/04-spring-java-baseline/compose.yaml --profile spring-baseline up --build --detach --wait spring-baseline
docker compose -f examples/04-spring-java-baseline/compose.yaml --profile spring-baseline down
```

The runtime uses one CPU, 512 MiB container memory, G1 GC, and a 256 MiB maximum heap. Spring AOT is explicitly disabled. The build extracts the Boot JAR into an application JAR plus `lib/`, matching the deployment layout used by the cache example. Ordinary JVM CDS stays enabled.

## Application checks

`make test-app EXAMPLE=04` builds and starts this service, waits for readiness, then prints curl commands and formatted JSON and verifies readiness, product, quote and computation responses. Run the same command again to repeat the checks. The app stays running until `make clean`, so you can also execute the printed curl commands yourself. Omit `EXAMPLE` for fzf selection; the picker offers application examples 01–08. Use `PORT` consistently when choosing another host port; `ITERATIONS` changes the sample computation.

## HTTP examples

```sh
curl -s http://localhost:8080/ready
curl -s http://localhost:8080/products/1
curl -s -H 'Content-Type: application/json' \
  -d '{"quantities":{"1":2,"2":1}}' http://localhost:8080/quotes
curl -s 'http://localhost:8080/compute?iterations=100000'
```

Expected responses:

```json
{"ready":true,"productCount":8,"catalogLabel":"Catalog","springAot":false,"generatedInitializer":false,"javaVersion":"25.0.4.1","springBootVersion":"4.1.1"}
{"id":1,"name":"Keyboard","priceCents":9900}
{"subtotalCents":22300,"discountCents":2230,"totalCents":20070}
{"iterations":100000,"checksum":-7520082499104634107}
```

`/ready` returns 503 until `ApplicationReadyEvent`. Products come from the packaged `catalog.csv`. Unknown products return 404. Empty quotes, unknown quote products, quantities outside 1–100, malformed JSON, and compute iterations outside 1–10,000,000 return 400. The calculation contract matches the plain Java examples.

## Benchmark

```sh
make bench EXAMPLE=04
make bench EXAMPLE=04 RUNS=10
make bench EXAMPLE=04 SUITE=load
make bench EXAMPLE=04 SUITE=all
```

The default `startup` suite runs two unmeasured processes, then 30 fresh JVM processes. It measures HTTP readiness, the first verified product and quote responses, Java RSS at readiness and after a 200 ms idle interval, and peak process RSS. Readiness is polled every 20 ms; measurement uncertainty includes the polling interval and probe time. The first product and quote run sequentially after readiness, so their timestamps include their earlier requests. Every mode passes the complete HTTP contract before measurements.

The optional `load` suite uses five fresh-process repetitions, each with 30 seconds of warmup and 60 seconds of measured requests at 100 requests/second. A separate Python process uses one keep-alive connection and a rotating product/quote/compute mix. It verifies every response and reports successful requests/second, latency p50/p95/p99, schedule lag, and Java RSS after load. Errors, timeouts, or an unsustained offered rate fail the comparison. This measures latency at that rate; the rate bounds reported throughput. The client has its own two-CPU Compose container; Java has a separate one-CPU limit. It does not establish maximum server capacity.

For a short load check:

```sh
make bench EXAMPLE=04 SUITE=load LOAD_RUNS=1 LOAD_WARMUP=2 LOAD_SECONDS=5 RATE=50
```

All process measurements run inside a Linux container and exclude Compose launch, packaging, output checks outside the stated timers, and diagnostic verification. The OS page cache is ordinary; these are fresh-process starts. Peak RSS covers the whole process through termination, including functional checks; readiness and idle RSS are separate samples. Startup records include cgroup throttle counters. Build costs report Gradle packaging, including tests and any uncached downloads, and may come from a cached Docker layer.

The terminal ends with results and preparation tables. Evidence goes to the permanently Git-ignored `results/04-spring-java-baseline/<UTC timestamp>/`: `report.html`, `summary.json`, `environment.json`, `runs.csv`, `runs.jsonl`, packaging logs, application logs/process metrics, and per-request JSON for load runs. Metadata includes exact commands, toolchains/image digest, source and deployment hashes, limits, and benchmark settings. Artifact size includes the application JAR and libraries, excluding the Java runtime and base image. Failures write `artifacts/failure.json` without a successful summary.

Memory columns report medians across measured processes or load repetitions, in MiB. Readiness RSS is sampled when the service becomes ready; peak RSS covers the process through shutdown, including functional verification. Load RSS is sampled after each measured load window. RSS includes heap and runtime overhead, rather than the heap limit or total container usage.

Each run directory contains `report.html` and an `artifacts/` subdirectory for all supporting evidence. The report links to the artifacts and its path is printed at completion.

## Observed results

A Gradle-built run on October 9, 2026 used Linux aarch64 containers on Docker Desktop with the toolchains and limits above, 100,000 compute iterations, two unmeasured startups and 30 measured startups:

| Measurement | Baseline |
| --- | --- |
| Readiness median | 1985.73 ms |
| Readiness p95 | 2217.54 ms |
| First quote median since launch | 2070.56 ms |
| Median readiness RSS | 149.08 MiB |
| Median peak RSS | 151.75 MiB |

Three short load repetitions each used 10 seconds of warmup and 10 seconds at 100 requests/second. Median throughput was 99.99 requests/second, with median repetition p95 latency 2.78 ms and 165.11 MiB Java RSS after load. All 3,000 measured responses passed verification. The separate client had no CPU throttling. These short runs describe this machine and offered rate, and do not establish steady-state capacity.

Gradle packaging took 25.10 seconds including tests and dependency resolution, with 561.39 MiB process/child peak RSS; the deployment JAR and libraries totalled 18.75 MiB. This cost came from image-build measurements and can be reused by Docker. Evidence is ignored at `results/04-spring-java-baseline/20261009T155107.654170Z/`.

## Build tests and source

```sh
make build EXAMPLE=04
```

Image builds run five workload tests and five Java HTTP tests. `make test-app EXAMPLE=04` checks the packaged service with sample API requests. The shared benchmark verifies readiness and every measured response.

- [Application and beans](src/main/java/dev/aotexamples/spring/CatalogApplication.java), [controller](src/main/java/dev/aotexamples/spring/CatalogController.java), and [readiness](src/main/java/dev/aotexamples/spring/Readiness.java) implement the HTTP service.
- [Dockerfile](containers/application.Dockerfile) packages and extracts the application; [Compose](compose.yaml) defines service, benchmark, and tooling containers.
- [HTTP harness](../../benchmark/http_run.py) and [load client](../../benchmark/http_load.py) collect measurements; [smoke checks](../../benchmark/http_smoke.py) verify packaged execution.

For optional local Java 25 development:

```sh
cd examples/04-spring-java-baseline
./gradlew build
java -Xmx256m -XX:+UseG1GC -Dspring.aot.enabled=false -jar build/libs/catalog-service.jar
```
