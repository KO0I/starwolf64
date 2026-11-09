"""Serve the exported patch-only emulator for local preview."""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent / "runtime/site"
FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/client.js": ("client.js", "text/javascript; charset=utf-8"),
    "/rom-patch.mjs": ("rom-patch.mjs", "text/javascript; charset=utf-8"),
    "/coi-serviceworker.js": ("coi-serviceworker.js", "text/javascript; charset=utf-8"),
    "/wolfen.patch.json": ("wolfen.patch.json", "application/json"),
}


class Handler(BaseHTTPRequestHandler):
    def do_HEAD(self):
        self.respond(False)

    def do_GET(self):
        self.respond(True)

    def respond(self, body):
        route = urlsplit(self.path).path
        if route == "/health":
            patch = json.loads((ROOT / "wolfen.patch.json").read_bytes())
            payload = json.dumps({"runtime": "emulator", "base_rom_required": True,
                                  "rom_version": patch["target"]["sha256"][:16]}).encode()
            mime = "application/json"
        elif route in FILES:
            name, mime = FILES[route]
            payload = (ROOT / name).read_bytes()
        elif route == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        if body:
            try:
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8641)
    args = parser.parse_args()
    if not (ROOT / "wolfen.patch.json").is_file():
        parser.error("Run python3 tools/export_browser_site.py before starting the preview")
    print("Patch-only emulator on http://127.0.0.1:" + str(args.port), flush=True)
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
