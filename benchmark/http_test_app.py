#!/usr/bin/env python3
"""Show and verify sample API requests against an already running Compose service."""

import argparse
import http.client
import json
import shlex
import sys

from http_common import PRODUCT, QUOTE, QUOTE_BODY, SPRING_EXAMPLES, checksum, request, verify_ready, verify_response


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--example", choices=SPRING_EXAMPLES[:-1], required=True)
    parser.add_argument("--host", required=True)
    parser.add_argument("--display-url", default="http://localhost:8080")
    parser.add_argument("--iterations", type=int, default=100_000)
    args = parser.parse_args()
    if not 1 <= args.iterations <= 10_000_000:
        parser.error("iterations must be 1..10000000")

    cases = [
        ("Check readiness", "/ready", None, None),
        ("Get a product", "/products/1", None, PRODUCT),
        ("Calculate a quote", "/quotes", QUOTE_BODY, QUOTE),
        ("Run the computation", f"/compute?iterations={args.iterations}", None,
         {"iterations": args.iterations, "checksum": checksum(args.iterations)}),
    ]
    if args.example[:2] in ("07", "08"):
        cases.append(("Check resources and reflection", "/native-metadata", None,
                      {"policy": "ten-percent", "catalogResource": True}))

    print(f"\nTesting {args.example}: {args.display_url}\n", flush=True)
    connection = http.client.HTTPConnection(args.host, 8080, timeout=5)
    try:
        for index, (title, path, body, expected) in enumerate(cases, 1):
            curl = ["curl", "-sS", args.display_url.rstrip("/") + path]
            if body is not None:
                curl.extend(["-H", "Content-Type: application/json", "-d", body])
            print(f"[{index}/{len(cases)}] {title}\n$ {shlex.join(curl)}", flush=True)
            result = request(connection, path, body)
            if path == "/ready":
                verify_ready(result, aot=args.example[:2] in ("05", "07", "08"), example=args.example)
            else:
                verify_response(result, expected, path)
            print(json.dumps(result, indent=2) + "\n", flush=True)
    except (OSError, http.client.HTTPException, ValueError) as error:
        print(f"Request check failed: {error}", file=sys.stderr)
        print(f"Run make test-app EXAMPLE={args.example[:2]} to start the app and repeat these checks.", file=sys.stderr)
        return 1
    finally:
        connection.close()
    print(f"All {len(cases)} API requests passed. The application is still running.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
