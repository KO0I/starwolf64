#!/usr/bin/env python3
"""Build the WASM player and serve it privately over Tailscale HTTPS."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener

import dependencies
import run as wasm_build
from refresh_mod import verify_sources as verify_mod_sources

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "build/wasm"


def command(*args):
    print("+ " + " ".join(map(str, args)), flush=True)
    child = subprocess.Popen(list(map(str, args)), cwd=ROOT, start_new_session=True)
    try:
        result = child.wait()
    except BaseException:
        try:
            os.killpg(child.pid, signal.SIGINT)
            child.wait(timeout=8)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait()
        except ProcessLookupError:
            pass
        raise
    if result:
        raise subprocess.CalledProcessError(result, args)


def configured_port(value, port):
    if isinstance(value, dict):
        if str(port) in value.get("TCP", {}):
            return True
        return any(configured_port(child, port) for child in value.values())
    return False


def shared_checkout():
    common = subprocess.check_output(["git", "rev-parse", "--git-common-dir"], cwd=ROOT, text=True).strip()
    return (ROOT / common).resolve().parent


def prepare(cache):
    BUILD.mkdir(parents=True, exist_ok=True)
    (BUILD / "logs").mkdir(exist_ok=True)
    (BUILD / "tmp").mkdir(exist_ok=True)
    os.environ["TMPDIR"] = str(BUILD / "tmp")
    shared = shared_checkout()
    cache = Path(cache).resolve() if cache else shared / "build/wasm"
    lock = ROOT / "tools/wasm/lock.json"
    cache_lock = cache.parent.parent / "tools/wasm/lock.json"
    if cache.resolve() != BUILD.resolve() and cache_lock.is_file() and cache_lock.read_bytes() == lock.read_bytes():
        for name in ("emsdk", "prefix"):
            target = BUILD / name
            source = cache / name
            if not target.exists() and source.is_dir():
                target.symlink_to(source.resolve(), target_is_directory=True)
                print("Reusing matching WASM cache: " + str(target), flush=True)
        if not (BUILD / "downloads").exists() and (cache / "downloads").is_dir():
            shutil.copytree(cache / "downloads", BUILD / "downloads")
    for name in wasm_build.LOCK["submodules"]:
        if not (ROOT / name / "CMakeLists.txt").is_file():
            args = ["git", "submodule", "update", "--init", "--recursive"]
            reference = shared / name
            if shared != ROOT and (reference / "CMakeLists.txt").is_file():
                args += ["--reference", str(reference)]
            command(*args, name)
    wasm_build.verify_sources()
    if not (BUILD / "emsdk/.emscripten").is_file():
        command(sys.executable, "-B", ROOT / "tools/wasm/run.py", "bootstrap")
    else:
        wasm_build.verify_sdk()
    try:
        dependencies.verify(ROOT)
    except FileNotFoundError:
        if (BUILD / "prefix").is_symlink():
            raise RuntimeError("Shared dependency cache is incomplete; choose a complete WASM_CACHE")
        command(sys.executable, "-B", ROOT / "tools/wasm/run.py", "dependencies")
    try:
        verify_mod_sources(ROOT)
    except ValueError:
        command(sys.executable, "-B", ROOT / "tools/wasm/refresh_mod.py")
    command(sys.executable, "-B", ROOT / "tools/wasm/run.py", "public")


def stop(child):
    if child and child.poll() is None:
        child.send_signal(signal.SIGINT)
        try:
            child.wait(timeout=8)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8667)
    parser.add_argument("--https-port", type=int)
    parser.add_argument("--cache", default="", help="Optional matching build/wasm dependency cache")
    parser.add_argument("--no-build", action="store_true", help="Serve the existing exported WASM site")
    args = parser.parse_args()
    https_port = args.port if args.https_port is None else args.https_port
    if not all(1 <= port <= 65535 for port in (args.port, https_port)):
        parser.error("Ports must be between 1 and 65535")
    server = lock_file = serve_prefix = None
    backend = f"http://127.0.0.1:{args.port}"
    def serve_config():
        return json.loads(subprocess.check_output(["tailscale", "serve", "status", "--json"], text=True))
    try:
        BUILD.mkdir(parents=True, exist_ok=True)
        lock_file = (BUILD / "localsite.lock").open("a")
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("localsite is already running in this worktree")
        if not shutil.which("tailscale"):
            raise RuntimeError("Install and connect Tailscale before running make localsite")
        status = json.loads(subprocess.check_output(["tailscale", "status", "--json"], text=True))
        if status.get("BackendState") != "Running":
            raise RuntimeError("Connect Tailscale before running make localsite")
        dns = status["Self"]["DNSName"].rstrip(".")
        config = serve_config()
        if configured_port(config, https_port):
            raise RuntimeError(f"Tailscale port {https_port} is already configured; choose SITE_HTTPS_PORT")
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", args.port))
        if not args.no_build:
            prepare(args.cache)
        site = BUILD / "site"
        if json.loads((site / "site.json").read_text()).get("format") != "starwolf64-wasm-site-v1":
            raise RuntimeError("Expected an exported WASM site in build/wasm/site")
        server = subprocess.Popen([sys.executable, "-B", str(ROOT / "tools/wasm/serve_site.py"),
                                   "--directory", str(site), "--port", str(args.port), "--no-browser"], cwd=ROOT)
        opener = build_opener(ProxyHandler({}))
        backend = f"http://127.0.0.1:{args.port}"
        for attempt in range(100):
            if server.poll() is not None:
                raise RuntimeError("WASM HTTP server failed to start")
            try:
                with opener.open(backend + "/", timeout=1) as response:
                    if response.headers.get("Cross-Origin-Opener-Policy") != "same-origin" or response.headers.get("Cross-Origin-Embedder-Policy") != "require-corp":
                        raise RuntimeError("WASM server is missing cross-origin isolation headers")
                break
            except URLError:
                time.sleep(.1)
        else:
            raise RuntimeError("WASM HTTP server did not become ready")
        if configured_port(serve_config(), https_port):
            raise RuntimeError(f"Tailscale port {https_port} was configured during the build; choose SITE_HTTPS_PORT")
        control = ["tailscale"]
        serve_args = ["serve", "--bg", f"--https={https_port}", backend]
        result = subprocess.run(control + serve_args, capture_output=True, text=True, stdin=subprocess.DEVNULL)
        if result.returncode and ("401 Unauthorized" in result.stderr or "Access denied" in result.stderr):
            if not shutil.which("sudo"):
                raise RuntimeError(result.stderr.strip())
            if configured_port(serve_config(), https_port):
                raise RuntimeError("Tailscale port was claimed by another server")
            control = ["sudo", "-n", "tailscale"]
            print("Using passwordless sudo for this preview's Tailscale route.", flush=True)
            result = subprocess.run(control + serve_args, capture_output=True, text=True, stdin=subprocess.DEVNULL)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip())
        serve_prefix = control
        print(result.stdout.strip(), flush=True)
        suffix = "" if https_port == 443 else f":{https_port}"
        print(f"Local WASM: {backend}/", flush=True)
        print(f"Tailscale WASM: https://{dns}{suffix}/", flush=True)
        print("Keep make localsite running; Ctrl+C stops this preview.", flush=True)
        while server.poll() is None:
            time.sleep(.5)
        raise RuntimeError("The WASM preview server exited")
    except KeyboardInterrupt:
        return 0
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"localsite: {error}\n")
    finally:
        try:
            if serve_prefix:
                current = serve_config()
                handler = current.get("Web", {}).get(f"{dns}:{https_port}", {}).get("Handlers", {}).get("/", {})
                if handler.get("Proxy") == backend:
                    result = subprocess.run(serve_prefix + ["serve", f"--https={https_port}", "off"],
                                            capture_output=True, text=True, stdin=subprocess.DEVNULL)
                    if result.returncode:
                        print("Could not remove this preview's Tailscale route: " + result.stderr, file=sys.stderr)
        except (OSError, ValueError, subprocess.CalledProcessError) as error:
            print(f"Could not remove the preview route on HTTPS port {https_port}: {error}", file=sys.stderr)
        finally:
            stop(server)
            if lock_file:
                lock_file.close()


def interrupted(signum, frame):
    raise KeyboardInterrupt


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, interrupted)
    raise SystemExit(main())
