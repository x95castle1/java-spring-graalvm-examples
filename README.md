# Java AOT examples

Each numbered directory in `examples/` is a self-contained project. It owns its application code, Gradle wrapper and configuration, Docker Compose file, container recipes, and tests. The root [benchmark harness](benchmark/) measures every example and writes ignored evidence under `results/`. The root [Makefile](Makefile) is the common command entry point. All nine builds use their own Gradle 9.1.0 wrapper with a pinned distribution checksum and Java 25 toolchain. Docker supplies Java; no host Java or Gradle installation is needed for the Make commands. For optional local development, run `./gradlew build` inside the selected example with Java 25 installed.

Run all `make` commands from the repository root with Docker running, Docker Compose v2 and Make available. Install `fzf` for interactive example selection (`brew install fzf` on macOS), or pass `EXAMPLE` explicitly. Native builds in Examples 03, 07 and 09 can take several minutes; allow at least 8 GiB of available Docker memory for the Spring native builds. Use `make help` to see the commands and options.

## What Spring AOT, JVM AOT and GraalVM do

**AOT means ahead of time:** preparing work before an application's normal execution. These technologies prepare different parts of the application, so their outputs and runtime requirements differ.

**Spring AOT** analyzes a Spring application during the build and generates code for registering and initializing its beans—the objects managed by Spring. It also produces metadata describing reflection, resources and proxies needed by native compilation. It is used to reduce Spring's discovery work at startup and prepare Spring applications for Native Image. Generated initialization can run on a JVM or be compiled into a native executable. Bean selection, including conditions and profiles that determine which beans exist, is decided during the build. [Spring AOT documentation](https://docs.spring.io/spring-framework/reference/core/aot.html).

**JVM AOT**, in this repository, means **HotSpot's AOT cache in Java 25**. A training run records information that the JVM turns into a reusable cache of prepared class data and method-execution profiles. Later runs reuse class-loading and linking work; recorded profiles help the just-in-time (JIT) compiler optimize code sooner. It is used to improve startup and warmup while continuing to run the application on HotSpot with runtime JIT compilation. The cache belongs to its matching JVM and application deployment, so changed deployments need a matching cache. [Java 25 AOT features](https://docs.oracle.com/en/java/javase/25/migrate/significant-changes-jdk-25.html).

