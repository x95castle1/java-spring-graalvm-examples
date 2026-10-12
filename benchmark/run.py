#!/usr/bin/env python3
"""Measure fresh JVM or native processes inside one container; verify every result."""

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import html
import json
import math
import os
from pathlib import Path
import platform
import random
import shutil
import signal
import statistics
import subprocess
import sys
import tempfile
import time

JAVA_COMMAND = ["java", "-Xmx256m", "-XX:+UseG1GC", "-jar", "/app/plain-java.jar"]
NATIVE_COMMAND = ["/app/catalog-cli", "-Xmx256m"]
EXAMPLE_ID = os.environ.get("EXAMPLE_ID", "01-plain-java")
MAX_ITERATIONS = 10_000_000


def cache_command(recipe):
    return [*JAVA_COMMAND[:3], "-XX:AOTMode=on", f"-XX:AOTCache=/app/{recipe}.aot", *JAVA_COMMAND[3:]]


def expected_checksum(iterations):
    """An independent implementation of the Java workload, outside timed runs."""
    value = 0x1234ABCD
    mask = (1 << 64) - 1
    for _ in range(iterations):
        value ^= (value << 13) & mask
        value ^= value >> 7
        value ^= (value << 17) & mask
    return value if value < (1 << 63) else value - (1 << 64)


def verify_output(output, iterations, checksum):
    expected = {
        "application": "catalog-cli",
        "iterations": iterations,
        "productCount": 8,
        "subtotalCents": 22_300,
        "discountCents": 2230,
        "totalCents": 20_070,
        "checksum": checksum,
    }
    for field, value in expected.items():
        if output.get(field) != value:
            raise ValueError(f"Incorrect {field}: expected {value!r}, got {output.get(field)!r}")
    if str(output.get("javaVersion", "")).split(".")[0] != "25":
        raise ValueError("These examples require Java 25")


def percentile(values, percent):
    ordered = sorted(values)
    position = (len(ordered) - 1) * percent / 100
    lower = math.floor(position)
    upper = math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def summarize(records, variant="plain-jvm-baseline"):
    elapsed = [record["elapsed_ms"] for record in records]
    memory = [record["peak_rss_kib"] / 1024 for record in records]
    return {
        "variant": variant,
        "runs": len(records),
        "completion_ms": {
            "min": min(elapsed),
            "median": statistics.median(elapsed),
            "p95": percentile(elapsed, 95),
            "max": max(elapsed),
            "stddev": statistics.stdev(elapsed) if len(elapsed) > 1 else 0,
        },
        "peak_rss_mib": {
            "median": statistics.median(memory),
            "p95": percentile(memory, 95),
            "max": max(memory),
        },
        "mean_cpu_seconds": statistics.mean(
            record["user_cpu_seconds"] + record["system_cpu_seconds"] for record in records
        ),
    }


def read_optional(path):
    location = Path(path)
    return location.read_text().strip() if location.is_file() else None


def cpu_throttling():
    contents = read_optional("/sys/fs/cgroup/cpu.stat")
    return dict(line.split() for line in contents.splitlines()) if contents else {}


def environment(command, args):
    java = subprocess.run(["java", "-version"], capture_output=True, text=True, check=True)
    return {
        "example": EXAMPLE_ID,
        "variant": {"02-plain-jvm-aot-cache": "plain-jvm-cache-comparison",
                    "03-plain-graalvm-native": "plain-native-comparison"}.get(EXAMPLE_ID, "plain-jvm-baseline"),
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "command": command,
        "iterations": args.iterations,
        "warmup_processes": args.warmups,
        "measured_processes": args.runs,
        "java_version": (java.stdout + java.stderr).strip(),
        "java_image": read_optional("/app/java-image.txt"),
        "source_sha256": read_optional("/app/source.sha256"),
        "jar_sha256": hashlib.sha256(Path("/app/plain-java.jar").read_bytes()).hexdigest(),
        "jar_bytes": Path("/app/plain-java.jar").stat().st_size,
        "os": platform.system(),
        "kernel": platform.release(),
        "architecture": platform.machine(),
        "python_version": platform.python_version(),
        "cpu_max": read_optional("/sys/fs/cgroup/cpu.max"),
        "memory_max_bytes": read_optional("/sys/fs/cgroup/memory.max"),
        "measurement": "Fresh process completion, including GNU time wrapper overhead; excludes container startup",
        "memory_method": "GNU time %M: child-process peak RSS in KiB, not heap size or container memory",
        "filesystem_cache": "Ordinary OS page cache; warmup processes run first",
        "jvm_cache": "No application AOT cache; default JVM CDS remains enabled",
        "percentile_method": "Linear interpolation; p95 is descriptive at this sample count",
    }


