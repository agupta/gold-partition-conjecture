#!/usr/bin/env python3
"""Atomic publication and validation of shard files."""

from __future__ import annotations

import os
from pathlib import Path
import re
import sys


def fail(message: str) -> "NoReturn":
    raise SystemExit(message)


def fsync_file(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def publish_success(temporary: Path, final: Path) -> None:
    source_paths = [Path(f"{temporary}.{suffix}") for suffix in ("out", "err", "meta")]
    final_paths = [Path(f"{final}.{suffix}") for suffix in ("out", "err", "meta")]
    marker = Path(f"{final}.done")
    for path in source_paths:
        if not path.is_file():
            fail(f"missing temporary file: {path}")
        fsync_file(path)
    for path in [*final_paths, marker]:
        if path.exists():
            fail(f"refusing to replace existing shard artifact: {path}")
    for source, destination in zip(source_paths, final_paths):
        os.replace(source, destination)
    fsync_directory(final.parent)

    temporary_marker = Path(f"{temporary}.done")
    descriptor = os.open(
        temporary_marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644
    )
    try:
        os.write(descriptor, b"done\n")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary_marker, marker)
    fsync_directory(final.parent)


def parse_metadata(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            result[key] = value
    return result


def validate_complete(
    final: Path, mode: str, n: str, residue: str, modulus: str, digest: str
) -> None:
    marker = Path(f"{final}.done")
    if not marker.is_file() or marker.read_bytes() != b"done\n":
        fail(f"invalid completion marker: {marker}")
    for suffix in ("out", "err", "meta"):
        path = Path(f"{final}.{suffix}")
        if not path.is_file():
            fail(f"missing completed shard file: {path}")
    metadata = parse_metadata(Path(f"{final}.meta"))
    expected = {
        "mode": mode,
        "n": n,
        "residue": residue,
        "modulus": modulus,
        "generator_options": "o,q,m",
        "binary_sha256": digest,
    }
    for key, value in expected.items():
        if metadata.get(key) != value:
            fail(f"completed shard has unexpected {key}")
    prefix = "GPC-FINAL " if mode == "gpc" else "LEM-FINAL "
    summaries = [
        line
        for line in Path(f"{final}.out").read_text().splitlines()
        if line.startswith(prefix)
    ]
    if len(summaries) != 1:
        fail(f"completed shard has {len(summaries)} final summaries")


def main() -> None:
    if len(sys.argv) < 2:
        fail("usage: shard_io.py {publish-success|validate-complete} ...")
    command = sys.argv[1]
    if command == "publish-success" and len(sys.argv) == 4:
        publish_success(Path(sys.argv[2]), Path(sys.argv[3]))
        return
    if command == "validate-complete" and len(sys.argv) == 8:
        digest = sys.argv[7]
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            fail("invalid binary SHA-256")
        validate_complete(
            Path(sys.argv[2]), sys.argv[3], sys.argv[4], sys.argv[5],
            sys.argv[6], digest
        )
        return
    fail("invalid shard_io.py arguments")


if __name__ == "__main__":
    main()
