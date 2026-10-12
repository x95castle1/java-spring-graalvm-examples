"""Verify application classes use each matching cache and invalid deployments fail."""

from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

from http_common import DUAL_DEPLOYMENT_EXAMPLES, EXAMPLE_ID, Server, commands, mode_aot, verify_contract


def cache_commands(example=EXAMPLE_ID):
    return {name: command for name, command in commands(example).items()
            if any(argument.startswith("-XX:AOTCache=") for argument in command)}


def evidence_name(name):
    return name.removesuffix("-cache") if EXAMPLE_ID == "06-spring-jvm-aot-cache" else name


def check(name, command, directory, iterations=100_000):
    log_path = Path(directory) / f"{evidence_name(name)}-verification.log"
    logged = list(command)
    logged.insert(1, f"-Xlog:aot=info,class+load=info:file={log_path}")
    with Server(logged, directory, f"{name}-verification", aot=mode_aot(name)) as server:
        verify_contract(server.connection, iterations)
    log = log_path.read_text()
    names = ["spring.CatalogApplication", "core.Catalog", "core.Workload"]
    if mode_aot(name):
        names.append("spring.CatalogApplication__ApplicationContextInitializer")
    for application_class in names:
        if not any(f"dev.aotexamples.{application_class} source: shared objects file" in line for line in log.splitlines()):
            raise RuntimeError(f"{name} cache did not supply application class {application_class}")
    return log_path


def reject_invalid(name, original, directory):
    command = list(original)
    command.insert(1, "-Dspring.context.exit=onRefresh")
    jar = Path(command[command.index("-jar") + 1])
    prefix = "" if EXAMPLE_ID == "06-spring-jvm-aot-cache" else name + "-"

    def require_failure(arguments, label):
        completed = subprocess.run(arguments, cwd="/app", capture_output=True, text=True, timeout=60)
        diagnostic = completed.stdout + completed.stderr
        (Path(directory) / f"{prefix}{label}-rejection.log").write_text(diagnostic)
        if completed.returncode == 0 or "Unable to use" not in diagnostic:
            raise RuntimeError(f"{label} cache deployment was not rejected: {diagnostic}")

    missing = ["-XX:AOTCache=/app/missing-cache.aot" if argument.startswith("-XX:AOTCache=") else argument
               for argument in command]
    require_failure(missing, "missing-cache")
    with tempfile.TemporaryDirectory(prefix="spring-cache-backup-") as location:
        backup = Path(location) / "catalog-service.jar"
        shutil.copy2(jar, backup)
        try:
            with zipfile.ZipFile(jar, "a") as archive:
                archive.writestr("changed-fixture.txt", "regenerate the cache after deployment changes")
            require_failure(command, "changed-jar")
        finally:
            shutil.copy2(backup, jar)
    if EXAMPLE_ID in DUAL_DEPLOYMENT_EXAMPLES:
        swapped = list(command)
        swapped[swapped.index("-jar") + 1] = "/app/aot/catalog-service.jar" if name == "jvm-cache" else "/app/plain/catalog-service.jar"
        require_failure(swapped, "wrong-deployment")


def verify(directory, iterations=100_000):
    variants = cache_commands()
    if not variants:
        raise ValueError("Select a Spring JVM cache example")
    for name, command in variants.items():
        check(name, command, directory, iterations)
    negative = variants if EXAMPLE_ID in DUAL_DEPLOYMENT_EXAMPLES else {"workload-cache": variants["workload-cache"]}
    for name, command in negative.items():
        reject_invalid(name, command, directory)
        check(name, command, directory, iterations)


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="spring-cache-check-") as directory:
        verify(directory)
    print("Verified Spring caches supply application classes; invalid deployments are rejected.")
