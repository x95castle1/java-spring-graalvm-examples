# 03 — Plain Java with GraalVM Native Image

This example compiles the catalog CLI into a Linux executable with GraalVM Community Native Image. The production container runs that executable without a JDK or application JAR. It owns its Java source, fixture, tests, Gradle wrapper, build scripts, Compose file, and Dockerfiles; it builds independently of examples 01 and 02.

The root benchmark compares two modes from this example's same input JAR: ordinary HotSpot JVM execution and native execution. Native Image analyzes reachable code and compiles it ahead of deployment, including a native runtime and garbage collector. [GraalVM Native Image documentation](https://www.graalvm.org/jdk25/reference-manual/native-image/).

## Setup and changes from the baseline

- **Setup:** This independent Gradle project packages the catalog CLI, then a GraalVM Native Image build stage compiles its JAR into a Linux executable. The production Compose service runs that executable as user `10001` in Oracle Linux, without Java installed. Explicit resource metadata includes `catalog.csv` in the executable.
- **Baseline:** The reference is ordinary HotSpot execution of this example's own input JAR, matching Example 01's workload. JVM and native measurements use the same computation, one CPU, 512 MiB container memory, and 256 MiB maximum heap.
- **What changes:** Deployment runs `/app/catalog-cli` instead of `java -jar`. Native compilation moves reachable-code analysis and machine-code generation into the build. The runtime includes GraalVM's native support and Serial GC; the JVM baseline uses G1. The native and JVM Java patch versions also differ.
- **Why enable it:** Reduce the launch work of this short-lived CLI and remove the need to deploy a JVM. Resource metadata keeps the catalog available when the application is compiled into an executable.
- **Expected result:** The same quote and checksum, with substantially shorter completion time and potentially lower peak process memory for this workload. Native compilation takes additional time and memory, and the executable is tied to its target OS and architecture. Its size includes a runtime, so comparing it with the JAR alone does not represent total deployment size. This measures the whole native deployment alternative, including its different collector.

## Test the application

With Docker running, execute from the repository root. `make test-app` opens the fzf picker; select `03-plain-graalvm-native`. Explicit selection skips the picker:

```sh
make status EXAMPLE=03
make build EXAMPLE=03
make test-app EXAMPLE=03
make test-app EXAMPLE=03 ITERATIONS=1000000
```

The first build packages the Java application and compiles the executable. Unchanged layers are reused on subsequent runs. Compilation uses two compiler threads and a 2 GiB compiler heap, with additional native compiler memory needed. Docker Desktop needs enough memory for that build; runtime limits are separate.

The CLI prints the same quote and checksum as the JVM examples, then exits. The native executable reports its embedded Java version:

```json
{"application":"catalog-cli","javaVersion":"25.0.2","iterations":100000,"productCount":8,"subtotalCents":22300,"discountCents":2230,"totalCents":20070,"checksum":-7520082499104634107}
```

Equivalent direct Compose command:

```sh
docker compose -f examples/03-plain-graalvm-native/compose.yaml --profile cli-native run --rm --build cli-native --iterations 100000
```

The production image runs as user `10001` on Oracle Linux 9 slim. `make clean EXAMPLE=03` removes the example's Compose network and remaining containers, preserving results and the Gradle cache volume. Host Java, Gradle, and GraalVM installations are optional; Compose supplies the toolchains.

## Native build and resource metadata

[The Dockerfile](containers/application.Dockerfile) packages the JAR using pinned Temurin Java 25, compiles it using pinned GraalVM Community 25, then copies only the executable into the production image. Build arguments and Compose anchors record immutable image digests. The selected toolchains are Temurin 25.0.4.1 and GraalVM CE 25.0.2+10.1.

Compilation runs:

```sh
native-image --no-fallback --gc=serial -march=compatibility \
  --exact-reachability-metadata --parallelism=2 -J-Xmx2g \
  -jar /app/plain-java.jar /app/catalog-cli
```

