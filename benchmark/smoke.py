"""Check the packaged CLI in the same image used for benchmarks."""

import json
import subprocess
from run import EXAMPLE_ID, JAVA_COMMAND, NATIVE_COMMAND, cache_command, expected_checksum, verify_output

commands = [JAVA_COMMAND]
if EXAMPLE_ID == "02-plain-jvm-aot-cache":
    commands.extend(cache_command(recipe) for recipe in ("short", "workload"))
elif EXAMPLE_ID == "03-plain-graalvm-native":
    from native_check import verify_native
    verify_native()
    commands.append(NATIVE_COMMAND)

for command in commands:
    for iterations in (1, 100_000):
        completed = subprocess.run(
            [*command, "--iterations", str(iterations)], capture_output=True, text=True, check=True, timeout=30,
        )
        verify_output(json.loads(completed.stdout), iterations, expected_checksum(iterations))

    for arguments in (["--iterations", "0"], ["--iterations", "10000001"], ["--unknown"], ["--iterations", "nope"]):
        completed = subprocess.run([*command, *arguments], capture_output=True, text=True, timeout=30)
        if completed.returncode != 2 or not completed.stderr.strip() or completed.stdout.strip():
            raise RuntimeError(f"Invalid arguments were not rejected: {arguments}")

    completed = subprocess.run([*command, "--help"], capture_output=True, text=True, check=True, timeout=30)
    if "Usage:" not in completed.stdout:
        raise RuntimeError("Missing CLI help")

print("Packaged CLI smoke checks passed: resources, quote, checksum, bounds, invalid arguments, and help.")
