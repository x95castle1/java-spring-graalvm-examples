"""HTTP workload contract and bounded lifecycle for fresh Spring JVM and native processes."""

from functools import lru_cache
import http.client
import json
import os
from pathlib import Path
import signal
import subprocess
import time

from run import cpu_throttling, expected_checksum

DUAL_DEPLOYMENT_EXAMPLES = ("08-spring-aot-jvm-aot-cache", "09-combined-comparison")
SPRING_EXAMPLES = ("04-spring-java-baseline", "05-spring-aot-cache", "06-spring-jvm-aot-cache",
                   "07-spring-aot-graalvm-native", *DUAL_DEPLOYMENT_EXAMPLES)
EXAMPLE_ID = os.environ.get("EXAMPLE_ID", SPRING_EXAMPLES[0])
JAVA = ["java", "-Xmx256m", "-XX:+UseG1GC"]
JAR = "/app/catalog-service.jar"
POLL_INTERVAL = 0.02
QUOTE_BODY = '{"quantities":{"1":2,"2":1}}'
PRODUCT = {"id": 1, "name": "Keyboard", "priceCents": 9900}
QUOTE = {"subtotalCents": 22300, "discountCents": 2230, "totalCents": 20070}
checksum = lru_cache(maxsize=16)(expected_checksum)


def commands(example=EXAMPLE_ID):
    baseline = [*JAVA, "-Dspring.aot.enabled=false", "-jar", JAR]
    if example == "04-spring-java-baseline":
        return {"baseline": baseline}
    if example == "05-spring-aot-cache":
        return {"baseline": baseline, "spring-aot": [*JAVA, "-Dspring.aot.enabled=true", "-jar", JAR]}
    if example == "06-spring-jvm-aot-cache":
        return {"baseline": baseline, **{
            f"{recipe}-cache": [*JAVA, "-Dspring.aot.enabled=false", "-XX:AOTMode=on",
                               f"-XX:AOTCache=/app/{recipe}.aot", "-jar", JAR]
            for recipe in ("short", "workload")
        }}
    if example == "07-spring-aot-graalvm-native":
        return {"baseline": baseline, "native": ["/app/catalog-service", "-Xmx256m"]}
    if example in DUAL_DEPLOYMENT_EXAMPLES:
        plain = "/app/plain/catalog-service.jar"
        aot = "/app/aot/catalog-service.jar"
        matrix = {
            "baseline": [*JAVA, "-Dspring.aot.enabled=false", "-jar", plain],
            "spring-aot": [*JAVA, "-Dspring.aot.enabled=true", "-jar", aot],
            "jvm-cache": [*JAVA, "-Dspring.aot.enabled=false", "-XX:AOTMode=on",
                          "-XX:AOTCache=/app/jvm-cache.aot", "-jar", plain],
            "spring-aot-cache": [*JAVA, "-Dspring.aot.enabled=true", "-XX:AOTMode=on",
                                 "-XX:AOTCache=/app/spring-aot-cache.aot", "-jar", aot],
            "native": ["/app/catalog-service", "-Xmx256m"],
        }
        if example == "08-spring-aot-jvm-aot-cache":
            return {name: matrix[name] for name in ("baseline", "spring-aot-cache")}
        return matrix
    raise ValueError(f"Unknown Spring example: {example}")


def mode_aot(variant):
    return variant in ("spring-aot", "spring-aot-cache", "native")


def has_generated_initializer(example=EXAMPLE_ID, aot=False):
    return aot or example in ("05-spring-aot-cache", "07-spring-aot-graalvm-native")


def request(connection, path, body=None, status=200):
    connection.request("GET" if body is None else "POST", path, body,
                       {"Content-Type": "application/json"})
    response = connection.getresponse()
    raw = response.read()
    if response.status != status:
        raise ValueError(f"{path}: expected HTTP {status}, got {response.status}: {raw.decode(errors='replace')}")
    return json.loads(raw) if raw else None


def verify_response(actual, expected, route):
    if actual != expected:
        raise ValueError(f"Incorrect {route} response: expected {expected!r}, got {actual!r}")


def verify_ready(actual, aot=False, label="Catalog", example=EXAMPLE_ID):
    for field, expected in {"ready": True, "productCount": 8, "springAot": aot,
                            "catalogLabel": label, "generatedInitializer": has_generated_initializer(example, aot)}.items():
        if actual.get(field) != expected:
            raise ValueError(f"Incorrect readiness {field}: {actual.get(field)!r}; expected {expected!r}")
    if str(actual.get("javaVersion", "")).split(".")[0] != "25" or actual.get("springBootVersion") != "4.1.1":
        raise ValueError("Expected Java 25 and Spring Boot 4.1.1")


def workload_request(connection, index, iterations):
    route = index % 3
    if route == 0:
        actual, expected, path = request(connection, "/products/1"), PRODUCT, "/products/1"
    elif route == 1:
        actual, expected, path = request(connection, "/quotes", QUOTE_BODY), QUOTE, "/quotes"
    else:
        path = f"/compute?iterations={iterations}"
        actual, expected = request(connection, path), {"iterations": iterations, "checksum": checksum(iterations)}
    verify_response(actual, expected, path)


