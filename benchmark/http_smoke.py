"""Check the packaged HTTP service in each mode, including Spring AOT profile semantics."""

import tempfile

from http_common import DUAL_DEPLOYMENT_EXAMPLES, EXAMPLE_ID, Server, commands, mode_aot, verify_contract


def smoke():
    with tempfile.TemporaryDirectory(prefix="spring-smoke-") as directory:
        for variant, command in commands().items():
            with Server(command, directory, variant, aot=mode_aot(variant)) as server:
                verify_contract(server.connection)
            print(f"Verified {variant}: readiness, resources, JSON, quote, checksum, bounds, and invalid requests.")
        if EXAMPLE_ID in ("05-spring-aot-cache", "07-spring-aot-graalvm-native", *DUAL_DEPLOYMENT_EXAMPLES):
            for variant, command in commands().items():
                label = "Catalog" if mode_aot(variant) else "Alternate catalog"
                with Server([*command, "--spring.profiles.active=alternate"], directory, f"{variant}-profile",
                            aot=mode_aot(variant), catalog_label=label) as server:
                    verify_contract(server.connection)
            print("Verified profile choice: JVM selects alternate at runtime; Spring AOT retains the build-time bean graph.")


if __name__ == "__main__":
    smoke()
