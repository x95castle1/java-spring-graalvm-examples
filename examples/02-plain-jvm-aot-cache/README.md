# 02 — Plain Java with the JVM AOT cache

The catalog CLI runs on HotSpot Java 25 with an application AOT cache. The JVM reuses class-loading and linking work and recorded method profiles from a training run. JIT compilation still happens at runtime. Java 25's one-command workflow records the application and starts a child JVM to assemble the cache after it exits. [Oracle Java 25 command reference](https://docs.oracle.com/en/java/javase/25/docs/specs/man/java.html).

This example owns its Java source, fixture, tests, Gradle wrapper, build scripts, Compose file, and Dockerfiles. Its application source and build configuration are copied from example 01; it builds without importing that example. The root benchmark harness compares modes using this example's identical JAR.

## Setup and changes from the baseline

- **Setup:** This independent Gradle project owns a copy of Example 01's catalog CLI. Compose builds its JAR and records two training runs: a minimal complete CLI invocation and a longer computation workload. The default application runs with the workload cache on pinned HotSpot Java 25.
- **Baseline:** The comparison uses this project's own JAR with ordinary JVM execution and default CDS, matching Example 01's runtime settings. All three benchmark modes share that JAR, JVM, G1 collector, heap, and container limits.
- **What changes:** Training adds `-XX:AOTCacheOutput` to create `short.aot` and `workload.aot`. Execution selects an archive with `-XX:AOTCache` and requires it with `-XX:AOTMode=on`. The build packages the matching caches alongside the application; verification checks real archive use and rejects invalid deployments.
- **Why enable it:** Reuse application class-loading and linking work and method profiles from training to reduce work in a fresh JVM. HotSpot and runtime JIT compilation remain in use.
- **Expected result:** The same quote and checksum, with potentially lower CLI completion time and process memory than the uncached mode. The two recipes may perform similarly because they exercise the same small application. Any gain requires extra training and archive storage, and the cache must match its application and JVM. The benchmark reports these costs separately.

## Test the application

Run from the repository root with Docker running. `make test-app` opens the fzf picker; select `02-plain-jvm-aot-cache`. The explicit commands below skip the picker:

```sh
make test-app EXAMPLE=02
make test-app EXAMPLE=02 ITERATIONS=1000000
```

The build packages the application and trains two caches. Normal runs select the workload cache and print the same JSON as example 01:

```json
{"application":"catalog-cli","javaVersion":"25.0.4.1","iterations":100000,"productCount":8,"subtotalCents":22300,"discountCents":2230,"totalCents":20070,"checksum":-7520082499104634107}
```

Equivalent direct Compose command:

```sh
docker compose -f examples/02-plain-jvm-aot-cache/compose.yaml --profile cli-jvm-cache run --rm --build cli-jvm-cache --iterations 100000
```

The CLI exits after printing its result. `make clean EXAMPLE=02` removes the example's Compose network and remaining containers, preserving results and the Gradle cache volume.

## Training and verification

```sh
make train EXAMPLE=02
make verify EXAMPLE=02
```

Training is already part of `make build`, `make test-app`, and `make bench` for this example. Docker reuses unchanged build layers; `make train` ensures the image is built rather than forcing a fresh recording every time.

| Recipe | Training input | Artifact |
| --- | --- | --- |
| Short | Load catalog, calculate quote, compute one iteration | `/app/short.aot` |
| Workload | Same request with 100,000 computation iterations | `/app/workload.aot` |

The short recipe is a minimal complete CLI run. Both recipes exercise the same class paths; their profiles and measured benefits may be similar. Change the workload training amount independently of measured work:

```sh
make bench EXAMPLE=02 TRAIN_ITERATIONS=1000000 ITERATIONS=100000
```

Inside the image, training uses:

```sh
java -Xmx256m -XX:+UseG1GC -XX:AOTCacheOutput=/app/workload.aot \
  -jar /app/plain-java.jar --iterations 100000
```

Execution uses:

```sh
java -Xmx256m -XX:+UseG1GC -XX:AOTMode=on -XX:AOTCache=/app/workload.aot \
  -jar /app/plain-java.jar --iterations 100000
```