def measure(command, iterations, checksum, timeout):
    with tempfile.TemporaryDirectory(prefix="aot-baseline-") as directory:
        metrics_path = Path(directory) / "time.json"
        measured_command = [
            "/usr/bin/time", "--quiet", "--output", str(metrics_path),
            "--format", '{"user_cpu_seconds":%U,"system_cpu_seconds":%S,"peak_rss_kib":%M}',
            *command,
        ]
        before = cpu_throttling()
        started = time.perf_counter_ns()
        with subprocess.Popen(
            measured_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, start_new_session=True,
        ) as process:
            try:
                stdout, stderr = process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate()
                raise RuntimeError(f"Application exceeded {timeout} seconds") from None
            elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
            if process.returncode != 0:
                raise RuntimeError(f"Application exited {process.returncode}: {stderr.strip()}")
        output = json.loads(stdout)
        verify_output(output, iterations, checksum)
        metrics = json.loads(metrics_path.read_text())
        if metrics["peak_rss_kib"] <= 0:
            raise RuntimeError("GNU time did not record peak RSS")
        after = cpu_throttling()
        throttling = {
            "cpu_throttled_periods": int(after.get("nr_throttled", 0)) - int(before.get("nr_throttled", 0)),
            "cpu_throttled_usec": int(after.get("throttled_usec", 0)) - int(before.get("throttled_usec", 0)),
        }
        return {"elapsed_ms": elapsed_ms, **metrics, **throttling, "output": output}


def summary_rows(summary):
    completion = summary["completion_ms"]
    memory = summary["peak_rss_mib"]
    return [
        ("Measured JVM processes", str(summary["runs"])),
        ("Completion median", f'{completion["median"]:.2f} ms'),
        ("Completion p95", f'{completion["p95"]:.2f} ms'),
        ("Completion range", f'{completion["min"]:.2f}–{completion["max"]:.2f} ms'),
        ("Median peak memory (RSS)", f'{memory["median"]:.2f} MiB'),
        ("Peak process RSS maximum", f'{memory["max"]:.2f} MiB'),
        ("Mean process CPU time", f'{summary["mean_cpu_seconds"]:.3f} seconds'),
    ]


def format_table(rows):
    """Render open tables with aligned values and optional terminal colors."""
    widths = [max(len(row[column]) for row in rows) for column in range(len(rows[0]))]
    force_color = os.environ.get("FORCE_COLOR")
    interactive = sys.stdout.isatty()
    color = interactive and os.environ.get("TERM") != "dumb"
    if force_color is not None:
        color = force_color not in ("", "0")
    if os.environ.get("NO_COLOR"):
        color = False

    def paint(value, style):
        return f"\033[{style}m{value}\033[0m" if color else value

    def render(columns):
        def format_row(row):
            return "   ".join(row[column].ljust(widths[column]) if column == 0
                              else row[column].rjust(widths[column]) for column in columns)

        separator = paint("   ".join("─" * widths[column] for column in columns), "38;2;65;71;77")
        lines = [paint(format_row(rows[0]), "1;38;2;255;221;161"), separator]
        for index, row in enumerate(rows[1:]):
            lines.append(paint(format_row(row), "38;2;216;217;219"))
            if index < len(rows) - 2:
                lines.append(separator)
        return "\n".join(lines)

    # Repeat the row label when detailed tables need multiple groups to fit the terminal.
    groups, columns = [], [0]
    available = shutil.get_terminal_size(fallback=(120, 24)).columns if interactive else None
    for column in range(1, len(widths)):
        if available and len(columns) > 1 and sum(widths[i] for i in columns) + widths[column] + 3 * len(columns) > available:
            groups.append(columns)
            columns = [0]
        columns.append(column)
    groups.append(columns)
    return "\n\n".join(render(columns) for columns in groups)


