"""Exercise real HTTP routes, then stop Java cleanly to assemble its AOT cache."""

import http.client
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

requests, iterations = map(int, sys.argv[1:])
if not 1 <= requests <= 100_000 or not 1 <= iterations <= 10_000_000:
    raise ValueError("Training requests must be 1..100000; iterations must be 1..10000000")
checksum = 0x1234ABCD
for _ in range(iterations):
    checksum ^= (checksum << 13) & ((1 << 64) - 1)
    checksum ^= checksum >> 7
    checksum ^= (checksum << 17) & ((1 << 64) - 1)
if checksum >= 1 << 63:
    checksum -= 1 << 64

jar = os.environ["TRAIN_JAR"]
use_aot = os.environ["TRAIN_SPRING_AOT"] == "true"
cache_name = os.environ["CACHE_NAME"]

command = ["java", "-Xmx256m", "-XX:+UseG1GC", f"-Dspring.aot.enabled={str(use_aot).lower()}",
           f"-XX:AOTCacheOutput=/app/{cache_name}.aot", f"-Xlog:aot=info:file=/app/{cache_name}-training.log",
           "-jar", jar]
with Path(f"/app/{cache_name}-application.log").open("w") as log:
    process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
    connection = http.client.HTTPConnection("127.0.0.1", 8080, timeout=2)
    try:
        deadline = time.monotonic() + 60
        while True:
            if process.poll() is not None:
                raise RuntimeError("Training server exited: " + Path(log.name).read_text())
            if time.monotonic() > deadline:
                raise RuntimeError("Training server did not become ready")
            try:
                connection.request("GET", "/ready")
                response = connection.getresponse()
                ready = json.loads(response.read())
                if response.status == 200 and ready["ready"] and ready["springAot"] == use_aot:
                    break
            except (OSError, http.client.HTTPException):
                connection.close()
            time.sleep(0.02)
        for index in range(requests):
            route = index % 3
            if route == 0:
                method, path, body = "GET", "/products/1", None
                expected = {"id": 1, "name": "Keyboard", "priceCents": 9900}
            elif route == 1:
                method, path, body = "POST", "/quotes", '{"quantities":{"1":2,"2":1}}'
                expected = {"subtotalCents": 22300, "discountCents": 2230, "totalCents": 20070}
            else:
                method, path, body = "GET", f"/compute?iterations={iterations}", None
                expected = {"iterations": iterations, "checksum": checksum}
            connection.request(method, path, body, {"Content-Type": "application/json"})
            response = connection.getresponse()
            if response.status != 200 or json.loads(response.read()) != expected:
                raise RuntimeError("Incorrect workload-training response: " + path)
        print(f"Verified {requests} HTTP training requests; compute iterations={iterations}")
    finally:
        connection.close()
        if process.poll() is None:
            process.send_signal(signal.SIGTERM)
        try:
            process.wait(timeout=60)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            raise RuntimeError("Training shutdown/cache assembly timed out") from None
    if process.returncode not in (0, 143, -signal.SIGTERM):
        raise RuntimeError("Training failed: " + Path(log.name).read_text())
