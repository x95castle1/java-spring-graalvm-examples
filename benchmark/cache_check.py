"""Verify actual application cache use and fail-fast rejection before timing."""

import json
from pathlib import Path
import subprocess
import tempfile
import zipfile


def verify_cache(recipe, iterations=100_000):
    from run import cache_command, expected_checksum, verify_output

    with tempfile.TemporaryDirectory(prefix="aot-verification-") as location:
        log_path = Path(location) / "verification.log"
        command = cache_command(recipe)
        command.insert(1, f"-Xlog:aot=info,class+load=info:file={log_path}")
        completed = subprocess.run(
            [*command, "--iterations", str(iterations)], capture_output=True, text=True,
            check=True, timeout=30,
        )
        verify_output(json.loads(completed.stdout), iterations, expected_checksum(iterations))
        log = log_path.read_text()
        for name in ("cli.CatalogCli", "core.Catalog", "core.Workload"):
            if not any(f"dev.aotexamples.{name} source: shared objects file" in line
                       for line in log.splitlines()):
                raise RuntimeError(f"{recipe} cache did not supply application class {name}")
        return log


def verify_invalid_caches():
    from run import cache_command

    with tempfile.TemporaryDirectory(prefix="aot-invalid-") as location:
        command = cache_command("workload")
        missing = [argument.replace("/app/workload.aot", f"{location}/missing.aot") for argument in command]
        completed = subprocess.run(missing, capture_output=True, text=True, timeout=30)
        diagnostic = completed.stdout + completed.stderr
        if completed.returncode == 0 or "Unable to use" not in diagnostic:
            raise RuntimeError(f"Missing cache was not rejected: {diagnostic}")

        changed_jar = Path(location) / "changed.jar"
        changed_jar.write_bytes(Path("/app/plain-java.jar").read_bytes())
        with zipfile.ZipFile(changed_jar, "a") as archive:
            archive.writestr("changed-fixture.txt", "cache must be regenerated")
        changed = [argument.replace("/app/plain-java.jar", str(changed_jar)) for argument in command]
        completed = subprocess.run(changed, capture_output=True, text=True, timeout=30)
        diagnostic = completed.stdout + completed.stderr
        if completed.returncode == 0 or "Unable to use" not in diagnostic:
            raise RuntimeError(f"Changed JAR was not rejected: {diagnostic}")


if __name__ == "__main__":
    for recipe in ("short", "workload"):
        verify_cache(recipe)
        print(f"Verified {recipe} cache: CLI, catalog, and workload loaded from shared objects file.")
    verify_invalid_caches()
    print("Missing cache and changed JAR correctly rejected in strict AOT mode.")