def format_summary_table(summary):
    return format_table([("Metric", "Result"), *summary_rows(summary)])


def report_link(path):
    """Link container reports to the corresponding file on the host."""
    path = Path(path).absolute()
    host_results = os.environ.get("REPORT_HOST_RESULTS")
    if host_results and path.is_relative_to("/results"):
        path = Path(host_results) / path.relative_to("/results")
    uri = path.as_uri()
    if sys.stdout.isatty() and os.environ.get("TERM") != "dumb":
        return f"\033]8;;{uri}\033\\{uri}\033]8;;\033\\"
    return uri


def comparison_rows(summaries):
    baseline = summaries["baseline"]
    rows = [("Variant", "Runs", "Median ms", "p95 ms", "Median peak RSS MiB", "Time reduction", "RSS reduction")]
    for variant, summary in summaries.items():
        elapsed = summary["completion_ms"]["median"]
        rss = summary["peak_rss_mib"]["median"]
        rows.append((variant, str(summary["runs"]), f"{elapsed:.2f}",
                     f'{summary["completion_ms"]["p95"]:.2f}', f"{rss:.2f}",
                     f'{reduction(baseline["completion_ms"]["median"], elapsed):+.1f}%',
                     f'{reduction(baseline["peak_rss_mib"]["median"], rss):+.1f}%'))
    return rows


def reduction(baseline, value):
    return 100 * (baseline - value) / baseline


def prepare_caches(args, directory, metadata):
    from cache_check import verify_cache, verify_invalid_caches

    metadata["training"] = {}
    metadata["jvm_cache"] = "Baseline: default CDS. Cache variants: strict AOTMode=on; application cache."
    for recipe in ("short", "workload"):
        log = verify_cache(recipe, args.iterations)
        (directory / f"{recipe}-verification.log").write_text(log)
        archive = Path(f"/app/{recipe}.aot")
        training = json.loads(Path(f"/app/{recipe}-training.json").read_text())
        training.update({
            "iterations": 1 if recipe == "short" else int(read_optional("/app/training-iterations.txt")),
            "cache_bytes": archive.stat().st_size,
            "cache_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            "command": [*JAVA_COMMAND[:3], f"-XX:AOTCacheOutput=/app/{recipe}.aot",
                        f"-Xlog:aot=info:file=/app/{recipe}-training.log", *JAVA_COMMAND[3:],
                        "--iterations", "1" if recipe == "short" else read_optional("/app/training-iterations.txt")],
            "cost_scope": "Training plus child cache assembly; excludes Gradle, downloads, and Docker image build",
        })
        metadata["training"][recipe] = training
        shutil.copyfile(f"/app/{recipe}-training.log", directory / f"{recipe}-training.log")
    verify_invalid_caches()
    metadata["cache_verification"] = "Application classes loaded from cache; missing cache and changed JAR rejected"


def prepare_native(args, directory, metadata):
    from native_check import verify_native

    info = verify_native(args.iterations, args.timeout)
    metadata.update({
        "native_build": info,
        "native_image": read_optional("/app/native-image.txt"),
        "native_version": read_optional("/app/native-version.txt"),
        "native_runtime_image": read_optional("/app/runtime-image.txt"),
        "garbage_collectors": {"baseline": "HotSpot G1", "native": "GraalVM Community Serial"},
        "max_heap_bytes": 256 * 1024**2,
        "native_verification": "ELF executable; embedded catalog, quote, and checksum verified before timing",
        "runtime_images": "Both timed modes run in the same Temurin benchmark image; native deployment uses Oracle Linux without a JDK",
    })
    shutil.copyfile("/app/native-build.log", directory / "native-build.log")
    (directory / "native-verification.json").write_text(json.dumps(info["verification_output"], indent=2) + "\n")


