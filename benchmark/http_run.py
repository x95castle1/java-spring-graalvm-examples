#!/usr/bin/env python3
"""Compare independently packaged Spring HTTP service modes in fresh JVM and native processes."""

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import html
import http.client
import json
import math
from pathlib import Path
import platform
import random
import shutil
import statistics
import subprocess
import sys
import time

from http_common import DUAL_DEPLOYMENT_EXAMPLES, EXAMPLE_ID, JAR, POLL_INTERVAL, SPRING_EXAMPLES, Server, checksum, commands, mode_aot, process_rss, verify_contract
from run import format_table, percentile, read_optional, reduction, report_link


def describe(values):
    return {"median": statistics.median(values), "p95": percentile(values, 95), "min": min(values), "max": max(values)}


def summarize_startup(records):
    return {"runs": len(records), **{field: describe([record[field] for record in records])
                                    for field in ("ready_ms", "first_product_ms", "first_quote_ms",
                                                  "ready_rss_kib", "idle_rss_kib", "peak_rss_kib")}}


def startup_rows(summaries):
    rows = [("Variant", "Runs", "Ready median ms", "Ready p95 ms", "First quote ms", "Median ready RSS MiB", "Median peak RSS MiB", "Time reduction", "Ready RSS reduction")]
    baseline = summaries["baseline"]
    for variant, summary in summaries.items():
        ready, rss = summary["ready_ms"]["median"], summary["ready_rss_kib"]["median"]
        rows.append((variant, str(summary["runs"]), f"{ready:.2f}", f'{summary["ready_ms"]["p95"]:.2f}',
                     f'{summary["first_quote_ms"]["median"]:.2f}', f"{rss / 1024:.2f}",
                     f'{summary["peak_rss_kib"]["median"] / 1024:.2f}',
                     f'{reduction(baseline["ready_ms"]["median"], ready):+.1f}%',
                     f'{reduction(baseline["ready_rss_kib"]["median"], rss):+.1f}%'))
    return rows


def combined_rows(summaries):
    rows = [("Mode", "Median startup", "Median memory")]
    for variant, label in (("baseline", "Baseline"), ("spring-aot", "Spring AOT"),
                           ("jvm-cache", "JVM cache"), ("spring-aot-cache", "Spring AOT + JVM cache"),
                           ("native", "Native")):
        if variant in summaries:
            info = summaries[variant]
            rows.append((label, f'{info["ready_ms"]["median"]:,.0f} ms',
                         f'{info["ready_rss_kib"]["median"] / 1024:,.2f} MiB'))
    return rows


