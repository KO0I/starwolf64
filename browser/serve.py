from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
import argparse

ROOT = Path(__file__).resolve().parent
ROM = ROOT / "wolfen.z64"

class Handler(BaseHTTPRequestHandler):
    def do_HEAD(self):
        self.respond(False)

    def do_GET(self):
        self.respond(True)

    def respond(self, body):
        route = urlsplit(self.path).path
        if route in ("/", "/index.html"):
            file, mime = ROOT / "index.html", "text/html; charset=utf-8"
        elif route == "/game.z64":
            file, mime = ROM, "application/octet-stream"
        elif route == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        else:
            self.send_error(404)
            return
        if not file.is_file():
            self.send_error(503, "Run python3 tools/build_wolfen.py from the project directory, then reload." if file == ROM else "File not found")
            return
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(file.stat().st_size))
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        if body:
            with file.open("rb") as stream:
                while data := stream.read(256 * 1024):
                    self.wfile.write(data)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8641)
    args = parser.parse_args()
    print(f"Star Fox 64 browser player on http://127.0.0.1:{args.port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
