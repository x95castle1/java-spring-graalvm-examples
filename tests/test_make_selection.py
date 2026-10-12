"""Check Make dispatch without building images or contacting Docker."""

import os
from pathlib import Path
import pty
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
MAKE = shutil.which("make")


class MakeSelectionTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="aot-make-selection-")
        self.addCleanup(self.directory.cleanup)
        self.location = Path(self.directory.name)
        self.calls = self.location / "docker-calls"
        self.picks = self.location / "picker-calls"
        self.choices = self.location / "picker-choices"
        self.environment = {
            **os.environ,
            "PATH": f"{self.location}:/usr/bin:/bin",
            "CALL_LOG": str(self.calls),
            "PICK_LOG": str(self.picks),
            "CHOICES_LOG": str(self.choices),
            "PICK_CHOICE": "02-plain-jvm-aot-cache",
            "RUNNING_SERVICE": "spring-combined",
        }
        for key in ("EXAMPLE", "MAKEFLAGS", "MFLAGS", "MAKEOVERRIDES"):
            self.environment.pop(key, None)
        self.command("docker", 'printf "%s\\n" "$*" "TRAIN_ITERATIONS=$TRAIN_ITERATIONS" >> "$CALL_LOG"\n'
                     'case "$*" in *" ps "*) printf "%s\\n" "$RUNNING_SERVICE" ;; *" port "*) printf "127.0.0.1:%s\\n" "${PUBLISHED_PORT:-$PORT}" ;; esac\n')

    def command(self, name, body):
        path = self.location / name
        path.write_text("#!/bin/sh\n" + body)
        path.chmod(0o755)

    def picker(self, cancel=False):
        body = 'printf "picked\\n" >> "$PICK_LOG"\n/bin/cat > "$CHOICES_LOG"\n'
        body += "exit 130\n" if cancel else 'printf "%s\\n" "$PICK_CHOICE"\n'
        self.command("fzf", body)

    def invoke(self, *arguments, terminal=False):
        if terminal:
            master, slave = pty.openpty()
            try:
                return subprocess.run([MAKE, *arguments], cwd=ROOT, env=self.environment,
                                      stdin=slave, capture_output=True, text=True, timeout=10)
            finally:
                os.close(slave)
                os.close(master)
        return subprocess.run([MAKE, *arguments], cwd=ROOT, env=self.environment,
                              stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=10)

    def test_explicit_number_skips_picker(self):
        result = self.invoke("validate", "EXAMPLE=02")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("examples/02-plain-jvm-aot-cache/compose.yaml", self.calls.read_text())
        self.assertFalse(self.picks.exists())

    def test_full_name_and_options_reach_selected_command(self):
        result = self.invoke("bench", "EXAMPLE=02-plain-jvm-aot-cache", "RUNS=7", "ITERATIONS=3")
        self.assertEqual(0, result.returncode, result.stderr)
        calls = self.calls.read_text()
        self.assertIn("--compare --runs 7 --warmups 2 --iterations 3", calls)

    def test_selects_once_for_multiple_goals(self):
        self.picker()
        result = self.invoke("validate", "status", terminal=True)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(["picked"], self.picks.read_text().splitlines())
        self.assertEqual(["01-plain-java", "02-plain-jvm-aot-cache", "03-plain-graalvm-native",
                          "04-spring-java-baseline", "05-spring-aot-cache", "06-spring-jvm-aot-cache", "07-spring-aot-graalvm-native", "08-spring-aot-jvm-aot-cache", "09-combined-comparison"], self.choices.read_text().splitlines())
        self.assertIn("examples/02-plain-jvm-aot-cache/compose.yaml", self.calls.read_text())
        self.assertIn("java -version", self.calls.read_text())

    def test_picker_preserves_benchmark_options(self):
        self.picker()
        result = self.invoke("bench", "RUNS=7", "TRAIN_ITERATIONS=3", terminal=True)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("--compare --runs 7", self.calls.read_text())
        self.assertIn("TRAIN_ITERATIONS=3", self.calls.read_text())

    def test_native_selection_dispatches_runtime_and_comparison(self):
        self.picker()
        self.environment["PICK_CHOICE"] = "03-plain-graalvm-native"
        result = self.invoke("test-app", "bench", "ITERATIONS=3", "RUNS=7", terminal=True)
        self.assertEqual(0, result.returncode, result.stderr)
        calls = self.calls.read_text()
        self.assertIn("examples/03-plain-graalvm-native/compose.yaml", calls)
        self.assertIn("--profile cli-native run --rm --build cli-native --iterations 3", calls)
        self.assertIn("--compare --runs 7 --warmups 2 --iterations 3", calls)
        self.assertEqual(["picked"], self.picks.read_text().splitlines())

    def test_verify_offers_only_cache_examples(self):
        self.picker()
        result = self.invoke("verify", terminal=True)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(["02-plain-jvm-aot-cache", "06-spring-jvm-aot-cache", "08-spring-aot-jvm-aot-cache", "09-combined-comparison"], self.choices.read_text().splitlines())
        self.assertIn("/benchmark/cache_check.py", self.calls.read_text())

    def test_spring_full_name_runs_server_and_forwards_load_options(self):
        result = self.invoke("test-app", "bench", "EXAMPLE=05-spring-aot-cache", "PORT=8090", "SUITE=all", "LOAD_SECONDS=3", "RATE=20")
        self.assertEqual(0, result.returncode, result.stderr)
        calls = self.calls.read_text()
        self.assertIn("up --build --detach --wait spring-aot", calls)
        self.assertIn("http-benchmark", calls)
        self.assertIn("--suite all --load-runs 5 --load-warmup 30 --load-seconds 3 --rate 20", calls)
        self.assertFalse(self.picks.exists())

    def test_spring_cache_picker_dispatches_verification(self):
        self.picker()
        self.environment["PICK_CHOICE"] = "06-spring-jvm-aot-cache"
        result = self.invoke("verify", terminal=True)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("http-benchmark /benchmark/http_cache_check.py", self.calls.read_text())

    def test_build_selects_application_image(self):
        result = self.invoke("build", "EXAMPLE=05")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("compose.yaml build spring-aot", self.calls.read_text())

    def test_spring_native_and_combined_dispatch(self):
        for example, service in (("07", "spring-native"), ("08", "spring-combined")):
            result = self.invoke("test-app", "EXAMPLE=" + example)
            self.assertEqual(0, result.returncode, result.stderr)
            calls = self.calls.read_text()
            self.assertIn("up --build --detach --wait " + service, calls)
            self.assertIn("--host " + service, calls)

    def test_cancel_runs_nothing(self):
        self.picker(cancel=True)
        result = self.invoke("clean", terminal=True)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("No example selected", result.stderr)
        self.assertFalse(self.calls.exists())

    def test_comparison_suite_test_app_redirects_to_bench_without_docker(self):
        result = self.invoke("test-app", "EXAMPLE=09")
        self.assertNotEqual(0, result.returncode)
        self.assertIn("make bench EXAMPLE=09", result.stderr)
        self.assertFalse(self.calls.exists())

    def test_test_app_picker_excludes_comparison_suite(self):
        self.picker()
        self.environment["PICK_CHOICE"] = "08-spring-aot-jvm-aot-cache"
        result = self.invoke("test-app", terminal=True)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("08-spring-aot-jvm-aot-cache", self.choices.read_text())
        self.assertNotIn("09-combined-comparison", self.choices.read_text())

    def test_suite_build_and_bench_select_comparison_image(self):
        self.picker()
        self.environment["PICK_CHOICE"] = "09-combined-comparison"
        result = self.invoke("build", "bench", "RUNS=2", terminal=True)
        self.assertEqual(0, result.returncode, result.stderr)
        calls = self.calls.read_text()
        self.assertIn("examples/09-combined-comparison/compose.yaml build http-benchmark", calls)
        self.assertIn("http-benchmark --runs 2", calls)

    def test_test_app_selects_once_and_preserves_options(self):
        self.picker()
        self.environment["PICK_CHOICE"] = "08-spring-aot-jvm-aot-cache"
        result = self.invoke("test-app", "PORT=8088", "ITERATIONS=3", terminal=True)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(["picked"], self.picks.read_text().splitlines())
        self.assertEqual(["01-plain-java", "02-plain-jvm-aot-cache", "03-plain-graalvm-native",
                          "04-spring-java-baseline", "05-spring-aot-cache", "06-spring-jvm-aot-cache",
                          "07-spring-aot-graalvm-native", "08-spring-aot-jvm-aot-cache"],
                         self.choices.read_text().splitlines())
        calls = self.calls.read_text()
        self.assertIn("up --build --detach --wait spring-combined", calls)
        self.assertIn("/benchmark/http_test_app.py --example 08-spring-aot-jvm-aot-cache --host spring-combined", calls)
        self.assertIn("--display-url http://localhost:8088 --iterations 3", calls)
        self.assertIn("Stop: make clean EXAMPLE=08", result.stdout)

    def test_test_app_starts_stopped_http_app_before_requests(self):
        self.environment["RUNNING_SERVICE"] = ""
        result = self.invoke("test-app", "EXAMPLE=08", "PORT=8088")
        self.assertEqual(0, result.returncode, result.stderr)
        calls = self.calls.read_text()
        self.assertLess(calls.index("up --build --detach --wait spring-combined"),
                        calls.index("/benchmark/http_test_app.py"))
        self.assertNotIn("ps --status running", calls)

    def test_test_app_uses_services_published_port(self):
        self.environment["PUBLISHED_PORT"] = "9090"
        result = self.invoke("test-app", "EXAMPLE=08")
        self.assertEqual(0, result.returncode, result.stderr)
        calls = self.calls.read_text()
        self.assertIn("port spring-combined 8080", calls)
        self.assertIn("--display-url http://localhost:9090", calls)
        self.assertIn("Ready: http://localhost:9090/ready", result.stdout)

    def test_retired_targets_are_unavailable(self):
        for target in ("run", "try", "test"):
            result = self.invoke(target, "EXAMPLE=08")
            self.assertNotEqual(0, result.returncode)
            self.assertIn("No rule to make target", result.stderr)
            self.assertFalse(self.calls.exists())

    def test_noninteractive_picker_fails_without_defaulting(self):
        self.picker()
        result = self.invoke("test-app")
        self.assertNotEqual(0, result.returncode)
        self.assertIn("needs a terminal", result.stderr)
        self.assertFalse(self.calls.exists())

    def test_help_and_missing_fzf(self):
        result = self.invoke("help")
        self.assertEqual(0, result.returncode)
        self.assertFalse(self.calls.exists())
        self.assertIn("make test-app", result.stdout)
        self.assertIn("network\n\nExample commands", result.stdout)
        self.assertNotIn("make run ", result.stdout)
        self.assertNotIn("make try ", result.stdout)
        self.assertNotIn("make test ", result.stdout)
        # Do not depend on whether fzf happens to be installed in /usr/bin.
        (self.location / "sh").symlink_to("/bin/sh")
        self.environment["PATH"] = str(self.location)
        result = self.invoke("test-app", terminal=True)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("fzf is required", result.stderr)
        self.assertFalse(self.calls.exists())


if __name__ == "__main__":
    unittest.main()