Strict `AOTMode=on` causes cache-loading failures to terminate execution. Before benchmarking, the harness also checks verbose class-loading logs to establish that `CatalogCli`, `Catalog`, and `Workload` actually came from the archive. Negative checks require a missing cache and a changed application JAR to fail. Verification logs are outside the timed runs. [Oracle AOT mode documentation](https://docs.oracle.com/en/java/javase/25/docs/specs/man/java.html).

Keep the archive, application JAR, and exact Java image together. Rebuild after changing the application, JDK, architecture, JVM options, or deployment layout. The Docker stages retain the JAR's path and timestamps between training and execution. Training artifacts stay inside the image and are never committed.

## Benchmark

```sh
make bench EXAMPLE=02
make bench EXAMPLE=02 RUNS=10
```

Each invocation measures three modes in the same container:

1. `baseline`: ordinary JVM execution with default CDS, matching example 01's settings.
2. `short-cache`: strict application cache execution after the minimal training run.
3. `workload-cache`: strict application cache execution after workload training.

The default is two unmeasured processes per mode, followed by 30 measured processes per mode (90 total). Each round shuffles the modes with a fixed seed to distribute drift across variants. A 100 ms quiet interval before each launch is outside timing and reduces carryover CPU-quota effects. Every process's JSON and checksum are verified independently; raw records also include cgroup throttle counters.

All modes use the same JAR, pinned Temurin Java 25 image, G1 GC, 256 MiB maximum heap, one CPU, and 512 MiB container memory limit. Completion includes the entire CLI process and GNU time overhead. Container launch, training, response validation, and diagnostic logging are excluded. Peak RSS measures process memory including JVM overhead. Runs use the ordinary OS page cache; Docker Desktop produces Linux container results.

The final terminal table shows completion median/p95, median peak RSS, samples, and reductions against the baseline. Positive reductions are improvements; negative reductions are regressions. A second table shows training plus assembly time, peak training RSS, and archive size. Training costs are those recorded during image build, which Docker may cache; they exclude Gradle, downloads, and image preparation. GNU time reports a process/child maximum rather than combined concurrent memory.

Evidence is written to the Git-ignored root directory:

```text
results/02-plain-jvm-aot-cache/<UTC timestamp>/
  report.html
  artifacts/
    summary.json
    environment.json
    runs.csv
    runs.jsonl
    short-verification.log
    workload-verification.log
    short-training.log
    workload-training.log
```

Open `report.html` for the comparison and raw-data links. Metadata includes exact commands, Java version/image digest, source/JAR/cache checksums, resource limits, training inputs, and sample counts. Any validation, cache, or timeout failure stops the comparison and writes `artifacts/failure.json`; no successful summary is produced.

## Observed comparison

A Gradle-built run on October 9, 2026 used Linux aarch64 containers on Docker Desktop, 100,000 iterations, the pinned toolchains and limits above, two unmeasured processes and 30 samples per mode. Modes were shuffled each round with seed 42 and a 100 ms interval between launches.

| Mode | Completion median | Completion p95 | Median peak RSS | Completion reduction | RSS reduction |
| --- | --- | --- | --- | --- | --- |
| Baseline | 34.60 ms | 39.61 ms | 42.90 MiB | +0.0% | +0.0% |
| Short cache | 30.77 ms | 36.35 ms | 38.55 MiB | +11.1% | +10.1% |
| Workload cache | 30.56 ms | 35.63 ms | 38.67 MiB | +11.7% | +9.9% |

Both archives were 11.44 MiB. Recording plus assembly took 0.48 seconds for the short recipe and 0.56 seconds for the workload recipe during image build. These describe this machine and small CLI; rerun locally to compare your environment. Evidence remains ignored at `results/02-plain-jvm-aot-cache/20261009T155013.641706Z/`.

## Source and local development

- [CLI](src/main/java/dev/aotexamples/cli/CatalogCli.java), [workload](src/main/java/dev/aotexamples/core/Workload.java), and [fixture](src/main/resources/catalog.csv) implement the copied application contract.
- [Dockerfile](containers/application.Dockerfile) packages, trains, and runs it.
- [Compose](compose.yaml) defines application, benchmark, and tooling containers.
- [Harness](../../benchmark/run.py) measures the comparison; [cache checks](../../benchmark/cache_check.py) verify cache use and invalid deployments.

For optional local Java 25 development:

```sh
cd examples/02-plain-jvm-aot-cache
./gradlew build
```

`make build EXAMPLE=02` runs the five Java workload tests during packaging. `make test-app EXAMPLE=02` executes the workload-cache CLI. `make verify EXAMPLE=02` checks cache use and invalid deployments; `make bench EXAMPLE=02` verifies the measured outputs in all three modes.
