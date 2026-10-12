"""Compose-only coordinator for a load client with its own CPU and memory limits."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import sys


class Handler(BaseHTTPRequestHandler):
    def respond(self, status, body):
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        self.respond(200 if self.path == "/ready" else 404, {"ready": self.path == "/ready"})

    def do_POST(self):
        if self.path != "/run":
            self.respond(404, {"error": "Unknown route"})
            return
        try:
            job = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            output = Path(job["output"])
            output.resolve().relative_to(Path("/results").resolve())
            command = [sys.executable, "/benchmark/http_load.py", "--host", "http-benchmark", "--output", str(output)]
            for key in ("warmup", "duration", "rate", "iterations"):
                command.extend([f"--{key}", str(job[key])])
            subprocess.run(command, check=True, timeout=float(job["warmup"]) + 2 * float(job["duration"]) + 60)
            self.respond(200, {"ok": True})
        except Exception as error:
            self.respond(500, {"error": str(error)})


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 9000), Handler).serve_forever()
