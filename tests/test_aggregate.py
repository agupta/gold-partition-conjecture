#!/usr/bin/env python3
"""Adversarial tests for shard aggregation."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "aggregate", ROOT / "scripts" / "aggregate.py"
)
assert SPEC and SPEC.loader
aggregate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(aggregate)


class AggregationTests(unittest.TestCase):
    digest = "a" * 64

    def write_shard(
        self,
        directory: Path,
        residue: int,
        *,
        n: int = 3,
        modulus: int = 2,
        total: int = 0,
        chain: int = 0,
        low_slave: int = 0,
        half_pair: int = 0,
        triple_count: int = 0,
        open_count: int = 0,
    ) -> None:
        base = directory / f"s{residue}"
        base.with_suffix(".done").write_text("done\n")
        base.with_suffix(".err").write_text("")
        base.with_suffix(".meta").write_text(
            "\n".join(
                [
                    "mode=gpc",
                    f"n={n}",
                    f"residue={residue}",
                    f"modulus={modulus}",
                    "generator_options=o,q,m",
                    "host=test",
                    "started_utc=2026-01-01T00:00:00Z",
                    "finished_utc=2026-01-01T00:00:01Z",
                    f"binary_sha256={self.digest}",
                ]
            )
            + "\n"
        )
        base.with_suffix(".out").write_text(
            "GPC-FINAL "
            f"total={total} chain={chain} low_slave={low_slave} "
            f"half_pair={half_pair} triple={triple_count} open={open_count}\n"
        )

    def complete_fixture(self, directory: Path) -> None:
        self.write_shard(
            directory, 0, total=2, chain=1, low_slave=1
        )
        self.write_shard(
            directory, 1, total=3, low_slave=2, triple_count=1
        )

    def test_complete_partition(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            self.complete_fixture(directory)
            totals, digest = aggregate.read_totals("gpc", 3, 2, directory)
            aggregate.check_gpc(3, totals)
            self.assertEqual(totals["total"], 5)
            self.assertEqual(digest, self.digest)

    def assert_rejected(self, mutate) -> None:
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            self.complete_fixture(directory)
            mutate(directory)
            with self.assertRaises(SystemExit):
                aggregate.read_totals("gpc", 3, 2, directory)

    def test_rejects_missing_marker(self) -> None:
        self.assert_rejected(lambda d: (d / "s1.done").unlink())

    def test_rejects_bad_marker_contents(self) -> None:
        self.assert_rejected(lambda d: (d / "s1.done").write_text(""))

    def test_rejects_duplicate_summary(self) -> None:
        def mutate(directory: Path) -> None:
            path = directory / "s1.out"
            path.write_text(path.read_text() + path.read_text())

        self.assert_rejected(mutate)

    def test_rejects_wrong_residue_metadata(self) -> None:
        def mutate(directory: Path) -> None:
            path = directory / "s1.meta"
            path.write_text(path.read_text().replace("residue=1", "residue=0"))

        self.assert_rejected(mutate)

    def test_rejects_mixed_binary_hashes(self) -> None:
        def mutate(directory: Path) -> None:
            path = directory / "s1.meta"
            path.write_text(path.read_text().replace("a" * 64, "b" * 64))

        self.assert_rejected(mutate)

    def test_rejects_failure_artifact(self) -> None:
        self.assert_rejected(lambda d: (d / "s1.failed").write_text("failed\n"))

    def test_rejects_bad_generator_options(self) -> None:
        def mutate(directory: Path) -> None:
            path = directory / "s1.meta"
            path.write_text(
                path.read_text().replace(
                    "generator_options=o,q,m", "generator_options=q,m"
                )
            )

        self.assert_rejected(mutate)

    def test_rejects_negative_counter(self) -> None:
        def mutate(directory: Path) -> None:
            path = directory / "s1.out"
            path.write_text(path.read_text().replace("open=0", "open=-1"))

        self.assert_rejected(mutate)

    def test_rejects_unexpected_counter(self) -> None:
        def mutate(directory: Path) -> None:
            path = directory / "s1.out"
            path.write_text(path.read_text().rstrip() + " extra=0\n")

        self.assert_rejected(mutate)

    def test_rejects_shard_partition_error(self) -> None:
        def mutate(directory: Path) -> None:
            path = directory / "s1.out"
            path.write_text(path.read_text().replace("low_slave=2", "low_slave=1"))

        self.assert_rejected(mutate)

    def test_rejects_unrecognized_legacy_bare_hash_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            self.complete_fixture(directory)
            for residue in (0, 1):
                path = directory / f"s{residue}.meta"
                lines = [
                    line
                    for line in path.read_text().splitlines()
                    if not line.startswith(("generator_options=", "binary_sha256="))
                ]
                lines.insert(-1, f"{self.digest}  /historical/build/gpc")
                path.write_text("\n".join(lines) + "\n")
            with self.assertRaises(SystemExit):
                aggregate.read_totals("gpc", 3, 2, directory)

    def test_legacy_profiles_are_exactly_allowlisted(self) -> None:
        metadata = {
            "_legacy_bare_hash": "yes",
            "binary_sha256": aggregate.PRODUCTION_GPC_SHA256,
        }
        accepted = (
            ("gpc", 10, 64),
            ("gpc", 11, 64),
            ("gpc", 12, 64),
            ("gpc", 13, 1024),
            ("gpc", 14, 4096),
        )
        for mode, n, modulus in accepted:
            with self.subTest(mode=mode, n=n, modulus=modulus):
                self.assertTrue(
                    aggregate.accepts_legacy_profile(mode, n, modulus, metadata)
                )

        rejected = (
            ("majority", 14, 4096),
            ("gpc", 9, 64),
            ("gpc", 13, 4096),
            ("gpc", 14, 1024),
        )
        for mode, n, modulus in rejected:
            with self.subTest(mode=mode, n=n, modulus=modulus):
                self.assertFalse(
                    aggregate.accepts_legacy_profile(mode, n, modulus, metadata)
                )

        wrong_hash = dict(metadata, binary_sha256="b" * 64)
        self.assertFalse(
            aggregate.accepts_legacy_profile("gpc", 14, 4096, wrong_hash)
        )
        keyed_hash = dict(metadata, _legacy_bare_hash="no")
        self.assertFalse(
            aggregate.accepts_legacy_profile("gpc", 14, 4096, keyed_hash)
        )


if __name__ == "__main__":
    unittest.main()
