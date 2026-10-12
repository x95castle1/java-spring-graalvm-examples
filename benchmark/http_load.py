"""Separate-process, keep-alive HTTP client with a fixed offered request rate."""

import argparse
import http.client
import json
import math
from pathlib import Path
import time

from http_common import checksum, workload_request
from run import cpu_throttling, percentile, read_optional


def exercise(connection, duration, rate, iterations, record=False):
    count = max(1, math.floor(duration * rate))
    start = time.perf_counter()
    samples = []
    for index in range(count):
        scheduled = start + index / rate
        delay = scheduled - time.perf_counter()
        if delay > 0:
            time.sleep(delay)
        began = time.perf_counter()
        workload_request(connection, index, iterations)
        if record:
            samples.append({"request": index + 1, "route": ("product", "quote", "compute")[index % 3],
                            "latency_ms": (time.perf_counter() - began) * 1000,
                            "schedule_lag_ms": max(0, began - scheduled) * 1000})
    delay = start + duration - time.perf_counter()
    if delay > 0:
        time.sleep(delay)
    elapsed = time.perf_counter() - start
    return elapsed, samples


def run_load(warmup, duration, rate, iterations, host="127.0.0.1"):
    checksum(iterations)  # Independent verification work stays outside the request timer.
    connection = http.client.HTTPConnection(host, 8080, timeout=5)
    try:
        if warmup:
            exercise(connection, warmup, rate, iterations)
        before = cpu_throttling()
        elapsed, samples = exercise(connection, duration, rate, iterations, True)
        after = cpu_throttling()
    finally:
        connection.close()
    latencies = [sample["latency_ms"] for sample in samples]
    return {
        "requests": len(samples), "errors": 0, "duration_seconds": elapsed,
        "requested_duration_seconds": duration, "offered_requests_per_second": rate,
        "successful_requests_per_second": len(samples) / elapsed,
        "latency_ms": {"p50": percentile(latencies, 50), "p95": percentile(latencies, 95), "p99": percentile(latencies, 99)},
        "max_schedule_lag_ms": max(sample["schedule_lag_ms"] for sample in samples),
        "client_kept_up": elapsed <= duration * 1.05 and max(sample["schedule_lag_ms"] for sample in samples) < 100,
        "client_cpu_max": read_optional("/sys/fs/cgroup/cpu.max"),
        "client_memory_max_bytes": read_optional("/sys/fs/cgroup/memory.max"),
        "client_throttled_usec": int(after.get("throttled_usec", 0)) - int(before.get("throttled_usec", 0)),
        "client_usage_usec": int(after.get("usage_usec", 0)) - int(before.get("usage_usec", 0)),
        "samples": samples,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--warmup", type=float, required=True)
    parser.add_argument("--duration", type=float, required=True)
    parser.add_argument("--rate", type=float, required=True)
    parser.add_argument("--iterations", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    try:
        output = run_load(args.warmup, args.duration, args.rate, args.iterations, args.host)
    except Exception as error:
        args.output.write_text(json.dumps({"error": str(error)}) + "\n")
        raise
    args.output.write_text(json.dumps(output, indent=2) + "\n")