`--no-fallback` requires a native executable. `-march=compatibility` avoids specializing the executable for the build host's CPU features. The executable still targets the build's OS and architecture: a Linux arm64 build runs in Linux arm64 containers, including Docker Desktop on Apple Silicon. [Native Image options](https://www.graalvm.org/jdk25/reference-manual/native-image/overview/Options/).

The CLI loads `/catalog.csv` from its classpath. [Reachability metadata](src/main/resources/META-INF/native-image/dev.aotexamples/plain-java/reachability-metadata.json) explicitly includes that resource in the executable. The copied workload requires no application reflection configuration. [GraalVM resource metadata](https://www.graalvm.org/jdk25/reference-manual/native-image/metadata/).

At runtime the native command is:

```sh
/app/catalog-cli -Xmx256m --iterations 100000
```

## Benchmark

```sh
make bench EXAMPLE=03
make bench EXAMPLE=03 RUNS=10
```

The default comparison runs two unmeasured processes per mode and 30 measured processes per mode, for 60 measured launches. A seeded shuffle orders JVM and native execution within each round. A 100 ms quiet interval before each launch stays outside timing and reduces carryover CPU-quota effects. Every response and checksum is checked independently after timing; a failed launch or incorrect response stops the benchmark.

Both modes run inside the same Linux benchmark container with one CPU, 512 MiB container memory, and a 256 MiB maximum heap. The JVM uses Temurin's G1 GC; the native executable uses GraalVM Community's Serial GC. Their Java patch releases differ and are recorded in metadata. This measures the complete deployment alternatives for this small CLI, including those runtime differences.

Completion covers process launch through exit, including GNU time wrapper overhead. Container launch, compilation, diagnostic checks, and output validation are excluded. RSS is peak process memory, including heap and runtime overhead. Runs use the ordinary OS page cache. Native execution is short enough that wrapper overhead is noticeable; these results do not measure sustained throughput or HTTP readiness.

The terminal table and HTML report show completion median/p95, median peak RSS, samples, and percentage reductions against the JVM baseline. Positive reductions mean improvement; negative reductions remain visible. A second table reports native compilation time, peak compilation RSS, executable size, and input JAR size. Compilation costs were recorded during image build and may come from a cached layer; they exclude Gradle, downloads, and image preparation.

Executable and JAR sizes exclude base images and shared libraries. The executable includes its native runtime, while deploying the JAR requires a JVM as well. Total container sizes are not included in this report.

Generated evidence is permanently ignored by Git:

```text
results/03-plain-graalvm-native/<UTC timestamp>/
  report.html
  artifacts/
    summary.json
    environment.json
    runs.csv
    runs.jsonl
    native-verification.json
    native-build.log
```

Open `report.html` for the comparison and links to raw evidence. Metadata records exact commands, toolchain versions/digests, GC settings, source/JAR/executable hashes, resource limits, and compilation measurements. Failures write `artifacts/failure.json` without a successful summary.

## Observed comparison

A Gradle-built run on October 9, 2026 used Linux aarch64 containers on Docker Desktop, 100,000 iterations, the pinned toolchains and limits above, two unmeasured processes and 30 samples per mode. Modes were shuffled each round with seed 42 and a 100 ms interval between launches.

| Mode | Completion median | Completion p95 | Median peak RSS | Completion reduction | RSS reduction |
| --- | --- | --- | --- | --- | --- |
| JVM baseline | 40.41 ms | 52.28 ms | 42.90 MiB | +0.0% | +0.0% |
| Native | 3.70 ms | 4.58 ms | 10.80 MiB | +90.9% | +74.8% |

Native compilation took 22.55 seconds with 1159.40 MiB peak process RSS. The executable was 12.44 MiB; the input JAR was 8.39 KiB. These describe this machine and small CLI; rerun locally to compare your environment. Evidence remains ignored at `results/03-plain-graalvm-native/20261009T155046.009161Z/`.

## Build tests and source

```sh
make build EXAMPLE=03
```

Image builds run the five Java workload tests before compiling the native executable. `make test-app EXAMPLE=03` runs the packaged native CLI. The benchmark checks the native artifact and embedded resources and verifies each measured result in both modes. The production image contains the executable without Java or an application JAR.

- [CLI](src/main/java/dev/aotexamples/cli/CatalogCli.java), [workload](src/main/java/dev/aotexamples/core/Workload.java), and [catalog](src/main/resources/catalog.csv) implement the same contract as the JVM examples.
- [Compose](compose.yaml) defines native application, benchmark, and tooling containers.
- [Shared harness](../../benchmark/run.py) measures both modes; [native checks](../../benchmark/native_check.py) validate the artifact and embedded resources.

For optional local Java 25 development:

```sh
cd examples/03-plain-graalvm-native
./gradlew build
```

That builds and tests the Java application. The Compose build additionally compiles the Linux native executable.
