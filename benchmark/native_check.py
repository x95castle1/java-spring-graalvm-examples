"""Verify the actual native executable and its embedded resources before timing."""

import hashlib
import json
from pathlib import Path
import subprocess

from run import NATIVE_COMMAND, expected_checksum, verify_output


def verify_elf(path):
    with path.open("rb") as source:
        if source.read(4) != b"\x7fELF":
            raise ValueError("Native artifact must be a Linux ELF executable")


def verify_native(iterations=100_000, timeout=30):
    executable = Path("/app/catalog-cli")
    verify_elf(executable)
    completed = subprocess.run([*NATIVE_COMMAND, "--iterations", str(iterations)],
                               capture_output=True, text=True, check=True, timeout=timeout)
    output = json.loads(completed.stdout)
    verify_output(output, iterations, expected_checksum(iterations))
    info = json.loads(Path("/app/native-build.json").read_text())
    if info["elapsed_seconds"] <= 0 or info["peak_rss_kib"] <= 0:
        raise ValueError("Missing native compilation measurements")
    return {
        **info,
        "executable_bytes": executable.stat().st_size,
        "executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
        "verification_output": output,
        "command": ["native-image", "--no-fallback", "--gc=serial", "-march=compatibility",
                    "--exact-reachability-metadata", "--parallelism=2", "-J-Xmx2g",
                    "-jar", "/app/plain-java.jar", "/app/catalog-cli"],
        "cost_scope": "Native compiler process and children; excludes Gradle, downloads, and Docker image preparation",
    }


if __name__ == "__main__":
    print(json.dumps(verify_native(), indent=2))
