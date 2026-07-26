#!/usr/bin/env python3
"""Check complete small orders from the two compiled classifiers."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys


COUNTS = {
    1: 1,
    2: 2,
    3: 5,
    4: 16,
    5: 63,
    6: 318,
    7: 2_045,
    8: 16_999,
    9: 183_231,
}
GPC = {
    8: (16_633, 365),
    9: (178_771, 4_459),
}


def summary(binary: Path, n: int, prefix: str) -> dict[str, int]:
    result = subprocess.run(
        [str(binary), str(n), "o", "q"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    lines = [line for line in result.stdout.splitlines() if line.startswith(prefix)]
    if len(lines) != 1:
        raise SystemExit(f"{binary.name}, n={n}: {len(lines)} summaries")
    return {
        key: int(value)
        for key, value in (
            token.split("=", 1) for token in lines[0].split()[1:]
        )
    }


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: check_programs.py GPC_BINARY MAJORITY_BINARY")
    gpc, majority = map(Path, sys.argv[1:])
    for n, expected_total in COUNTS.items():
        fields = summary(gpc, n, "GPC-FINAL ")
        pair_total = fields["low_slave"] + fields["half_pair"]
        if (
            fields["total"] != expected_total
            or fields["chain"] != 1
            or fields["open"] != 0
            or sum(
                fields[key]
                for key in ("chain", "low_slave", "half_pair", "triple", "open")
            )
            != expected_total
        ):
            raise SystemExit(f"invalid GPC summary at n={n}: {fields}")
        if n in GPC and (pair_total, fields["triple"]) != GPC[n]:
            raise SystemExit(f"GPC regression mismatch at n={n}")
        print(f"PASS: compiled GPC classifier, n={n}")

    fields = summary(majority, 8, "LEM-FINAL ")
    if (
        fields["total"] != COUNTS[8]
        or fields["chain"] != 1
        or fields["cyclic"] != 0
        or fields["third"] != 12
        or fields["above"] != 16_986
        or fields["viol"] != 0
        or fields["skipdual"] != fields["dualpair"]
    ):
        raise SystemExit(f"invalid majority summary at n=8: {fields}")
    print("PASS: compiled majority classifier, n=8")


if __name__ == "__main__":
    main()
