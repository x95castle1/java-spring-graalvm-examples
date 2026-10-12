# Shared benchmark harness

Run from the repository root:

```sh
make bench EXAMPLE=01
make bench EXAMPLE=02
make bench EXAMPLE=03
make bench EXAMPLE=04
make bench EXAMPLE=05
make bench EXAMPLE=06
make bench EXAMPLE=07
make bench EXAMPLE=08
make bench EXAMPLE=09
```

Use `make bench` to select an example with fzf. Explicit `EXAMPLE` values skip the picker and also accept full directory names.

The selected example's Compose file builds its benchmark image and mounts this directory read-only at `/benchmark`. Applications keep independent source and Gradle builds. This directory owns measurement, statistics, output verification, and report generation across examples.

All terminal tables use the shared formatter: gold headers, muted horizontal separators, right-aligned values, and no surrounding box. Wide tables split into groups that fit the interactive terminal, repeating their first column as the row label. ANSI colors are enabled for interactive terminals and omitted for redirected output or `TERM=dumb`. `NO_COLOR=1` disables colors; `FORCE_COLOR=1` enables them even when redirected. `NO_COLOR` takes precedence. The root Makefile passes these environment settings into the benchmark container. HTML and raw artifacts contain no terminal color codes.

The final report line prints a `file://` URL, with an OSC 8 hyperlink in interactive terminals. The root Makefile supplies `REPORT_HOST_RESULTS` to map `/results/.../report.html` to the actual host file. URLs encode spaces and other special characters; redirected output contains no hyperlink escape codes. For direct Compose benchmarking from the repository root, add `--env REPORT_HOST_RESULTS="$PWD/results"` to `docker compose run` to use the same host mapping.

`run.py` measures a fresh process using GNU time and a monotonic wall clock. Example 01 measures its normal JVM. Example 02 sets `EXAMPLE_ID=02-plain-jvm-aot-cache` and compares ordinary JVM, short-cache, and workload-cache execution of its own identical JAR. Example 03 sets `EXAMPLE_ID=03-plain-graalvm-native` and compares its ordinary JVM with a native executable compiled from the same JAR. Comparisons shuffle each round with seed 42 and insert a 100 ms untimed interval before each launch. They have no build dependency on example 01.

`smoke.py` checks packaged CLI output, bounds, bad arguments, and help. `cache_check.py` verifies application classes load from the archive and checks rejection of a missing cache and changed JAR. Verbose cache logs and independent checksum calculation stay outside timed runs.

`native_check.py` requires a Linux ELF artifact, verifies the embedded catalog and checksum, and records native compilation measurements and executable checksum/size. Example 03's production-image checks also run the executable without a JDK or application JAR. Its baseline uses Temurin's G1 GC and its native runtime uses GraalVM Community's Serial GC; both have a 256 MiB maximum heap. Exact toolchain versions and digests are recorded rather than assuming identical patch releases or collectors.

Every invocation creates `results/<numbered-example>/<UTC timestamp>/` containing `report.html` and an `artifacts/` subdirectory. The subdirectory holds JSONL, CSV, metadata, summary, logs, and all other evidence; the HTML report links to these files. Example 02 also records training inputs/costs, cache sizes/checksums, and verification logs. Example 03 records compiler time/memory, executable size/checksum, verification JSON, and the native build log. Failures produce `artifacts/failure.json` without a successful summary or HTML report. All results are ignored by Git.

`RUNS` means samples per variant; example 02 launches three times that many measured processes and example 03 launches twice that many. Two unmeasured processes per mode run by default. Completion includes GNU time overhead; RSS includes runtime overhead beyond the heap. Sample records include cgroup throttle counters. Positive reductions in the comparison mean improvement, and negative reductions remain visible. These CLI runs measure completion rather than sustained throughput.

Every CLI terminal and HTML table labels median peak process memory explicitly, in MiB. This is the median across measured processes of GNU time's peak RSS for each process, including heap and runtime overhead. Warmup processes are excluded from the median. RSS is not the configured heap limit or total container usage.

Training costs cover recording plus cache assembly when the image layer was created. Docker may reuse those costs on later benchmark invocations. Build time, dependency downloads, and container launch are not included in runtime measurements.

Native compilation costs cover the compiler process and its children during image build, excluding Gradle, downloads, and image preparation. Artifact sizes exclude base images and shared libraries; comparing executable size against JAR size alone does not account for the JVM needed to deploy the JAR. Both timed example 03 modes run in the same benchmark container; the native production container uses Oracle Linux without a JDK.

## HTTP service benchmarks

`make test-app EXAMPLE=08` builds and starts the selected HTTP application, waits for readiness and shows verified sample API requests. `http_test_app.py` is the shared client for examples 04–08: it prints curl equivalents and formatted JSON for readiness, product, quote and computation responses, plus resource/reflection checks where supported. It runs in the selected project's benchmark image and connects to the application over its Compose network. The application stays running. Repeat the same command to check it again; `make clean` stops it. CLI examples 01–03 execute their application directly through `make test-app`.

`http_run.py` measures the independent Spring services. Example 04 measures its ordinary JVM; example 05 compares Spring AOT off/on using the same processed JAR; example 06 compares its baseline and two JVM AOT caches with Spring AOT disabled. Example 07 compares its processed JVM deployment (Spring AOT disabled) with a Spring AOT native executable. Example 08 compares its ordinary JVM baseline with Spring AOT plus its matching JVM cache. Example 09 builds distinct ordinary and processed deployments, then compares baseline, Spring AOT, JVM cache, Spring AOT plus JVM cache, and native execution. Example 09 is a comparison suite with no default `make test-app` application. No example builds another application's source.

