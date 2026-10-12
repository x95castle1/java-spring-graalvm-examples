import unittest
import sys
import tempfile

from http_common import EXAMPLE_ID, Server, commands, has_generated_initializer, verify_ready, verify_response
from http_run import startup_rows, summarize_startup


class HttpBenchmarkTest(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "linux", "Server measurement uses Linux GNU time and /proc")
    def test_fast_incorrect_http_server_is_rejected_and_stopped(self):
        ready = {"ready": True, "productCount": 8, "catalogLabel": "Catalog", "springAot": False,
                 "generatedInitializer": has_generated_initializer(), "javaVersion": "25.0.4.1", "springBootVersion": "4.1.1"}
        code = f'''
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        value = {ready!r} if self.path == '/ready' else {{'id': 0}}
        body = json.dumps(value).encode()
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *args): pass
HTTPServer(('127.0.0.1', 8080), Handler).serve_forever()
'''
        with tempfile.TemporaryDirectory() as directory:
            server = Server([sys.executable, "-c", code], directory, "incorrect", timeout=5)
            with self.assertRaisesRegex(ValueError, "Incorrect /products/1"):
                with server:
                    self.fail("Incorrect server passed startup verification")
            self.assertIsNotNone(server.process.poll())

    @unittest.skipUnless(sys.platform == "linux", "Server measurement uses Linux GNU time and /proc")
    def test_readiness_timeout_stops_child(self):
        with tempfile.TemporaryDirectory() as directory:
            server = Server([sys.executable, "-c", "import time; time.sleep(300)"], directory, "timeout", timeout=0.2)
            with self.assertRaisesRegex(RuntimeError, "readiness timeout"):
                with server:
                    self.fail("An unready process passed startup verification")
            self.assertIsNotNone(server.process.poll())

    def test_rejects_incorrect_quote_and_aot_mode(self):
        with self.assertRaisesRegex(ValueError, "Incorrect /quotes"):
            verify_response({"totalCents": 0}, {"totalCents": 20070}, "/quotes")
        ready = {"ready": True, "productCount": 8, "catalogLabel": "Catalog", "springAot": False,
                 "generatedInitializer": True, "javaVersion": "25.0.4.1", "springBootVersion": "4.1.1"}
        with self.assertRaisesRegex(ValueError, "springAot"):
            verify_ready(ready, aot=True, example="05-spring-aot-cache")
        verify_ready(ready, example="05-spring-aot-cache")

    def test_spring_aot_toggle_preserves_jar_and_cache_disables_spring_aot(self):
        aot = commands("05-spring-aot-cache")
        self.assertEqual(aot["baseline"][-2:], aot["spring-aot"][-2:])
        self.assertIn("-Dspring.aot.enabled=true", aot["spring-aot"])
        for name, command in commands("06-spring-jvm-aot-cache").items():
            self.assertIn("-Dspring.aot.enabled=false", command)
            if name != "baseline":
                self.assertIn("-XX:AOTMode=on", command)

    def test_startup_reductions_preserve_memory_regressions(self):
        record = {key: 100 for key in ("ready_ms", "first_product_ms", "first_quote_ms", "ready_rss_kib", "idle_rss_kib", "peak_rss_kib")}
        baseline = summarize_startup([record])
        changed = summarize_startup([{**record, "ready_ms": 50, "ready_rss_kib": 200}])
        row = startup_rows({"baseline": baseline, "spring-aot": changed})[2]
        self.assertEqual("+50.0%", row[7])
        self.assertEqual("-100.0%", row[8])

    def test_combined_modes_use_matching_jars_and_keep_native_separate(self):
        matrix = commands("09-combined-comparison")
        self.assertEqual(set(matrix), {"baseline", "spring-aot", "jvm-cache", "spring-aot-cache", "native"})
        self.assertEqual(matrix["baseline"][-1], matrix["jvm-cache"][-1])
        self.assertEqual(matrix["spring-aot"][-1], matrix["spring-aot-cache"][-1])
        self.assertNotEqual(matrix["baseline"][-1], matrix["spring-aot"][-1])
        self.assertIn("-Dspring.aot.enabled=true", matrix["spring-aot-cache"])
        self.assertIn("-XX:AOTMode=on", matrix["spring-aot-cache"])
        self.assertEqual(matrix["native"], ["/app/catalog-service", "-Xmx256m"])

    def test_dedicated_combined_example_only_compares_baseline_and_combined_jvm(self):
        matrix = commands("08-spring-aot-jvm-aot-cache")
        self.assertEqual(set(matrix), {"baseline", "spring-aot-cache"})
        self.assertNotEqual(matrix["baseline"][-1], matrix["spring-aot-cache"][-1])
        self.assertIn("-Dspring.aot.enabled=false", matrix["baseline"])
        self.assertIn("-Dspring.aot.enabled=true", matrix["spring-aot-cache"])
        self.assertIn("-XX:AOTMode=on", matrix["spring-aot-cache"])
        self.assertIn("-XX:AOTCache=/app/spring-aot-cache.aot", matrix["spring-aot-cache"])

    def test_plain_and_generated_readiness_are_verified_per_mode(self):
        ready = {"ready": True, "productCount": 8, "catalogLabel": "Catalog", "springAot": False,
                 "generatedInitializer": False, "javaVersion": "25.0.4.1", "springBootVersion": "4.1.1"}
        verify_ready(ready, example="09-combined-comparison")
        with self.assertRaisesRegex(ValueError, "generatedInitializer"):
            verify_ready({**ready, "springAot": True}, aot=True, example="09-combined-comparison")
        verify_ready({**ready, "springAot": True, "generatedInitializer": True}, aot=True,
                     example="09-combined-comparison")


if __name__ == "__main__":
    unittest.main()
