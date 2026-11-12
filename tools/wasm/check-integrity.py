#!/usr/bin/env python3
"""Prove that corrupted downloads and edits to cached sources are rejected."""

import hashlib
from pathlib import Path
import tempfile

import dependencies
from run import BUILD, LOCK, ROOT, run, verify_sources


def expect_failure(operation, message):
    try:
        operation()
    except RuntimeError as error:
        if message not in str(error):
            raise
    else:
        raise RuntimeError("Corrupted input was accepted")


def main():
    verify_sources()
    dependencies.prepare(ROOT, LOCK, run)
    with tempfile.TemporaryDirectory(dir=BUILD, prefix="integrity-") as directory:
        cached = Path(directory) / "download"
        cached.write_bytes(b"original")
        entry = {"url": "https://example.invalid/not-used", "sha256": hashlib.sha256(b"original").hexdigest()}
        dependencies.checked_download(cached, entry)
        cached.write_bytes(b"corrupted")
        expect_failure(lambda: dependencies.checked_download(cached, entry), "Source hash mismatch")
    # Exercise the actual prepare boundary, then restore the original bytes even
    # when the check fails. This file is documentation, not a compiler input.
    source = BUILD / "sources" / ("json-" + LOCK["sources"]["json"]["commit"]) / "README.md"
    original = source.read_bytes()
    try:
        source.write_bytes(original + b"\nWASM integrity rejection probe\n")
        expect_failure(lambda: dependencies.prepare(ROOT, LOCK, run), "Extracted source differs")
    finally:
        source.write_bytes(original)
    dependencies.prepare(ROOT, LOCK, run)
    print("PASS: corrupt download and modified source tree rejected; source restored")


if __name__ == "__main__":
    main()