JVM modes share the pinned Temurin image, G1 and a 256 MiB maximum heap. Native uses pinned GraalVM Community 25.0.2 and Serial GC, with the same heap and application container limits (one CPU, 512 MiB). Both Spring native build inputs are compiled with GraalVM's Java 25 JDK; runtime JVM/cache training uses Temurin 25.0.4.1. Versions/digests and per-mode collectors are recorded, so native comparisons identify these deployment differences.

`http_common.py` defines the fixed HTTP contract, polling, process lifecycle and application RSS sampling. `http_smoke.py` checks resources, JSON, quotes, checksums, bounds and invalid requests in every mode. Examples 05, 07, 08 and 09 also check that AOT fixes the build-time profile's beans. `http_cache_check.py` confirms application classes load from every configured archive and requires missing caches and a same-path changed JAR to fail in strict mode. The original JAR and its timestamps are restored and valid execution is checked again. Diagnostics stay outside measured starts.

The default `SUITE=startup` runs two unmeasured processes per mode and 30 measured processes per mode, in a seeded shuffled order with a 100 ms untimed launch interval. Measurements include HTTP readiness, first verified product/quote responses, readiness/idle RSS, and whole-process peak RSS. Readiness polling is every 20 ms, which adds uncertainty along with probe time. First product and quote requests are sequential after readiness; their timestamps are cumulative since process launch. Peak memory covers verification and shutdown as well. Container launch and build/diagnostic checks are excluded. These are fresh JVM/native processes with ordinary OS page cache.

Startup terminal and HTML tables show median readiness RSS and median peak RSS in MiB, calculated across measured processes. The memory reduction column compares readiness RSS with the baseline. Load tables show median process RSS sampled after each measured load window, across repetitions. The existing JSON summary fields retain their units: HTTP RSS fields are KiB; CLI `peak_rss_mib` is MiB. Raw JSONL/CSV evidence records each process's memory samples.

Examples 08 and 09's startup and `all` suites begin with a compact combined comparison in both the terminal and HTML report. Example 08 has two rows and Example 09 has five: readable mode names, median startup with units and thousands separators, and median readiness memory in MiB. Detailed startup, optional load and preparation tables follow. A load-only suite has no startup summary.

`SUITE=load` uses `http_load.py` in a separate Python process: one keep-alive connection, a fixed offered rate, and a rotating product/quote/compute mix. Defaults are `LOAD_RUNS=5 LOAD_WARMUP=30 LOAD_SECONDS=60 RATE=100`. `SUITE=all` runs both suites. Every response is verified; failed requests/timeouts or an unsustained rate fail the comparison. Per-request JSON records latency, route and schedule lag. The client has its own two-CPU Compose container; the application has a separate one-CPU limit; throughput is bounded by the offered rate and does not establish maximum server capacity. Short checks can override these options but do not establish steady-state behavior.

The HTTP reports include startup and optional load tables, sample counts and reductions, deployment JAR/library hashes and sizes, exact versions/digests, resource limits, and packaging/training costs. Example 05 saves its generated Spring source tree as a ZIP. Example 06 saves cache hashes/sizes, training inputs/costs, verification logs and negative-check diagnostics. JSONL, CSV and HTML stay under `results/04-spring-java-baseline/`, `results/05-spring-aot-cache/`, or `results/06-spring-jvm-aot-cache/` and are never committed.

Packaging measurements include Gradle tests and any uncached dependency downloads; example 05 includes Spring AOT processing. They do not isolate its incremental cost. Training measurements include shutdown and cache assembly, and workload training includes its HTTP client. Preparation metrics may come from reused image layers. Application deployment size includes the extracted JAR and libraries; caches are reported separately, excluding the Java runtime/base image.

Examples 07 and 09 save native compilation time/memory, executable size/hash, compiler logs and generated Spring sources. `http_native_check.py` verifies a Linux ELF executable and the resource/reflection endpoint. It deliberately calls an unregistered policy method, requires HTTP 500 with a `MissingReflectionRegistrationError` diagnostic naming that method, and verifies normal execution again. Those checks are excluded from timing. Production-image checks require no Java installation or application JAR.

Examples 08 and 09 verify archive use against each matching deployment, including the generated initializer in the combined cache. They reject missing caches, changed JARs and cross-deployment cache pairing, then restore timestamps and recheck valid execution. Both reports identify separate ordinary/AOT packaging and cache training costs; Example 09 also reports native compilation. Example 08 trains only the combined cache; Example 09 trains both matching caches. Native compilation cost for 07/09 includes the Gradle invocation and children after packaging; example 03's compiler-only measurement retains its narrower scope. Preparation cost may include uncached downloads or be reused from Docker layers. No artifact-size comparison includes the JVM/base image or shared-library deployment cost.

Evidence goes to ignored `results/07-spring-aot-graalvm-native/`, `results/08-spring-aot-jvm-aot-cache/` and `results/09-combined-comparison/`. Example 09's four JVM rows form a two-by-two comparison; native is the separate Spring AOT deployment alternative. Native executables cannot consume HotSpot AOT archives.
