#!/usr/bin/env python3
"""Unit tests for the balance-census aggregator and witness checker."""

from __future__ import annotations

from fractions import Fraction
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
AGGREGATE = ROOT / "scripts" / "aggregate_census.py"
sys.path.insert(0, str(ROOT / "scripts"))

import census_witness as cw  # noqa: E402


DIGEST = "a" * 64

PARAM = (
    "CENSUS-PARAM version=1 n=3 maxn=15 tail_num=9 tail_den=25"
    " tail_capacity=4096 equality_capacity=4096 dfs_budget=4000000"
    " decompose=1"
)
FINAL = (
    "CENSUS-FINAL total=5 chain=1 third=1 above=3 viol=0 connected=2"
    " cyclic=0 cyclic_inc=0 skipdual=1 dualpair=1 dualtie=3 tail_values=0"
    " equality_classes=1 maxscc=0 overflow=0"
    + "".join(f" c{length}=0" for length in range(3, 16))
    + "".join(f" i{length}=0" for length in range(3, 16))
)
MIN_ABOVE = "CENSUS-MIN kind=above num=1 den=2 witness=3:000000000000"
MIN_CONNECTED = (
    "CENSUS-MIN kind=above_connected num=1 den=2 witness=3:000000000000"
)
EQUALITY = "CENSUS-EQUALITY count=1 connected=1 witness=3:000000000001"

DEFAULT_LINES = [PARAM, FINAL, MIN_ABOVE, MIN_CONNECTED, EQUALITY]


def write_shard(
    outdir: Path, residue: int, modulus: int, lines, *,
    digest: str = DIGEST, marker: bytes = b"done\n", n: int = 3,
) -> None:
    base = outdir / f"s{residue}"
    payload = ("\n".join(lines) + "\n").encode()
    base.with_suffix(".out").write_bytes(payload)
    base.with_suffix(".err").write_text("")
    base.with_suffix(".meta").write_text(
        "\n".join(
            [
                f"out_sha256={hashlib.sha256(payload).hexdigest()}",
                "mode=census",
                f"n={n}",
                f"residue={residue}",
                f"modulus={modulus}",
                "generator_options=o,q,m",
                "host=test",
                "started_utc=2026-07-26T00:00:00Z",
                "finished_utc=2026-07-26T00:00:01Z",
                f"binary_sha256={digest}",
            ]
        )
        + "\n"
    )
    base.with_suffix(".done").write_bytes(marker)


def run_aggregate(outdir: Path, n: int = 3, modulus: int = 1):
    return subprocess.run(
        [sys.executable, str(AGGREGATE), str(n), str(modulus), str(outdir)],
        capture_output=True,
        text=True,
    )


class AggregatorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.outdir = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)

    def build(self, lines=None, **kwargs) -> None:
        write_shard(self.outdir, 0, 1, lines or DEFAULT_LINES, **kwargs)

    def assert_rejects(self, fragment: str) -> None:
        result = run_aggregate(self.outdir)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn(fragment, result.stderr)

    def test_accepts_a_complete_partition(self) -> None:
        self.build()
        result = run_aggregate(self.outdir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PASS: 1 complete, disjoint shards", result.stdout)
        self.assertIn("independently recomputed", result.stdout)

    def test_rejects_a_missing_marker(self) -> None:
        self.build()
        (self.outdir / "s0.done").unlink()
        self.assert_rejects("completion marker")

    def test_rejects_a_corrupt_marker(self) -> None:
        self.build(marker=b"done")
        self.assert_rejects("completion marker")

    def test_rejects_a_truncated_payload(self) -> None:
        self.build()
        payload = self.outdir / "s0.out"
        payload.write_bytes(payload.read_bytes()[:-1])
        self.assert_rejects("payload digest does not match")

    def test_rejects_a_missing_payload_digest(self) -> None:
        self.build()
        metadata = self.outdir / "s0.meta"
        metadata.write_text(
            "\n".join(
                line for line in metadata.read_text().splitlines()
                if not line.startswith("out_sha256=")
            )
            + "\n"
        )
        self.assert_rejects("payload digest")

    def test_rejects_a_failure_artifact(self) -> None:
        self.build()
        (self.outdir / "s0.failed").write_text("failed\n")
        self.assert_rejects("failure artifacts remain")

    def test_rejects_a_wrong_total(self) -> None:
        self.build([PARAM, FINAL.replace("total=5", "total=4"), MIN_ABOVE,
                    MIN_CONNECTED, EQUALITY])
        self.assert_rejects("expected 5")

    def test_rejects_a_missing_summary_field(self) -> None:
        self.build([PARAM, FINAL.replace(" c15=0", ""), MIN_ABOVE,
                    MIN_CONNECTED, EQUALITY])
        self.assert_rejects("missing c15")

    def test_rejects_two_summaries(self) -> None:
        self.build([PARAM, FINAL, FINAL, MIN_ABOVE, MIN_CONNECTED, EQUALITY])
        self.assert_rejects("2 final summaries")

    def test_rejects_a_violation(self) -> None:
        self.build([PARAM, FINAL.replace("viol=0", "viol=1"), MIN_ABOVE,
                    MIN_CONNECTED, EQUALITY])
        self.assert_rejects("1/3--2/3 bound is violated")

    def test_rejects_an_exhausted_cycle_budget(self) -> None:
        self.build([PARAM, FINAL.replace("overflow=0", "overflow=1"),
                    MIN_ABOVE, MIN_CONNECTED, EQUALITY])
        self.assert_rejects("exhausted its budget")

    def test_rejects_a_falsified_minimum(self) -> None:
        """The claimed value must survive independent recomputation."""
        self.build([PARAM, FINAL,
                    "CENSUS-MIN kind=above num=1 den=3 witness=3:000000000000",
                    MIN_CONNECTED, EQUALITY])
        self.assert_rejects("not strictly above 1/3")

    def test_rejects_a_witness_that_does_not_attain_its_value(self) -> None:
        self.build([PARAM, FINAL,
                    "CENSUS-MIN kind=above num=2 den=5 witness=3:000000000000",
                    "CENSUS-MIN kind=above_connected num=2 den=5"
                    " witness=3:000000000000", EQUALITY])
        self.assert_rejects("witness has balance 1/2")

    def test_rejects_a_malformed_witness(self) -> None:
        self.build([PARAM, FINAL,
                    "CENSUS-MIN kind=above num=1 den=2 witness=3:00000000",
                    MIN_CONNECTED, EQUALITY])
        self.assert_rejects("carries")

    def test_rejects_a_witness_that_is_not_a_poset(self) -> None:
        """Bits 0<1 and 1<0 encode no partial order."""
        self.build([PARAM, FINAL,
                    "CENSUS-MIN kind=above num=1 den=2"
                    " witness=3:000200010000", MIN_CONNECTED, EQUALITY])
        self.assert_rejects("mutually below")

    def test_rejects_an_equality_witness_outside_the_family(self) -> None:
        self.build([PARAM, FINAL,
                    MIN_ABOVE, MIN_CONNECTED,
                    "CENSUS-EQUALITY count=1 connected=1"
                    " witness=3:000000000000"])
        self.assert_rejects("balance is 1/2")

    def test_rejects_a_wrong_equality_count(self) -> None:
        self.build([PARAM, FINAL.replace("third=1", "third=2")
                    .replace("above=3", "above=2"),
                    MIN_ABOVE, MIN_CONNECTED, EQUALITY])
        self.assert_rejects("equality witness counts do not sum")

    def test_rejects_disagreeing_parameters(self) -> None:
        write_shard(self.outdir, 0, 2, DEFAULT_LINES)
        write_shard(
            self.outdir, 1, 2,
            [PARAM.replace("tail_den=25", "tail_den=20"),
             FINAL.replace("total=5", "total=0").replace("chain=1", "chain=0")
             .replace("third=1", "third=0").replace("above=3", "above=0")
             .replace("connected=2", "connected=0")
             .replace("skipdual=1", "skipdual=0")
             .replace("dualpair=1", "dualpair=0")
             .replace("dualtie=3", "dualtie=0")],
        )
        result = run_aggregate(self.outdir, modulus=2)
        self.assertEqual(result.returncode, 1)
        self.assertIn("parameters differ", result.stderr)

    def test_rejects_two_binary_hashes(self) -> None:
        write_shard(self.outdir, 0, 2, DEFAULT_LINES)
        write_shard(
            self.outdir, 1, 2,
            [PARAM,
             FINAL.replace("total=5", "total=0").replace("chain=1", "chain=0")
             .replace("third=1", "third=0").replace("above=3", "above=0")
             .replace("connected=2", "connected=0")
             .replace("skipdual=1", "skipdual=0")
             .replace("dualpair=1", "dualpair=0")
             .replace("dualtie=3", "dualtie=0")],
            digest="b" * 64,
        )
        result = run_aggregate(self.outdir, modulus=2)
        self.assertEqual(result.returncode, 1)
        self.assertIn("distinct binary hashes", result.stderr)

    def test_rejects_an_incomplete_partition(self) -> None:
        write_shard(self.outdir, 0, 2, DEFAULT_LINES)
        self.assert_rejects_missing()

    def assert_rejects_missing(self) -> None:
        result = run_aggregate(self.outdir, modulus=2)
        self.assertEqual(result.returncode, 1)
        self.assertIn("shard 1", result.stderr)


class WitnessTest(unittest.TestCase):
    """The independent checker must agree with hand computation."""

    def test_three_element_poset_t(self) -> None:
        t = (0b010, 0, 0)  # 0 < 1, element 2 isolated
        self.assertEqual(cw.extensions(t), 3)
        self.assertEqual(cw.balance(t), Fraction(1, 3))
        self.assertTrue(cw.is_equality_family(t))

    def test_antichain(self) -> None:
        antichain = (0, 0, 0)
        self.assertEqual(cw.extensions(antichain), 6)
        self.assertEqual(cw.balance(antichain), Fraction(1, 2))
        self.assertFalse(cw.is_equality_family(antichain))

    def test_chain_has_no_balance_constant(self) -> None:
        chain = (0b110, 0b100, 0)
        self.assertEqual(cw.extensions(chain), 1)
        self.assertIsNone(cw.balance(chain))
        self.assertFalse(cw.is_equality_family(chain))

    def test_dp_matches_brute_force(self) -> None:
        for witness in (
            "6:0000000000030001000f0009",
            "7:0040004000430041004f00490000",
            "8:000000000003000100070009003f002b",
        ):
            up = cw.decode(witness)
            with self.subTest(witness=witness):
                self.assertEqual(cw.balance(up), cw.brute_force_balance(up))

    def test_equality_family_recurrence(self) -> None:
        self.assertEqual(
            [cw.equality_family_count(n) for n in range(3, 15)],
            [1, 2, 3, 5, 8, 12, 18, 27, 40, 59, 87, 128],
        )

    def test_ordinal_sum_recognition(self) -> None:
        # T + singleton, from the order-4 census output.
        up = cw.decode("4:0008000800090000")
        self.assertEqual(cw.balance(up), Fraction(1, 3))
        self.assertTrue(cw.is_equality_family(up))
        self.assertEqual(len(cw.ordinal_summands(up)), 2)

    def test_rejects_a_cyclic_relation(self) -> None:
        with self.assertRaises(cw.WitnessError):
            cw.decode("3:000200010000")

    def test_rejects_a_non_transitive_relation(self) -> None:
        # 0 < 1 and 1 < 2 without 0 < 2.
        with self.assertRaises(cw.WitnessError):
            cw.decode("3:000200040000")

    def test_encode_round_trip(self) -> None:
        up = cw.decode("8:000000000003000100070009003f002b")
        self.assertEqual(cw.decode(cw.encode(up)), up)

    def test_cycle_lengths_of_a_directed_triangle(self) -> None:
        self.assertEqual(cw.cycle_lengths([0b010, 0b100, 0b001]), {3})
        self.assertEqual(cw.cycle_lengths([0b010, 0b100, 0]), set())


if __name__ == "__main__":
    unittest.main()
