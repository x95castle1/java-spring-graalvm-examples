# Java AOT examples

Each numbered directory in `examples/` is a self-contained application project. It owns its application code, Gradle wrapper and configuration, Docker Compose file, container recipes, and tests. The root [benchmark harness](benchmark/) measures every example and writes ignored evidence under `results/`. The root [Makefile](Makefile) is the common command entry point. All nine builds use their own Gradle 9.1.0 wrapper with a pinned distribution checksum and Java 25 toolchain. Docker supplies Java; no host Gradle installation is needed. For local development, run `./gradlew build` inside the selected example with Java 25 installed.

## 01 — Plain Java JVM baseline

[01-plain-java](examples/01-plain-java/README.md) is a Java 25 catalog CLI running on the standard HotSpot JVM. It establishes the baseline for later JVM AOT-cache and GraalVM Native Image examples.

With Docker Desktop running:

```sh
make test-app
make bench
```

`make bench` writes evidence to `results/01-plain-java/`. Use the example's README for configuration, direct Compose commands, and the benchmark method.

## 02 — JVM AOT cache

[02-plain-jvm-aot-cache](examples/02-plain-jvm-aot-cache/README.md) copies the CLI into a standalone project and adds short and workload cache training. Its benchmark compares ordinary JVM execution with both cache recipes using the same JAR.

```sh
make test-app EXAMPLE=02
make bench EXAMPLE=02
```

Results go to `results/02-plain-jvm-aot-cache/`. The benchmark prints runtime reductions, training costs, and cache sizes, and saves an HTML comparison. Use `make verify EXAMPLE=02` to check cache use and invalid deployments directly.

## 03 — GraalVM Native Image

[03-plain-graalvm-native](examples/03-plain-graalvm-native/README.md) compiles its own copy of the CLI into a Linux native executable and runs it in a container without Java installed. Its benchmark compares ordinary JVM and native execution from the same input JAR.

```sh
make test-app EXAMPLE=03
make bench EXAMPLE=03
```

Results go to `results/03-plain-graalvm-native/`. The terminal and HTML tables show runtime reductions, native compilation time/memory, and artifact sizes. The first build includes native compilation; subsequent runs reuse unchanged layers.

## 04–09 — Spring Boot HTTP services

Each service owns its copy of the same catalog source, resources, tests, Gradle build, and Compose/container configuration:

| Example | Default runtime | Benchmark modes |
| --- | --- | --- |
| [04-spring-java-baseline](examples/04-spring-java-baseline/README.md) | Ordinary HotSpot | JVM baseline |
| [05-spring-aot-cache](examples/05-spring-aot-cache/README.md) | Spring AOT on HotSpot | Same processed JAR with Spring AOT off/on |
| [06-spring-jvm-aot-cache](examples/06-spring-jvm-aot-cache/README.md) | HotSpot workload AOT cache, Spring AOT disabled | JVM baseline, startup cache, workload cache |
| [07-spring-aot-graalvm-native](examples/07-spring-aot-graalvm-native/README.md) | Spring AOT + GraalVM native executable | JVM baseline, native |
| [08-spring-aot-jvm-aot-cache](examples/08-spring-aot-jvm-aot-cache/README.md) | Spring AOT + JVM workload cache | Ordinary JVM baseline versus combined JVM deployment |
| [09-combined-comparison](examples/09-combined-comparison/README.md) | Comparison suite (`make bench`) | Ordinary JVM, Spring AOT, JVM cache, Spring AOT + JVM cache, native |

```sh
make test-app EXAMPLE=04
curl -s http://localhost:8080/ready
curl -s http://localhost:8080/products/1
curl -s -H 'Content-Type: application/json' -d '{"quantities":{"1":2,"2":1}}' http://localhost:8080/quotes
make clean EXAMPLE=04

make bench EXAMPLE=05
make verify EXAMPLE=06
```

`make test-app` builds the selected example and runs it. CLI examples 01–03 print their result and exit. HTTP examples 04–08 start detached, wait for readiness, then send sample requests, print curl equivalents and formatted JSON, and check the responses. Examples 07 and 08 also check the resource/reflection endpoint. The HTTP app stays running for you to use; `make clean` stops it.

```sh
make test-app EXAMPLE=08
make clean EXAMPLE=08
```