def environment(args, variants):
    main_dir = Path("/app/plain") if EXAMPLE_ID in DUAL_DEPLOYMENT_EXAMPLES else Path("/app")
    files = [main_dir / "catalog-service.jar", *sorted((main_dir / "lib").rglob("*.jar"))]
    artifacts = [{"path": str(path), "bytes": path.stat().st_size,
                  "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in files]
    java = subprocess.run(["java", "-version"], capture_output=True, text=True, check=True)
    return {
        "example": EXAMPLE_ID, "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "commands": variants, "arguments": {key: str(value) if isinstance(value, Path) else value for key, value in vars(args).items()},
        "java_version": (java.stdout + java.stderr).strip(), "spring_boot_version": read_optional("/app/boot-version.txt"),
        "java_image": read_optional("/app/java-image.txt"), "source_sha256": read_optional("/app/source.sha256"),
        "deployment_artifacts": artifacts, "deployment_bytes": sum(item["bytes"] for item in artifacts),
        "architecture": platform.machine(), "kernel": platform.release(), "python_version": platform.python_version(),
        "cpu_max": read_optional("/sys/fs/cgroup/cpu.max"), "memory_max_bytes": read_optional("/sys/fs/cgroup/memory.max"),
        "gc": "G1", "max_heap_mib": 256, "order": "Seeded shuffle within each round", "seed": args.seed,
        "poll_interval_ms": POLL_INTERVAL * 1000,
        "startup_scope": "GNU time/process launch to verified HTTP readiness; excludes container start, builds, and diagnostic verification",
        "first_response_scope": "Elapsed since process launch through verified product/quote body; one request follows the other",
        "rss_method": "Application /proc VmRSS at readiness and after an idle interval; GNU time child peak over the entire run",
        "filesystem_cache": "Ordinary OS page cache; fresh JVM and native processes, not disk-cold launches",
        "load_method": "Separate Compose client container (2 CPUs, 256 MiB), one keep-alive connection, fixed offered rate; Application container has 1 CPU, 512 MiB",
        "load_latency_scope": "Request roundtrip including JSON decoding/verification; no maximum-capacity or concurrency claim",
        "jvm_cache": "Baseline uses default CDS; cache modes require strict AOTMode=on",
        "packaging": {**json.loads(Path("/app/plain-packaging.json" if EXAMPLE_ID in DUAL_DEPLOYMENT_EXAMPLES else "/app/packaging.json").read_text()),
                      "scope": "Gradle build including tests and Spring AOT when enabled; may include uncached downloads, excludes Docker preparation/extraction"},
    }


def prepare(args, directory, metadata):
    if EXAMPLE_ID in DUAL_DEPLOYMENT_EXAMPLES:
        for kind in ("plain", "aot"):
            shutil.copyfile(f"/app/{kind}-packaging.log", directory / f"{kind}-packaging.log")
        aot_files = [Path("/app/aot/catalog-service.jar"), *sorted(Path("/app/aot/lib").rglob("*.jar"))]
        metadata["aot_deployment_artifacts"] = [{"path": str(path), "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in aot_files]
        metadata["aot_deployment_bytes"] = sum(path.stat().st_size for path in aot_files)
        metadata["aot_packaging"] = json.loads(Path("/app/aot-packaging.json").read_text())
        metadata["deployment_layout"] = "Plain JAR for the ordinary baseline; processed JAR with its matching combined cache; 09 also compares the individual JVM features and native execution"
    else:
        shutil.copyfile("/app/packaging.log", directory / "packaging.log")
    if EXAMPLE_ID in ("05-spring-aot-cache", "07-spring-aot-graalvm-native", *DUAL_DEPLOYMENT_EXAMPLES):
        generated = Path("/app/spring-aot")
        sources = sorted(generated.rglob("*.java"))
        if not sources or not any("CatalogApplication__ApplicationContextInitializer" in path.name for path in sources):
            raise ValueError("Missing Spring AOT generated application initializer")
        metadata["spring_aot"] = {"generated_java_files": len(sources),
                                  "generated_bytes": sum(path.stat().st_size for path in generated.rglob("*") if path.is_file()),
                                  "build_task": "processAot", "bean_profile": "default"}
        shutil.make_archive(str(directory / "spring-aot-sources"), "zip", generated)
    if EXAMPLE_ID in ("06-spring-jvm-aot-cache", *DUAL_DEPLOYMENT_EXAMPLES):
        from http_cache_check import verify
        verify(directory, args.iterations)
        metadata["cache_verification"] = "Application classes loaded from matching caches; missing cache and same-path changed JAR rejected; restored JAR reverified; 08/09 also reject cross-deployment caches"
        metadata["training"] = {}
        recipes = (("short", "workload") if EXAMPLE_ID == "06-spring-jvm-aot-cache" else
                   ("spring-aot-cache",) if EXAMPLE_ID == "08-spring-aot-jvm-aot-cache" else
                   ("jvm-cache", "spring-aot-cache"))
        for recipe in recipes:
            archive = Path(f"/app/{recipe}.aot")
            metadata["training"][recipe] = {
                **json.loads(Path(f"/app/{recipe}-training.json").read_text()),
                "cache_bytes": archive.stat().st_size, "cache_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                "http_requests": 0 if recipe == "short" else int(read_optional("/app/training-requests.txt")),
                "compute_iterations": None if recipe == "short" else int(read_optional("/app/training-iterations.txt")),
                "scope": "Training, graceful shutdown and child cache assembly; workload includes HTTP client; excludes Gradle and Docker preparation",
            }
            shutil.copyfile(f"/app/{recipe}-training.log", directory / f"{recipe}-training.log")
    if EXAMPLE_ID in ("07-spring-aot-graalvm-native", "09-combined-comparison"):
        from http_native_check import verify_native
        metadata["native_build"] = verify_native(args.iterations, args.timeout, directory)
        metadata["garbage_collectors"] = {name: "Serial" if name == "native" else "G1" for name in commands()}
        metadata["deployment_layout"] = "09: plain JAR for baseline/JVM cache, processed JAR for Spring AOT/combined cache/native input; 07: processed JAR for JVM/native input"
        metadata["compiler_java"] = read_optional("/app/native-version.txt")
        metadata["gc"] = "Per variant: JVM G1, native Serial"
        shutil.copyfile("/app/native-build.log", directory / "native-build.log")
    for variant, command in commands().items():
        with Server(command, directory, f"{variant}-preflight", aot=mode_aot(variant), timeout=args.timeout) as server:
            verify_contract(server.connection, args.iterations)
        metadata.setdefault("verified_modes", {})[variant] = server.ready_output


def startup(command, variant, label, args, directory):
    with Server(command, directory, label, aot=mode_aot(variant), timeout=args.timeout) as server:
        verify_contract(server.connection, args.iterations)
        time.sleep(args.idle)
        record = {**server.startup, "idle_rss_kib": process_rss(server.pid)}
    return {**record, **server.metrics}


def load(command, variant, label, args, directory):
    with Server(command, directory, label, aot=mode_aot(variant), timeout=args.timeout) as server:
        verify_contract(server.connection, args.iterations)
        output = directory / f"{label}-requests.json"
        client = http.client.HTTPConnection("http-load-client", 9000,
                                           timeout=args.load_warmup + 2 * args.load_seconds + 60)
        try:
            job = {"warmup": args.load_warmup, "duration": args.load_seconds, "rate": args.rate,
                   "iterations": args.iterations, "output": str(output)}
            client.request("POST", "/run", json.dumps(job), {"Content-Type": "application/json"})
            response = client.getresponse()
            reply = response.read().decode()
            if response.status != 200:
                raise RuntimeError(f"Separate HTTP client failed: {reply}; see {output}")
        finally:
            client.close()
        record = json.loads(output.read_text())
        if not record["client_kept_up"]:
            raise RuntimeError(f"Load client/server did not sustain offered rate; see {output}. Lower RATE before comparing latency.")
        record.pop("samples")  # Per-request records remain in the linked file.
        record.update({"steady_rss_kib": process_rss(server.pid), "request_evidence": output.name})
    return {**record, **server.metrics}


def write_report(directory, summary, metadata):
    tables = []
    if EXAMPLE_ID in DUAL_DEPLOYMENT_EXAMPLES and summary["startup"]:
        rows = combined_rows(summary["startup"])
        title = "Spring AOT + JVM cache comparison" if EXAMPLE_ID == "08-spring-aot-jvm-aot-cache" else "Combined comparison"
        print(f"\n{title} (fresh-process medians)\n")
        print(format_table(rows))
        print("\nMemory is process RSS at readiness. Detailed tables include peak memory and sample counts.")
        tables.append((f"{title} — medians", rows))
    if summary["startup"]:
        rows = startup_rows(summary["startup"])
        print("\nStartup comparison (positive reduction = improvement)\n")
        print(format_table(rows))
        tables.append(("Fresh-process startup", rows))
    if summary["load"]:
        rows = [("Variant", "Runs", "Requests/s", "p50 ms", "p95 ms", "p99 ms", "Median load RSS MiB", "p95 reduction")]
        baseline = summary["load"]["baseline"]["p95_ms"]["median"]
        for variant, info in summary["load"].items():
            rows.append((variant, str(info["runs"]), f'{info["requests_per_second"]["median"]:.2f}',
                         f'{info["p50_ms"]["median"]:.2f}', f'{info["p95_ms"]["median"]:.2f}',
                         f'{info["p99_ms"]["median"]:.2f}', f'{info["steady_rss_kib"]["median"] / 1024:.2f}',
                         f'{reduction(baseline, info["p95_ms"]["median"]):+.1f}%'))
        print("\nPaced HTTP load (throughput limited by the offered rate)\n")
        print(format_table(rows))
        tables.append(("Paced HTTP load", rows))
    info = metadata["packaging"]
    rows = [("Preparation", "Seconds", "Peak RSS MiB", "Artifact MiB"),
            ("Gradle packaging" + (" + Spring AOT" if EXAMPLE_ID in ("05-spring-aot-cache", "07-spring-aot-graalvm-native") else ""),
             f'{info["elapsed_seconds"]:.2f}', f'{info["peak_rss_kib"] / 1024:.2f}', f'{metadata["deployment_bytes"] / 1024**2:.2f}')]
    if "aot_packaging" in metadata:
        info = metadata["aot_packaging"]
        rows.append(("Gradle AOT packaging", f'{info["elapsed_seconds"]:.2f}',
                     f'{info["peak_rss_kib"] / 1024:.2f}', f'{metadata["aot_deployment_bytes"] / 1024**2:.2f}'))
    if "native_build" in metadata:
        info = metadata["native_build"]
        rows.append(("Gradle native compilation", f'{info["elapsed_seconds"]:.2f}',
                     f'{info["peak_rss_kib"] / 1024:.2f}', f'{info["executable_bytes"] / 1024**2:.2f}'))
    for recipe, info in metadata.get("training", {}).items():
        rows.append((f"{recipe} training + assembly", f'{info["elapsed_seconds"]:.2f}',
                     f'{info["peak_rss_kib"] / 1024:.2f}', f'{info["cache_bytes"] / 1024**2:.2f}'))
    print("\nPreparation costs recorded during image build (layers may be cached)\n")
    print(format_table(rows))
    tables.append(("Preparation and deployment artifacts", rows))
    table_html = "".join(f"<h2>{html.escape(title)}</h2><table>" + "".join(
        "<tr>" + "".join(f"<td>{html.escape(cell)}</td>" for cell in row) + "</tr>" for row in rows) + "</table>" for title, rows in tables)
    files = [path for path in sorted((directory / "artifacts").iterdir()) if path.is_file()]
    links = ", ".join(f'<a href="artifacts/{html.escape(path.name)}">{html.escape(path.name)}</a>' for path in files)
    (directory / "report.html").write_text(f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>{EXAMPLE_ID} results</title><style>body{{font:16px system-ui;max-width:1200px;margin:40px auto;padding:0 20px}}
table{{border-collapse:collapse;width:100%}}td{{padding:9px;border-bottom:1px solid #ddd}}tr:first-child{{font-weight:bold}}</style></head>
<body><h1>{EXAMPLE_ID}</h1>{table_html}
<p>The workload and container limits are fixed. JVM modes use G1; native uses Serial GC; every mode has a 256 MiB maximum heap.
04–06 compare modes within one deployment. 07 compares its processed JAR with native execution.
08 compares ordinary JVM execution with Spring AOT plus its matching JVM cache.
09 compares all five modes using ordinary and Spring AOT deployments built from its same source, with caches tied to each matching JAR.
Native compilation uses the recorded GraalVM JDK, whose patch version differs from the HotSpot runtime.
Source, deployment hashes, exact commands, and build/runtime versions are recorded in artifacts/environment.json.
Variants run sequentially in a seeded shuffled order. Default CDS stays enabled in the baseline.</p>
<p>Readiness is polled every {POLL_INTERVAL * 1000:g} ms; uncertainty includes that interval and probe time.
First product and quote include HTTP and JSON initialization after readiness. Container startup, preparation and diagnostics are excluded.
RSS at readiness/idle/load is application process RSS; peak RSS covers the whole process through termination, including verification.
Memory columns show medians across the measured processes or load repetitions, in MiB.
They include heap and runtime overhead rather than the heap limit or total container memory.
The OS page cache is ordinary; p95 is descriptive at the reported sample count.</p>
<p>Load uses one keep-alive connection at a fixed offered rate in a separate Compose container with its own two-CPU allowance.
Every response is verified; errors, timeouts or an unsustained offered rate fail the comparison.
This measures latency at that rate, not maximum server throughput. Startup and load repetitions are separate.</p>
<p>Packaging time includes tests and possibly uncached dependency downloads. Training excludes packaging and Docker preparation.
Artifact sizes cover JAR/libraries or the native executable, excluding the Java runtime, system shared libraries, base image and generated-source evidence; caches are additional deployment files.</p>
<p>Raw evidence: {links}</p></body></html>''')
    print(f"\nReport: {report_link(directory / 'report.html')}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=30)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--iterations", type=int, default=100_000)
    parser.add_argument("--suite", choices=("startup", "load", "all"), default="startup")
    parser.add_argument("--load-runs", type=int, default=5)
    parser.add_argument("--load-warmup", type=float, default=30)
    parser.add_argument("--load-seconds", type=float, default=60)
    parser.add_argument("--rate", type=float, default=100)
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--idle", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path, default=Path("/results"))
    args = parser.parse_args()
    if args.load_seconds * args.rate < 1:
        parser.error("load-seconds times rate must allow at least one measured request")
    if EXAMPLE_ID not in SPRING_EXAMPLES:
        parser.error("Use the selected Spring example's HTTP benchmark image")
    if not 1 <= args.runs <= 1000 or not 0 <= args.warmups <= 100 or not 1 <= args.load_runs <= 100:
        parser.error("runs must be 1..1000, warmups 0..100, and load-runs 1..100")
    if not 1 <= args.iterations <= 10_000_000:
        parser.error("iterations must be 1..10000000")
    for key, minimum, maximum in (("load_warmup", 0, 600), ("load_seconds", 0.1, 600), ("rate", 1, 10_000),
                                  ("timeout", 1, 600), ("idle", 0, 10)):
        value = getattr(args, key)
        if not math.isfinite(value) or not minimum <= value <= maximum:
            parser.error(f"{key} must be finite and within {minimum}..{maximum}")
    report_directory = args.output / EXAMPLE_ID / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    directory = report_directory / "artifacts"
    directory.mkdir(parents=True)
    variants = commands()
    metadata = environment(args, variants)
    startup_records, load_records = {key: [] for key in variants}, {key: [] for key in variants}
    phase, variant, run = "verification", None, 0
    try:
        checksum(args.iterations)
        prepare(args, directory, metadata)
        phase = "warmup"
        if args.suite in ("startup", "all"):
            for run in range(args.warmups):
                for variant, command in variants.items():
                    startup(command, variant, f"{variant}-warmup-{run + 1}", args, directory)
        order = random.Random(args.seed)
        with (directory / "runs.jsonl").open("w") as raw:
            for phase, repetitions, collection, runner in (
                ("startup", args.runs if args.suite in ("startup", "all") else 0, startup_records, startup),
                ("load", args.load_runs if args.suite in ("load", "all") else 0, load_records, load),
            ):
                for run in range(1, repetitions + 1):
                    names = list(variants)
                    order.shuffle(names)
                    for variant in names:
                        time.sleep(0.1)
                        record = {"phase": phase, "variant": variant, "run": run,
                                  **runner(variants[variant], variant, f"{variant}-{phase}-{run}", args, directory)}
                        collection[variant].append(record)
                        raw.write(json.dumps(record) + "\n")
                        raw.flush()
                        value = f'{record["ready_ms"]:.2f} ms ready' if phase == "startup" else f'{record["latency_ms"]["p95"]:.2f} ms p95'
                        print(f"{phase} {variant} {run}/{repetitions}: {value}", flush=True)
        summary = {"example": EXAMPLE_ID, "startup": {}, "load": {}, "environment": metadata}
        for variant, records in startup_records.items():
            if records:
                summary["startup"][variant] = summarize_startup(records)
        for variant, records in load_records.items():
            if records:
                summary["load"][variant] = {"runs": len(records), "errors": 0,
                    "requests_per_second": describe([record["successful_requests_per_second"] for record in records]),
                    "steady_rss_kib": describe([record["steady_rss_kib"] for record in records]),
                    **{f"{p}_ms": describe([record["latency_ms"][p] for record in records]) for p in ("p50", "p95", "p99")}}
        with (directory / "runs.csv").open("w", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=["phase", "variant", "run", "ready_ms", "first_product_ms",
                "first_quote_ms", "ready_rss_kib", "idle_rss_kib", "peak_rss_kib", "user_cpu_seconds", "system_cpu_seconds",
                "startup_cpu_throttled_periods", "startup_cpu_throttled_usec", "successful_requests_per_second",
                "steady_rss_kib", "requests", "errors", "p50_ms", "p95_ms", "p99_ms", "max_schedule_lag_ms"], extrasaction="ignore")
            writer.writeheader()
            for records in [*startup_records.values(), *load_records.values()]:
                for record in records:
                    writer.writerow({**record, **{f"{key}_ms": value for key, value in record.get("latency_ms", {}).items()}})
        (directory / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        (directory / "environment.json").write_text(json.dumps(metadata, indent=2) + "\n")
        write_report(report_directory, summary, metadata)
    except (Exception, KeyboardInterrupt) as error:
        (directory / "failure.json").write_text(json.dumps({"phase": phase, "variant": variant, "run": run, "error": str(error)}, indent=2) + "\n")
        (directory / "environment.json").write_text(json.dumps(metadata, indent=2) + "\n")
        (directory / "summary.json").unlink(missing_ok=True)
        print(f"Benchmark failed: {error}\nEvidence: {directory}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