def compare(args, directory):
    native = EXAMPLE_ID == "03-plain-graalvm-native"
    commands = {"baseline": JAVA_COMMAND, "native": NATIVE_COMMAND} if native else {
        "baseline": JAVA_COMMAND,
        "short-cache": cache_command("short"),
        "workload-cache": cache_command("workload"),
    }
    phase = "verification"
    metadata = environment(JAVA_COMMAND, args)
    metadata.update({
        "commands": commands,
        "order": "Seeded shuffle of all variants in each round",
        "seed": args.seed,
        "launch_interval_seconds": args.interval,
        "runs_per_variant": args.runs,
        "measured_processes": args.runs * len(commands),
        "total_measured_processes": args.runs * len(commands),
    })
    variant = None
    run = 0
    try:
        if native:
            prepare_native(args, directory, metadata)
        else:
            prepare_caches(args, directory, metadata)
        (directory / "environment.json").write_text(json.dumps(metadata, indent=2) + "\n")
        checksum = expected_checksum(args.iterations)
        phase = "warmup"
        for _ in range(args.warmups):
            for variant, command in commands.items():
                time.sleep(args.interval)
                measure([*command, "--iterations", str(args.iterations)], args.iterations, checksum, args.timeout)
        phase = "measurement"
        records = {variant: [] for variant in commands}
        order = random.Random(args.seed)
        with (directory / "runs.jsonl").open("w") as output:
            for run in range(1, args.runs + 1):
                variants = list(commands)
                order.shuffle(variants)
                for variant in variants:
                    time.sleep(args.interval)
                    measured = measure([*commands[variant], "--iterations", str(args.iterations)],
                                       args.iterations, checksum, args.timeout)
                    record = {"run": run, "variant": variant, **measured}
                    records[variant].append(record)
                    output.write(json.dumps(record) + "\n")
                    output.flush()
                    print(f'{variant} {run}/{args.runs}: {record["elapsed_ms"]:.2f} ms, '
                          f'peak RSS {record["peak_rss_kib"] / 1024:.2f} MiB', flush=True)
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as exception:
        failure = {"phase": phase, "variant": variant, "run": run, "error": str(exception)}
        (directory / "failure.json").write_text(json.dumps(failure, indent=2) + "\n")
        (directory / "environment.json").write_text(json.dumps(metadata, indent=2) + "\n")
        print(f"Benchmark failed: {exception}\nEvidence: {directory}", file=sys.stderr)
        return 1

    with (directory / "runs.csv").open("w", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=["variant", "run", "elapsed_ms", "user_cpu_seconds",
                                                    "system_cpu_seconds", "peak_rss_kib", "cpu_throttled_periods",
                                                    "cpu_throttled_usec"], extrasaction="ignore")
        writer.writeheader()
        for samples in records.values():
            writer.writerows(samples)
    summaries = {variant: summarize(samples, variant) for variant, samples in records.items()}
    summary = {"example": EXAMPLE_ID, "variants": summaries, "environment": metadata}
    (directory / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    rows = comparison_rows(summaries)
    table = "\n".join("<tr>" + "".join(f"<td>{html.escape(value)}</td>" for value in row) + "</tr>" for row in rows)
    if native:
        info = metadata["native_build"]
        title = "03 — GraalVM Native Image comparison"
        introduction = ("Identical input JAR and workload, 256 MiB maximum heap, CPU and memory limits. "
                        "Each round shuffles a fresh JVM process and a fresh native process. "
                        "HotSpot uses G1; GraalVM Community native uses Serial GC. "
                        "Exact JVM and embedded native Java versions are recorded in the environment file. "
                        "Both timed modes use the same benchmark container; native deployment runs without a JDK.")
        training_rows = [("Build", "Compile s", "Peak RSS MiB", "Executable MiB", "Input JAR KiB"),
                         ("native", f'{info["elapsed_seconds"]:.2f}', f'{info["peak_rss_kib"] / 1024:.2f}',
                          f'{info["executable_bytes"] / 1024**2:.2f}', f'{metadata["jar_bytes"] / 1024:.2f}')]
        preparation_note = ("Compilation cost was measured during image build and may come from a cached layer. "
                            "It excludes Gradle, dependency downloads, and image preparation. "
                            "Artifact sizes exclude base images and shared libraries: a JAR also requires a JVM. "
                            "The native executable includes its runtime. This CLI comparison does not measure sustained throughput.")
        evidence_links = '<a href="artifacts/native-verification.json">Native verification</a>, <a href="artifacts/native-build.log">Native compilation</a>'
    else:
        title = "02 — JVM AOT cache comparison"
        introduction = ("Identical JAR, Java image, heap, GC, CPU and memory limits. Each round shuffles three fresh JVM processes. "
                        "The baseline uses ordinary default CDS. Both cache variants passed strict verification.")
        training_rows = [("Recipe", "Iterations", "Train + assemble s", "Peak RSS MiB", "Cache MiB")]
        for recipe, info in metadata["training"].items():
            training_rows.append((recipe, str(info["iterations"]), f'{info["elapsed_seconds"]:.2f}',
                                  f'{info["peak_rss_kib"] / 1024:.2f}', f'{info["cache_bytes"] / 1024**2:.2f}'))
        preparation_note = ("Training costs were measured when the image was built; Docker may reuse those build layers. "
                            "They cover recording and cache assembly, excluding Gradle and image preparation. "
                            "Peak RSS is GNU time's process/child maximum, rather than combined concurrent memory. "
                            "Each cache is an additional deployment artifact.")
        evidence_links = ('<a href="artifacts/short-verification.log">Short cache verification</a>, '
                          '<a href="artifacts/workload-verification.log">Workload cache verification</a>, '
                          '<a href="artifacts/short-training.log">Short training</a>, <a href="artifacts/workload-training.log">Workload training</a>')
    training_table = "\n".join("<tr>" + "".join(f"<td>{html.escape(value)}</td>" for value in row) + "</tr>"
                               for row in training_rows)
    (directory.parent / "report.html").write_text(f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>{title}</title>
<style>body{{font:16px system-ui;max-width:1050px;margin:48px auto;padding:0 20px}}
table{{border-collapse:collapse;width:100%}}td{{padding:10px;border-bottom:1px solid #ddd}}
tr:first-child{{font-weight:bold}}a{{color:#1264a3}}</style></head><body>
<h1>{title}</h1>
<p>{introduction}</p>
<p>Launches have a {args.interval:g}-second quiet interval outside timing to reduce carryover CPU-quota effects.
Raw records include cgroup throttle counters for each sample.</p>
<table>{table}</table>
<p>Positive reductions indicate improvement; negative values indicate regression.
Completion includes GNU time overhead and excludes container launch, validation, training and verbose logging.
Memory is the median of each measured process's peak RSS, including heap and runtime overhead.
It is not the heap limit or total container memory. These runs use the ordinary OS page cache.
p95 is descriptive at this sample count.</p>
<h2>Preparation and deployment cost</h2><table>{training_table}</table>
<p>{preparation_note}</p>
<p>Evidence: <a href="artifacts/runs.csv">CSV</a>, <a href="artifacts/runs.jsonl">JSON records</a>,
<a href="artifacts/summary.json">Summary</a>, <a href="artifacts/environment.json">Environment and recipes</a>, {evidence_links}.</p>
</body></html>""")
    print(f"\n{EXAMPLE_ID} comparison (positive reduction = improvement)\n")
    print(format_table(rows))
    print("\nPreparation costs recorded during image build\n")
    print(format_table(training_rows))
    print(f"\nReport: {report_link(directory.parent / 'report.html')}")
    return 0


def write_report(directory, summary):
    table = "\n".join(
        f"<tr><th>{html.escape(label)}</th><td>{html.escape(value)}</td></tr>"
        for label, value in summary_rows(summary)
    )
    (directory / "report.html").write_text(f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Plain JVM baseline results</title>
<style>body{{font:16px system-ui;max-width:760px;margin:48px auto;padding:0 20px;color:#18232b}}
table{{border-collapse:collapse;width:100%}}th,td{{padding:12px;border-bottom:1px solid #dde3e8;text-align:left}}
th{{font-weight:500}}a{{color:#1264a3}}</style></head><body>
<h1>Plain JVM baseline results</h1>
<p>The catalog CLI ran in a fresh Java 25 process for each sample. Every response and checksum passed verification.</p>
<table>{table}</table>
<p>Completion measures the whole CLI execution and includes a small GNU time wrapper overhead.
Container startup and output verification are excluded. The OS page cache is ordinary;
default JVM CDS remains enabled. Median peak memory is the median of each measured process's peak RSS,
including heap and JVM overhead, rather than the heap limit or total container memory.</p>
<p>p95 uses linear interpolation and is descriptive at this sample count. These measurements establish the baseline for later comparisons.</p>
<p>Raw evidence: <a href="artifacts/runs.csv">CSV</a>, <a href="artifacts/runs.jsonl">JSON records</a>,
<a href="artifacts/summary.json">Summary</a>, <a href="artifacts/environment.json">Environment and command</a>.</p>
</body></html>
""")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=30)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--iterations", type=int, default=100_000)
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--output", type=Path, default=Path("/results"))
    parser.add_argument("--compare", action="store_true", default=EXAMPLE_ID in ("02-plain-jvm-aot-cache", "03-plain-graalvm-native"),
                        help="Compare the ordinary JVM with the selected example's optimized variants (default for 02/03)")
    parser.add_argument("--seed", type=int, default=42, help="Reproducible comparison order")
    parser.add_argument("--interval", type=float, default=0.1, help="Untimed interval between comparison launches")
    args = parser.parse_args()
    if not (1 <= args.runs <= 1000 and 0 <= args.warmups <= 100):
        parser.error("runs must be 1..1000 and warmups must be 0..100")
    if not 1 <= args.iterations <= MAX_ITERATIONS or not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("iterations must be 1..10000000 and timeout must be positive")
    if not math.isfinite(args.interval) or not 0 <= args.interval <= 10:
        parser.error("interval must be 0..10 seconds")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    report_directory = args.output / EXAMPLE_ID / stamp
    directory = report_directory / "artifacts"
    directory.mkdir(parents=True)
    if args.compare:
        if EXAMPLE_ID not in ("02-plain-jvm-aot-cache", "03-plain-graalvm-native"):
            parser.error("--compare requires example 02 or 03's benchmark image")
        return compare(args, directory)
    command = [*JAVA_COMMAND, "--iterations", str(args.iterations)]
    metadata = environment(command, args)
    (directory / "environment.json").write_text(json.dumps(metadata, indent=2) + "\n")
    checksum = expected_checksum(args.iterations)
    phase = "warmup"
    run = 0
    try:
        for run in range(1, args.warmups + 1):
            measure(command, args.iterations, checksum, args.timeout)
        phase = "measurement"
        records = []
        with (directory / "runs.jsonl").open("w") as output:
            for run in range(1, args.runs + 1):
                record = {"run": run, **measure(command, args.iterations, checksum, args.timeout)}
                records.append(record)
                output.write(json.dumps(record) + "\n")
                output.flush()
                print(f'Run {run}/{args.runs}: {record["elapsed_ms"]:.2f} ms, '
                      f'peak RSS {record["peak_rss_kib"] / 1024:.2f} MiB', flush=True)
    except (RuntimeError, ValueError, OSError) as exception:
        failure = {"phase": phase, "run": run, "error": str(exception)}
        (directory / "failure.json").write_text(json.dumps(failure, indent=2) + "\n")
        print(f"Benchmark failed: {exception}\nEvidence: {directory}", file=sys.stderr)
        return 1

    fields = ["run", "elapsed_ms", "user_cpu_seconds", "system_cpu_seconds", "peak_rss_kib"]
    with (directory / "runs.csv").open("w", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    summary = summarize(records)
    summary["environment"] = metadata
    (directory / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    write_report(report_directory, summary)
    print(f'\nBenchmark results: {summary["variant"]}\n')
    print(format_summary_table(summary))
    print(f"\nReport: {report_link(report_directory / 'report.html')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
