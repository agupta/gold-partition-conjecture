#!/usr/bin/env python3
"""Durable publication and validation of balance-census shard files.

A shard becomes visible to the aggregator only after every byte of its
payload is on stable storage.  The order is: fsync each payload file, rename
the payloads into place, fsync the directory, write and fsync the marker under
a temporary name, rename the marker, fsync the directory again.  A marker can
therefore never be observed without its complete, durable payload.

Kept separate from scripts/shard_io.py: the census seals each payload with a
SHA-256 recorded in its metadata, which the Gold Partition shards predate.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import sys


SUFFIXES = ("out", "err", "meta")
SUMMARY_PREFIX = "CENSUS-FINAL "
PARAM_PREFIX = "CENSUS-PARAM "
MARKER = b"done\n"


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
    source_paths = [Path(f"{temporary}.{suffix}") for suffix in SUFFIXES]
    final_paths = [Path(f"{final}.{suffix}") for suffix in SUFFIXES]
    marker = Path(f"{final}.done")

    # Seal the payload before anything is renamed into place.  Truncation or
    # bit rot after publication is then detectable by the aggregator, which is
    # how a corrupt residue was caught in the order-14 GPC run.
    payload = Path(f"{temporary}.out")
    if not payload.is_file():
        fail(f"missing temporary file: {payload}")
    digest = hashlib.sha256(payload.read_bytes()).hexdigest()
    with open(f"{temporary}.meta", "a", encoding="utf-8") as metadata:
        metadata.write(f"out_sha256={digest}\n")

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
        os.write(descriptor, MARKER)
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
    final: Path, n: str, residue: str, modulus: str, digest: str
) -> None:
    marker = Path(f"{final}.done")
    if not marker.is_file() or marker.read_bytes() != MARKER:
        fail(f"invalid completion marker: {marker}")
    for suffix in SUFFIXES:
        path = Path(f"{final}.{suffix}")
        if not path.is_file():
            fail(f"missing completed shard file: {path}")

    metadata = parse_metadata(Path(f"{final}.meta"))
    expected = {
        "mode": "census",
        "n": n,
        "residue": residue,
        "modulus": modulus,
        "generator_options": "o,q,m",
        "binary_sha256": digest,
    }
    for key, value in expected.items():
        if metadata.get(key) != value:
            fail(f"completed shard has unexpected {key}")

    payload = Path(f"{final}.out").read_bytes()
    recorded = metadata.get("out_sha256", "")
    if not re.fullmatch(r"[0-9a-f]{64}", recorded):
        fail(f"{final}.meta: missing or invalid payload digest")
    if hashlib.sha256(payload).hexdigest() != recorded:
        fail(f"{final}.out: payload digest does not match {recorded}")

    lines = payload.decode().splitlines()
    summaries = [line for line in lines if line.startswith(SUMMARY_PREFIX)]
    if len(summaries) != 1:
        fail(f"completed shard has {len(summaries)} final summaries")
    params = [line for line in lines if line.startswith(PARAM_PREFIX)]
    if len(params) != 1:
        fail(f"completed shard has {len(params)} parameter lines")


def main() -> None:
    if len(sys.argv) < 2:
        fail("usage: census_io.py {publish-success|validate-complete} ...")
    command = sys.argv[1]
    if command == "publish-success" and len(sys.argv) == 4:
        publish_success(Path(sys.argv[2]), Path(sys.argv[3]))
        return
    if command == "validate-complete" and len(sys.argv) == 7:
        digest = sys.argv[6]
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            fail("invalid binary SHA-256")
        validate_complete(
            Path(sys.argv[2]), sys.argv[3], sys.argv[4], sys.argv[5], digest
        )
        return
    fail("invalid census_io.py arguments")


if __name__ == "__main__":
    main()
