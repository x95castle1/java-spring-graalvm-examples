"""Require a native ELF artifact and verify its HTTP resource/reflection behavior."""

import hashlib
import json
from pathlib import Path
import tempfile

from http_common import Server, commands, request, verify_contract
from native_check import verify_elf
from run import read_optional


def check_missing_metadata(directory, timeout):
    jvm_command = list(commands()["baseline"])
    jvm_command.insert(1, "-Dcatalog.policyMethod=unregisteredName")
    with Server(jvm_command, directory, "jvm-unregistered-control", timeout=timeout) as server:
        verify_contract(server.connection)
    command = [*commands()["native"], "-Dcatalog.policyMethod=unregisteredName"]
    with Server(command, directory, "native-missing-metadata", aot=True, timeout=timeout) as server:
        request(server.connection, "/native-metadata", status=500)
    diagnostic = server.log_path.read_text()
    if "MissingReflectionRegistrationError" not in diagnostic or "unregisteredName" not in diagnostic:
        raise ValueError("Unregistered policy method did not produce the expected native metadata diagnostic: " + diagnostic[-6000:])
    return {"jvm_control_http_status": 200, "http_status": 500, "unregistered_method": "DiscountPolicy.unregisteredName",
            "diagnostic": "MissingReflectionRegistrationError", "log": server.log_path.name}


def verify_native(iterations=100_000, timeout=60, directory=None):
    executable = Path("/app/catalog-service")
    verify_elf(executable)
    costs = json.loads(Path("/app/native-build.json").read_text())
    if costs["elapsed_seconds"] <= 0 or costs["peak_rss_kib"] <= 0:
        raise ValueError("Missing native compilation measurements")
    if directory is None:
        with tempfile.TemporaryDirectory(prefix="spring-native-check-") as temporary:
            return verify_native(iterations, timeout, temporary)
    missing_metadata = check_missing_metadata(directory, timeout)
    with Server(commands()["native"], directory, "native-verification", aot=True, timeout=timeout) as server:
        verify_contract(server.connection, iterations)
    return {**costs, "missing_metadata_check": missing_metadata, "executable_bytes": executable.stat().st_size,
            "executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
            "native_version": read_optional("/app/native-version.txt"),
            "native_image": read_optional("/app/native-image.txt"),
            "runtime_image": read_optional("/app/runtime-image.txt"),
            "build_command": "./gradlew --no-daemon --console=plain nativeCompile",
            "compiler_options": ["--no-fallback", "--gc=serial", "-march=compatibility",
                                 "--parallelism=2", "-J-Xmx4g"],
            "native_plugin_version": "1.1.8", "metadata_repository_enabled": True, "metadata_repository_version": "1.0.9",

            "cost_scope": "Gradle nativeCompile and children, including compiler and any uncached metadata resolution; excludes initial Java packaging/tests and Docker preparation"}


if __name__ == "__main__":
    print(json.dumps(verify_native(), indent=2))