def verify_contract(connection, iterations=100_000):
    if EXAMPLE_ID in ("07-spring-aot-graalvm-native", *DUAL_DEPLOYMENT_EXAMPLES):
        verify_response(request(connection, "/native-metadata"),
                        {"policy": "ten-percent", "catalogResource": True}, "/native-metadata")
    for index in range(3):
        workload_request(connection, index, iterations)
    verify_response(request(connection, "/compute?iterations=1"),
                    {"iterations": 1, "checksum": checksum(1)}, "/compute")
    for route in ("/products/99", "/missing"):
        request(connection, route, status=404)
    for value in ("0", "10000001", "nope"):
        request(connection, f"/compute?iterations={value}", status=400)
    for body in ('{}', '{"quantities":{}}', '{"quantities":{"1":0}}',
                 '{"quantities":{"1":101}}', '{"quantities":{"99":1}}',
                 '{"quantities":{"1":null}}', 'not-json'):
        request(connection, "/quotes", body, status=400)


def process_rss(pid):
    path = Path(f"/proc/{pid}/status")
    if path.is_file():
        for line in path.read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    raise RuntimeError("Application process exited before RSS collection")


def java_pid(process):
    children = Path(f"/proc/{process.pid}/task/{process.pid}/children")
    pids = children.read_text().split() if children.exists() else []
    if len(pids) != 1:
        raise RuntimeError("GNU time must have one application child process")
    return int(pids[0])


class Server:
    def __init__(self, command, directory, label, *, aot=False, catalog_label="Catalog", timeout=60):
        self.command = command
        self.directory = Path(directory)
        self.label = label
        self.aot = aot
        self.catalog_label = catalog_label
        self.timeout = timeout
        self.process = None
        self.metrics = None
        self.connection = http.client.HTTPConnection("127.0.0.1", 8080, timeout=1)
        self.log_path = self.directory / f"{label}-application.log"
        self.time_path = self.directory / f"{label}-process.json"

    def __enter__(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        self.log = self.log_path.open("w")
        self.before = cpu_throttling()
        started = time.perf_counter_ns()
        try:
            self.process = subprocess.Popen([
                "/usr/bin/time", "--quiet", "--output", str(self.time_path),
                "--format", '{"user_cpu_seconds":%U,"system_cpu_seconds":%S,"peak_rss_kib":%M}',
                *self.command,
            ], cwd="/app", stdout=self.log, stderr=subprocess.STDOUT, start_new_session=True)
            deadline = time.monotonic() + self.timeout
            while True:
                if self.process.poll() is not None:
                    raise RuntimeError(f"Server exited before readiness: {self.log_path.read_text()[-6000:]}")
                if time.monotonic() > deadline:
                    raise RuntimeError(f"Server exceeded {self.timeout}s readiness timeout; see {self.log_path}")
                try:
                    self.connection.request("GET", "/ready")
                    response = self.connection.getresponse()
                    raw = response.read()
                    if response.status == 200:
                        elapsed = (time.perf_counter_ns() - started) / 1_000_000
                        self.ready_output = json.loads(raw)
                        verify_ready(self.ready_output, self.aot, self.catalog_label)
                        break
                    if response.status != 503:
                        raise ValueError(f"Unexpected readiness HTTP status: {response.status}")
                except (OSError, http.client.HTTPException):
                    self.connection.close()
                time.sleep(POLL_INTERVAL)
            self.pid = java_pid(self.process)
            self.startup = {"ready_ms": elapsed, "ready_rss_kib": process_rss(self.pid), "ready_output": self.ready_output}
            verify_response(request(self.connection, "/products/1"), PRODUCT, "/products/1")
            self.startup["first_product_ms"] = (time.perf_counter_ns() - started) / 1_000_000
            verify_response(request(self.connection, "/quotes", QUOTE_BODY), QUOTE, "/quotes")
            self.startup["first_quote_ms"] = (time.perf_counter_ns() - started) / 1_000_000
            after = cpu_throttling()
            self.startup.update({
                "startup_cpu_throttled_periods": int(after.get("nr_throttled", 0)) - int(self.before.get("nr_throttled", 0)),
                "startup_cpu_throttled_usec": int(after.get("throttled_usec", 0)) - int(self.before.get("throttled_usec", 0)),
            })
            return self
        except BaseException:
            try:
                self.stop()
            except Exception:
                pass
            raise

    def stop(self):
        self.connection.close()
        if self.process is None or self.metrics is not None:
            self.log.close()
            return self.metrics
        if self.process.poll() is None:
            try:
                os.kill(java_pid(self.process), signal.SIGTERM)
            except ProcessLookupError:
                pass
        try:
            self.process.wait(timeout=self.timeout)
        except subprocess.TimeoutExpired:
            os.killpg(self.process.pid, signal.SIGKILL)
            self.process.wait()
            raise RuntimeError("Server shutdown timed out") from None
        finally:
            self.log.close()
        self.metrics = json.loads(self.time_path.read_text())
        if self.metrics["peak_rss_kib"] <= 0:
            raise RuntimeError("GNU time did not record application peak RSS")
        if self.process.returncode not in (0, 143):
            raise RuntimeError(f"Server crashed (exit {self.process.returncode}): {self.log_path.read_text()[-6000:]}")
        return self.metrics

    def __exit__(self, kind, value, traceback):
        self.stop()
