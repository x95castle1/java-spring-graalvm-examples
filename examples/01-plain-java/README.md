# 01 — Plain Java JVM baseline

This example runs a small catalog application on HotSpot Java 25 and records baseline measurements. It uses normal JVM execution with the default CDS archive. The JVM loads application classes and JIT-compiles methods as the application runs. [JVM AOT cache background](https://inside.java/2026/01/09/run-aot-cache/).

The application reads `catalog.csv` from the JAR, calculates a quote using integer cents, and completes a bounded computation with a deterministic checksum. The same workload can be reused by later examples so their results are comparable.

## Setup and changes from the baseline

- **Setup:** A standalone Gradle project builds the catalog CLI into a JAR. Docker Compose supplies pinned Temurin Java 25 and runs it on HotSpot with G1, a 256 MiB maximum heap, one CPU, and a 512 MiB container memory limit. Each invocation reads the catalog, calculates a quote, performs the requested computation, and exits.
- **Baseline:** This example establishes the plain Java baseline for Examples 02 and 03. It uses ordinary JVM execution and the JDK's default CDS archive, without an application AOT cache or native compilation.
- **What changes:** No AOT optimization is enabled here. The example adds a fixed workload, resource limits, output checks, and measurements so later execution strategies have a repeatable reference.
- **Why this setup:** It shows the cost of starting a JVM, loading application classes, and running the CLI under normal settings. Default CDS remains enabled because it is part of ordinary JVM execution.
- **Expected result:** Correct catalog and quote output plus a deterministic checksum. The benchmark establishes CLI completion time and median peak process memory; it makes no improvement claim. Later CLI examples should preserve the business result while changing preparation and execution costs. The Spring HTTP examples use their own baseline in Example 04.

## Test the application

Run commands from the repository root and select `01-plain-java` in the fzf picker. Pass `EXAMPLE=01` to skip selection:

```sh
make test-app
make test-app ITERATIONS=1000000
```

Or use Docker Compose directly:

```sh
docker compose -f examples/01-plain-java/compose.yaml --profile cli-baseline run --rm --build cli-baseline --iterations 100000
```

The process prints one JSON object and exits successfully. With 100,000 iterations, expect:

| Field | Value |
| --- | --- |
| `productCount` | `8` |
| `subtotalCents` | `22300` |
| `discountCents` | `2230` |
| `totalCents` | `20070` |
| `checksum` | `-7520082499104634107` |

Iteration counts must be between 1 and 10,000,000. Invalid arguments print an error to stderr and return exit code 2. View CLI help with:

```sh
docker compose -f examples/01-plain-java/compose.yaml --profile cli-baseline run --rm --no-deps cli-baseline --help
```

There is no long-running service to stop. `make clean` removes this project's Compose network and any remaining containers.

## Configuration

| Setting | Value |
| --- | --- |
| JVM | Pinned Eclipse Temurin Java 25 image on Ubuntu Noble |
| CPU limit | One CPU |
| Container memory limit | 512 MiB |
| Maximum Java heap | 256 MiB (`-Xmx256m`) |
| Garbage collector | G1 (`-XX:+UseG1GC`) |
| Workload | Eight products; one quote; 100,000 computation iterations by default |
| Build | Gradle 9.1.0 wrapper; Java tests execute during image build |

Java compilation targets Java 25. For optional local development with a Java 25 installation, run these commands from this example directory:

```sh
cd examples/01-plain-java
./gradlew build
java -Xmx256m -XX:+UseG1GC -jar build/libs/plain-java.jar --iterations 100000
```

## Measurements

```sh
make bench RUNS=30 WARMUPS=2 ITERATIONS=100000
```

The benchmark image extends the application image with Python and GNU time. The harness starts a fresh JVM for each run and computes its expected checksum independently. Docker container launch, the warmup processes, checksum calculation, and response validation are outside measured completion time. The GNU time wrapper is inside the completion window and also records CPU time and peak RSS.

The command finishes with a terminal table of completion time, peak process RSS, mean CPU time, and the number of measured processes. It also writes a static HTML report plus JSON and CSV evidence under `results/01-plain-java/`. Every invocation gets a new directory. A failed response or timeout stops the benchmark and writes `artifacts/failure.json`; it does not produce a successful summary.

Use completion median and spread as the primary numbers. p95 uses linear interpolation and is descriptive with only 30 samples. Peak RSS is the entire Java process, rather than its heap limit or total container memory. This small application primarily exposes launch overhead; its results describe this workload and should be compared with variants of the same application.

Each run directory contains `report.html` and an `artifacts/` subdirectory for all supporting evidence. The report links to the artifacts and its path is printed at completion.

A Gradle-built run on October 9, 2026 used Temurin 25.0.4.1, Linux aarch64 containers on Docker Desktop for macOS, the limits above, 100,000 iterations, two warmup processes, and 30 measured processes:

| Measurement | Baseline result |
| --- | --- |
| CLI completion median | 32.16 ms |
| CLI completion p95 | 57.65 ms |
| CLI completion range | 27.00–59.94 ms |
| Median peak memory (RSS) | 42.98 MiB |
| Peak process RSS maximum | 43.29 MiB |
| Application JAR size | 7,857 bytes |

These are results from that machine and run. Evidence is ignored at `results/01-plain-java/20261009T154949.031403Z/`. Regenerate them on your machine before comparing subsequent variants.

## Source and verification

- [CLI](src/main/java/dev/aotexamples/cli/CatalogCli.java) parses arguments and prints the result.
- [Workload](src/main/java/dev/aotexamples/core/Workload.java) calculates prices and the checksum.
- [Catalog fixture](src/main/resources/catalog.csv) contains the input data.
- [Container build](containers/application.Dockerfile) packages the JAR and benchmark image.
- [Benchmark](../../benchmark/run.py) verifies outputs and collects statistics.

`make build EXAMPLE=01` runs the Java tests for catalog resource loading, discount thresholds, invalid orders, deterministic computation and argument bounds during image packaging. `make test-app EXAMPLE=01` executes the packaged CLI; `make bench EXAMPLE=01` verifies each measured result.
