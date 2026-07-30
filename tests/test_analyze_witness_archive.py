#!/usr/bin/env python3
"""Unit tests for the retained-witness archive analyzer."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import analyze_witness_archive as analyzer  # noqa: E402


CYCLE_WITNESS = (
    "14:0000000000000003000500030005000300050002000401ff043f03c7"
)
EQUALITY_WITNESS = "3:000000000001"


class ArchiveAnalyzerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)

    def write(self, name: str, *lines: str) -> None:
        (self.directory / name).write_text("\n".join(lines) + "\n")

    def test_loads_strict_retained_record_schemas(self) -> None:
        self.write(
            "s0.out",
            "CENSUS-CYCLE relation=full length=8 count=1 "
            f"witness={CYCLE_WITNESS}",
            "CENSUS-TAIL num=1 den=2 count=1 connected=1 "
            f"witness={CYCLE_WITNESS}",
            "CENSUS-EQUALITY count=1 connected=1 "
            f"witness={EQUALITY_WITNESS}",
        )
        cycles, tails, equality, payloads = analyzer.load_archive(
            self.directory
        )
        self.assertEqual(payloads, 1)
        self.assertEqual(cycles["full"][8], {CYCLE_WITNESS})
        self.assertEqual(tails, [(Fraction(1, 2), CYCLE_WITNESS)])
        self.assertEqual(equality, {EQUALITY_WITNESS})

    def test_rejects_duplicate_or_unexpected_fields(self) -> None:
        self.write(
            "s0.out",
            "CENSUS-CYCLE relation=full relation=inc length=8 count=1 "
            f"witness={CYCLE_WITNESS}",
        )
        with self.assertRaisesRegex(ValueError, "duplicate field relation"):
            analyzer.load_archive(self.directory)

    def test_rejects_noncontiguous_payload_indices(self) -> None:
        self.write("s1.out", "")
        with self.assertRaisesRegex(ValueError, "not the contiguous range"):
            analyzer.load_archive(self.directory)

    def test_recomputes_record_properties(self) -> None:
        cycle = analyzer.analyze_cycle(CYCLE_WITNESS)
        self.assertEqual(cycle["balance"], "1/2")
        self.assertEqual(cycle["full_spectrum"], [4, 8])
        self.assertEqual(cycle["restricted_spectrum"], [4, 8])

        tail = analyzer.analyze_tail(CYCLE_WITNESS)
        self.assertEqual(tail["balance"], "1/2")

        self.assertEqual(
            analyzer.analyze_equality(EQUALITY_WITNESS),
            (EQUALITY_WITNESS, 2),
        )
        with self.assertRaisesRegex(ValueError, "equality witness has balance"):
            analyzer.analyze_equality(CYCLE_WITNESS)


if __name__ == "__main__":
    unittest.main()