**GraalVM** provides a Java development kit and compiler technologies, including an optimizing JIT compiler and **Native Image**, the tool used by these examples. Native Image analyzes Java bytecode and compiles reachable application code, dependencies and necessary runtime components into an executable for a specific operating system and CPU architecture. It is used when fast startup and a smaller runtime memory footprint are priorities, such as CLI tools, services that scale from zero and serverless workloads. The executable includes its runtime and garbage collector and runs without an installed JVM. Native compilation adds build time, and dynamic reflection or resource access may need explicit metadata. [GraalVM](https://www.graalvm.org/), [Native Image documentation](https://www.graalvm.org/jdk25/reference-manual/native-image/).

| Technology used here | Prepared output | Application runtime | Examples |
| --- | --- | --- | --- |
| Spring AOT | Generated initialization code and native metadata | HotSpot or a native executable | 05, 07, 08, 09 |
| JVM AOT cache | A cache trained for the matching deployment | HotSpot JVM | 02, 06, 08, 09 |
| GraalVM Native Image | Compiled native executable | Included native runtime | 03, 07, 09 |

Spring AOT can be combined with the JVM cache (Example 08), or with Native Image (Example 07). A native executable runs without HotSpot and cannot consume its AOT cache. Example 09 compares both supported combinations and the individual JVM variants. The benchmarks measure startup, memory and preparation costs rather than assuming every optimization improves every workload.

## The application we are testing

The examples use a small product catalog and quote calculator. At startup, the application loads eight products, such as a keyboard, mouse and monitor, from a bundled `catalog.csv` resource into memory. It looks up products by ID, calculates order totals using integer cents, and applies a 10% discount when the subtotal reaches 20,000 cents. The sample order contains two keyboards and one mouse: subtotal 22,300 cents, discount 2,230 cents, and total 20,070 cents.

The application also runs a bounded CPU computation that produces a deterministic checksum. `ITERATIONS` controls the amount of work, with 100,000 iterations by default. The benchmark independently calculates the expected checksum and verifies business results so each runtime must perform the same useful work.

Examples 01–03 expose this workload as a CLI: load the catalog, calculate the sample quote, run the computation, print one JSON result and exit. Examples 04–09 expose the catalog workload through a Spring Boot HTTP service:

| Request | What it does |
| --- | --- |
| `GET /ready` | Reports application readiness, product count and runtime/AOT details |
| `GET /products/1` | Returns the keyboard's ID, name and price |
| `POST /quotes` | Accepts product quantities and returns subtotal, discount and total |
| `GET /compute?iterations=100000` | Runs the computation and returns its checksum |
| `GET /native-metadata` (07–09) | Exercises bundled resource access and dynamic reflection |

The catalog and calculations need no database or external service. This keeps the workload repeatable while exercising resource loading, application initialization, computation and, for HTTP examples, request handling and JSON serialization. CLI benchmarks measure time to finish; HTTP benchmarks measure readiness, first useful responses and optional paced request load. Each example owns its implementation, and comparisons within an example change how the application is prepared and executed while preserving its business results.

## 01 — Plain Java JVM baseline

[01-plain-java](examples/01-plain-java/README.md) is a Java 25 catalog CLI running on the standard HotSpot JVM. It establishes the baseline for later JVM AOT-cache and GraalVM Native Image examples.

With Docker Desktop running:

```sh
make test-app EXAMPLE=01
make bench EXAMPLE=01
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

Each project implements the same catalog workload and owns its source, resources, tests, Gradle build, and Compose/container configuration. Example 09 is a comparison suite; Examples 04–08 also expose an application through `make test-app`:

| Example | Default runtime | Benchmark modes |
| --- | --- | --- |
| [04-spring-java-baseline](examples/04-spring-java-baseline/README.md) | Ordinary HotSpot | JVM baseline |
| [05-spring-aot-cache](examples/05-spring-aot-cache/README.md) | Spring AOT on HotSpot | Same processed JAR with Spring AOT off/on |
| [06-spring-jvm-aot-cache](examples/06-spring-jvm-aot-cache/README.md) | HotSpot workload AOT cache, Spring AOT disabled | JVM baseline, startup cache, workload cache |
| [07-spring-aot-graalvm-native](examples/07-spring-aot-graalvm-native/README.md) | Spring AOT + GraalVM native executable | Processed JAR with Spring AOT off, native |
| [08-spring-aot-jvm-aot-cache](examples/08-spring-aot-jvm-aot-cache/README.md) | Spring AOT + JVM workload cache | Ordinary JVM baseline versus combined JVM deployment |
| [09-combined-comparison](examples/09-combined-comparison/README.md) | Comparison suite (`make bench`) | Ordinary JVM, Spring AOT, JVM cache, Spring AOT + JVM cache, native |

Example 05 generates Spring initialization code and runs it on HotSpot. Despite its directory name, it does not create a JVM AOT cache archive. Example 08 combines Spring AOT with an actual JVM AOT cache; Example 09 compares all five modes from its own independent application project.

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

`make build` builds the selected image and runs its Java tests through Gradle; unchanged Docker layers reuse their previous successful tests. `make test-app` executes the CLI or checks the HTTP application's responses, while `make bench` verifies and measures fresh processes and saves a report. Example 09 supports `make build` and `make bench` but has no application for `make test-app`.

The default HTTP benchmark (`SUITE=startup`) measures 30 fresh-process startups per mode after two unmeasured warmup processes per mode, first useful responses, and process RSS. `make bench EXAMPLE=05 SUITE=load` runs only the load suite using a separate paced HTTP client; `SUITE=all` runs both startup and load suites. Default load settings are five repetitions per mode, 30 seconds warmup and 60 seconds measurement at 100 requests/second. A quick load check can use `SUITE=load LOAD_RUNS=1 LOAD_WARMUP=2 LOAD_SECONDS=5 RATE=50`. The client has its own two-CPU Compose container; the report compares latency at a fixed offered rate and does not claim maximum server capacity. Benchmarks launch application processes inside their own container, independently of any app left running by `make test-app`; container startup and image builds are outside the measured runtime window.

Comparison tables include reductions and preparation costs where applicable. All evidence goes to the ignored root `results/<numbered-example>/`, which must stay out of Git. Example 05 also saves generated Spring initialization sources; its README describes build-time profile selection and the separate packaged profile checks. Examples 02, 06, 08 and 09 verify actual cache use and rejection of invalid deployments before timing.

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

The benchmark prints a `file://` URL to `report.html` at completion. The root Makefile maps the container's report path to your host's `results/` directory. Compatible interactive terminals make the link clickable; redirected output contains the plain URL. The local HTML report links into `artifacts/`. Failed measured runs save diagnostics in `artifacts/failure.json`.

Terminal tables use gold headers, muted horizontal separators, and right-aligned numbers. Wide detail tables split into smaller groups to fit the terminal, repeating the row labels. Colors appear automatically in interactive terminals. Redirected output stays free of color codes; `NO_COLOR=1 make bench` disables colors and `FORCE_COLOR=1 make bench` enables them explicitly. These settings also work with `EXAMPLE=01` through `EXAMPLE=09`.

Every example reports median process memory in MiB. CLI examples show the median of each measured process's peak resident memory (RSS). HTTP startup tables show median memory at readiness and median peak memory through shutdown; load tables show median memory sampled after the load window. These include heap and runtime overhead. They measure process memory rather than the configured heap limit or total container usage. Compare modes within an example, since CLI completion and HTTP service memory have different measurement windows.

Run `make test-app`, `make bench`, `make build`, or another example command to select an example with `fzf`. Type to filter, press Enter to select, or Esc to cancel. `make train` and `make verify` offer cache examples only. Multiple goals such as `make build test-app` share one selection.

Install the picker with `brew install fzf` if needed. For scripts or a direct selection, pass `EXAMPLE=01` through `EXAMPLE=09`, or the full directory name, for example `make bench EXAMPLE=05-spring-aot-cache RUNS=10`. Noninteractive commands require an explicit example. `make help` lists commands without opening the picker.

All nine examples are implemented. Example 09 is excluded from the `make test-app` picker, and `make test-app EXAMPLE=09` directs you to `make bench EXAMPLE=09` without starting an application. Each example's README explains its setup, changes from the baseline and expected results.

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