Omit `EXAMPLE` for one fzf selection offering examples 01–08. Choose another HTTP host port with `make test-app EXAMPLE=08 PORT=8088`, and use the same `PORT` on repeat runs. Stop an app before switching examples on the same port. `ITERATIONS` controls the sample computation. Docker supplies the client as well as the application.

`make build` builds the selected image and runs its Java tests through Gradle; unchanged Docker layers reuse their previous successful tests. There is no separate `make test` target. `make test-app` checks application execution, while `make bench` measures fresh processes and saves a report.

The default HTTP benchmark measures 30 fresh-process startups per mode, first useful responses, and process RSS. `make bench EXAMPLE=05 SUITE=load` adds a separate paced HTTP client; `SUITE=all` runs startup and load suites. Default load settings are five repetitions per mode, 30 seconds warmup and 60 seconds measurement at 100 requests/second. A quick load check can use `LOAD_RUNS=1 LOAD_WARMUP=2 LOAD_SECONDS=5 RATE=50`. The client has its own two-CPU Compose container; the report compares latency at a fixed offered rate and does not claim maximum server capacity.

Terminal and HTML tables include reductions and preparation costs. All evidence goes to the ignored root `results/<numbered-example>/`. Example 05 also saves generated Spring initialization sources and tests build-time profile selection. Example 06 verifies actual cache use and rejection of invalid deployments before timing.

Each run keeps the HTML report beside one folder of supporting artifacts:

```text
results/09-combined-comparison/<UTC timestamp>/
  report.html
  artifacts/
    summary.json
    environment.json
    runs.csv
    runs.jsonl
    ...logs and other evidence
```

The benchmark prints a clickable `file://` URL to `report.html` at completion. The root Makefile maps the container's report path to your host's `results/` directory, so the link opens the local HTML report with links into `artifacts/`. Interactive terminals also receive an explicit hyperlink; redirected output contains the plain URL. Failed runs save diagnostics in `artifacts/failure.json`.

Terminal tables use gold headers, muted horizontal separators, and right-aligned numbers. Wide detail tables split into smaller groups to fit the terminal, repeating the row labels. Colors appear automatically in interactive terminals. Redirected output stays free of color codes; `NO_COLOR=1 make bench` disables colors and `FORCE_COLOR=1 make bench` enables them explicitly. These settings also work with `EXAMPLE=01` through `EXAMPLE=09`.

Every example reports median process memory in MiB. CLI examples show the median of each measured process's peak resident memory (RSS). HTTP startup tables show median memory at readiness and median peak memory through shutdown; load tables show median memory sampled after the load window. These include heap and runtime overhead. They measure process memory rather than the configured heap limit or total container usage. Compare modes within an example, since CLI completion and HTTP service memory have different measurement windows.

Run `make test-app`, `make bench`, `make build`, or another example command to select an example with `fzf`. Type to filter, press Enter to select, or Esc to cancel. `make train` and `make verify` offer cache examples only. Multiple goals such as `make build test-app` share one selection.

Install the picker with `brew install fzf` if needed. For scripts or a direct selection, pass `EXAMPLE=01` through `EXAMPLE=09`, or the full directory name, for example `make bench EXAMPLE=05-spring-aot-cache RUNS=10`. Noninteractive commands require an explicit example. `make help` lists commands without opening the picker.

All nine examples are implemented. Example 09 is a comparison suite; it is excluded from the `make test-app` picker, and `make test-app EXAMPLE=09` directs you to `make bench EXAMPLE=09` without starting an application. The [implementation plan](docs/IMPLEMENTATION_PLAN.md) explains the technologies and comparison matrix.

```sh
make test-app EXAMPLE=07
make clean EXAMPLE=07
make test-app EXAMPLE=08
make clean EXAMPLE=08
make bench EXAMPLE=08 SUITE=all
make bench EXAMPLE=09 SUITE=all
```

Example 08 is the dedicated Spring AOT + JVM cache service: `make test-app` starts that combination and `make bench` compares it with its ordinary baseline. Its build and tests use JVM deployments. Example 09 owns the complete five-mode comparison, including both matching JVM caches and the native executable. It verifies cache use, invalid deployments and native reflection/resource behavior before timing. Native production images run without Java; allow at least 8 GiB available Docker memory for native builds. Build and runtime costs appear separately in the terminal and HTML reports.

Spring AOT combines with the JVM cache on HotSpot, or with GraalVM Native Image. A native executable runs without HotSpot and cannot use HotSpot's AOT cache. Example 09 compares both supported combinations alongside their individual JVM variants.
