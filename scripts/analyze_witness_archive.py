#!/usr/bin/env python3
"""Recompute the manuscript's retained-witness statistics from census shards.

The order-14 census retains one witness per cycle length per shard, one
witness per low-tail value per shard, and equality-family representatives.
Those are deliberately not uniform samples of poset classes.  This program
reconstructs the exact retained sets and recomputes the statistics reported in
Sections 4 and 6 of the paper.

Usage:
    python3 scripts/analyze_witness_archive.py \
        /path/to/census-n14-shards --jobs 8 --check-paper

The directory must contain the completed ``s*.out`` payloads.  First use
``aggregate_census.py --verify all`` to validate the complete inventory,
metadata, and payload seals.  This analyzer then validates the retained-record
schemas and claims with the independent ideal-lattice implementation in
``census_witness.py`` and the published-certificate implementation in
``gpc_certificate.py``; it never calls a production C binary.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from fractions import Fraction
import json
import multiprocessing
import os
from pathlib import Path
import re
import sys

import census_witness as cw
import gpc_certificate as gc


def fields(line: str, expected: set[str], source: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for token in line.split()[1:]:
        if "=" not in token:
            raise ValueError(f"{source}: malformed token {token!r}")
        key, value = token.split("=", 1)
        if key in result:
            raise ValueError(f"{source}: duplicate field {key}")
        result[key] = value
    if set(result) != expected:
        missing = sorted(expected - set(result))
        extra = sorted(set(result) - expected)
        raise ValueError(
            f"{source}: invalid fields; missing={missing}, unexpected={extra}"
        )
    return result


def nonnegative(value: str, field: str, source: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise ValueError(
            f"{source}: non-integer {field}={value!r}"
        ) from error
    if parsed < 0:
        raise ValueError(f"{source}: negative {field}={value!r}")
    return parsed


def cyclic_part(adjacency: list[int]) -> int:
    reach = list(adjacency)
    for middle in range(len(adjacency)):
        for source in range(len(adjacency)):
            if (reach[source] >> middle) & 1:
                reach[source] |= reach[middle]
    return sum(
        1 << vertex
        for vertex in range(len(adjacency))
        if (reach[vertex] >> vertex) & 1
    )


def is_bipartite(adjacency: list[int], vertices: int) -> bool:
    neighbors = [0] * len(adjacency)
    for source in cw.bits(vertices):
        for target in cw.bits(adjacency[source] & vertices):
            neighbors[source] |= 1 << target
            neighbors[target] |= 1 << source

    colors: dict[int, int] = {}
    for start in cw.bits(vertices):
        if start in colors:
            continue
        colors[start] = 0
        stack = [start]
        while stack:
            source = stack.pop()
            for target in cw.bits(neighbors[source]):
                if target not in colors:
                    colors[target] = colors[source] ^ 1
                    stack.append(target)
                elif colors[target] == colors[source]:
                    return False
    return True


def automorphism_summary(up: tuple[int, ...]) -> tuple[int, bool]:
    """Return the automorphism-group order and whether one swaps a pair."""
    colors = cw.refine_colors(up)
    by_color: dict[int, list[int]] = defaultdict(list)
    for vertex, color in enumerate(colors):
        by_color[color].append(vertex)
    order = sorted(range(len(up)), key=lambda vertex: (
        len(by_color[colors[vertex]]), vertex
    ))
    image = [-1] * len(up)
    used = 0
    count = 0
    transposing = False

    def visit(index: int) -> None:
        nonlocal count, transposing, used
        if index == len(order):
            count += 1
            if not transposing:
                for source, target in enumerate(image):
                    if (
                        target != source
                        and image[target] == source
                        and not ((up[source] >> target) & 1)
                        and not ((up[target] >> source) & 1)
                    ):
                        transposing = True
                        break
            return

        source = order[index]
        for target in by_color[colors[source]]:
            if (used >> target) & 1:
                continue
            if any(
                ((up[source] >> earlier) & 1)
                != ((up[target] >> image[earlier]) & 1)
                or ((up[earlier] >> source) & 1)
                != ((up[image[earlier]] >> target) & 1)
                for earlier in order[:index]
            ):
                continue
            image[source] = target
            used |= 1 << target
            visit(index + 1)
            used &= ~(1 << target)
            image[source] = -1

    visit(0)
    return count, transposing


def analyze_cycle(witness: str) -> dict:
    up = cw.decode(witness)
    analysis = cw.Analysis(up)
    full = analysis.majority_digraph(True)
    restricted = analysis.majority_digraph(False)
    vertices = cyclic_part(full)
    members = list(cw.bits(vertices))
    balance = analysis.balance()
    return {
        "witness": witness,
        "balance": str(balance) if balance is not None else None,
        "full_spectrum": sorted(cw.cycle_lengths(full)),
        "restricted_spectrum": sorted(cw.cycle_lengths(restricted)),
        "cyclic_part_has_comparable_pair": any(
            (up[source] >> target) & 1
            for source in members
            for target in members
        ),
        "cyclic_part_bipartite": is_bipartite(full, vertices),
    }


def analyze_long(witness: str) -> tuple[str, int, bool, str, int]:
    up = cw.decode(witness)
    order, transposing = automorphism_summary(up)
    return witness, order, transposing, gc.classify(up), cw.width(up)


def analyze_tail(witness: str) -> dict:
    up = cw.decode(witness)
    analysis = cw.Analysis(up)
    return {
        "witness": witness,
        "balance": str(analysis.balance()),
        "certificate": gc.classify(up),
        "width": cw.width(up),
        "has_cycle": bool(cw.cycle_lengths(analysis.majority_digraph(True))),
    }


def analyze_equality(witness: str) -> tuple[str, int]:
    up = cw.decode(witness)
    balance = cw.Analysis(up).balance()
    if balance != Fraction(1, 3):
        raise ValueError(f"equality witness has balance {balance}: {witness}")
    if not cw.is_equality_family(up):
        raise ValueError(f"non-family equality witness: {witness}")
    return witness, cw.width(up)


def load_archive(directory: Path) -> tuple[
    dict[str, dict[int, set[str]]],
    list[tuple[Fraction, str]],
    set[str],
    int,
]:
    cycles = {
        "full": defaultdict(set),
        "inc": defaultdict(set),
    }
    tails: list[tuple[Fraction, str]] = []
    equality: set[str] = set()
    payloads = sorted(directory.glob("s*.out"))
    if not payloads:
        raise SystemExit(f"no s*.out payloads in {directory}")
    indices = []
    for path in payloads:
        match = re.fullmatch(r"s(\d+)\.out", path.name)
        if not match:
            raise ValueError(f"{path}: invalid shard payload name")
        indices.append(int(match.group(1)))
    if sorted(indices) != list(range(len(payloads))):
        raise ValueError(
            "shard payload indices are not the contiguous range "
            f"0..{len(payloads) - 1}"
        )

    for path in payloads:
        for line_number, line in enumerate(path.read_text().splitlines(), 1):
            source = f"{path}:{line_number}"
            if line.startswith("CENSUS-CYCLE "):
                item = fields(
                    line, {"relation", "length", "count", "witness"}, source
                )
                relation = item["relation"]
                if relation not in cycles:
                    raise ValueError(f"{path}: unknown relation {relation}")
                length = nonnegative(item["length"], "length", source)
                count = nonnegative(item["count"], "count", source)
                if length < 3 or count == 0:
                    raise ValueError(
                        f"{source}: invalid cycle length/count {length}/{count}"
                    )
                if item["witness"] in cycles[relation][length]:
                    raise ValueError(f"{source}: duplicate retained cycle record")
                cycles[relation][length].add(item["witness"])
            elif line.startswith("CENSUS-TAIL "):
                item = fields(
                    line, {"num", "den", "count", "connected", "witness"},
                    source,
                )
                numerator = nonnegative(item["num"], "num", source)
                denominator = nonnegative(item["den"], "den", source)
                count = nonnegative(item["count"], "count", source)
                connected = nonnegative(
                    item["connected"], "connected", source
                )
                if denominator == 0 or count == 0 or connected > count:
                    raise ValueError(f"{source}: invalid tail counters")
                record = (Fraction(numerator, denominator), item["witness"])
                if record in tails:
                    raise ValueError(f"{source}: duplicate retained tail record")
                tails.append(record)
            elif line.startswith("CENSUS-EQUALITY "):
                item = fields(
                    line, {"count", "connected", "witness"}, source
                )
                count = nonnegative(item["count"], "count", source)
                connected = nonnegative(
                    item["connected"], "connected", source
                )
                if count == 0 or connected > count:
                    raise ValueError(f"{source}: invalid equality counters")
                if item["witness"] in equality:
                    raise ValueError(
                        f"{source}: duplicate retained equality record"
                    )
                equality.add(item["witness"])
    return cycles, tails, equality, len(payloads)


def parallel_map(function, items: list[str], jobs: int):
    # Python 3.14 changed the POSIX default to forkserver, which needs a local
    # control socket and is unavailable in some batch sandboxes.  Plain fork
    # needs no socket and is safe here: workers receive immutable witness
    # strings and return new result objects.  Fall back to the platform
    # default where fork is unavailable.
    methods = multiprocessing.get_all_start_methods()
    context = multiprocessing.get_context(
        "fork" if "fork" in methods else methods[0]
    )
    with ProcessPoolExecutor(max_workers=jobs, mp_context=context) as executor:
        return list(executor.map(function, items, chunksize=64))


def summarize(directory: Path, jobs: int) -> dict:
    cycles, tail_records, equality_witnesses, payloads = load_archive(directory)
    full_by_length = cycles["full"]
    inc_by_length = cycles["inc"]
    all_cycle_witnesses = sorted(set().union(*full_by_length.values()))
    print(
        f"analyzing {len(all_cycle_witnesses):,} distinct cycle witnesses",
        file=sys.stderr,
        flush=True,
    )
    cycle_rows = parallel_map(analyze_cycle, all_cycle_witnesses, jobs)
    cycle_info = {row["witness"]: row for row in cycle_rows}
    for relation, by_length in cycles.items():
        spectrum_key = (
            "full_spectrum" if relation == "full"
            else "restricted_spectrum"
        )
        for length, witnesses in by_length.items():
            for witness in witnesses:
                if length not in cycle_info[witness][spectrum_key]:
                    raise ValueError(
                        f"{relation} length-{length} record is false: {witness}"
                    )

    per_length = {}
    for length in sorted(full_by_length):
        witnesses = sorted(full_by_length[length])
        per_length[str(length)] = {
            "witnesses": len(witnesses),
            "balance_one_half": sum(
                cycle_info[witness]["balance"] == "1/2"
                for witness in witnesses
            ),
            "cyclic_part_has_comparable_pair": sum(
                cycle_info[witness]["cyclic_part_has_comparable_pair"]
                for witness in witnesses
            ),
        }

    long_witnesses = sorted(
        full_by_length.get(7, set()) | full_by_length.get(8, set())
    )
    print(
        f"analyzing automorphisms of {len(long_witnesses)} long-cycle witnesses",
        file=sys.stderr,
        flush=True,
    )
    long_rows = parallel_map(analyze_long, long_witnesses, jobs)

    even_spectrum = [
        row for row in cycle_rows
        if row["full_spectrum"]
        and all(length % 2 == 0 for length in row["full_spectrum"])
    ]

    distinct_tail_witnesses = sorted({
        witness for _, witness in tail_records
    })
    representative_by_value: dict[Fraction, str] = {}
    for value, witness in tail_records:
        representative_by_value[value] = min(
            witness, representative_by_value.get(value, witness)
        )
    print(
        f"analyzing {len(distinct_tail_witnesses)} low-tail witnesses",
        file=sys.stderr,
        flush=True,
    )
    tail_rows = parallel_map(analyze_tail, distinct_tail_witnesses, jobs)
    tail_info = {row["witness"]: row for row in tail_rows}
    for value, witness in tail_records:
        if Fraction(tail_info[witness]["balance"]) != value:
            raise ValueError(
                f"tail record declares {value}, recomputed "
                f"{tail_info[witness]['balance']}: {witness}"
            )
    value_representatives = sorted(representative_by_value.values())

    print(
        f"checking {len(equality_witnesses)} equality representatives",
        file=sys.stderr,
        flush=True,
    )
    equality_rows = parallel_map(
        analyze_equality, sorted(equality_witnesses), jobs
    )

    return {
        "archive": str(directory),
        "payloads": payloads,
        "cycle": {
            "full_and_restricted_witness_sets_equal": (
                {key: sorted(value) for key, value in full_by_length.items()}
                == {key: sorted(value) for key, value in inc_by_length.items()}
            ),
            "records_by_length": per_length,
            "distinct_witnesses": len(all_cycle_witnesses),
            "with_comparable_pair_in_cyclic_part": sum(
                row["cyclic_part_has_comparable_pair"] for row in cycle_rows
            ),
            "all_even_spectrum": len(even_spectrum),
            "all_even_spectrum_nonbipartite": sum(
                not row["cyclic_part_bipartite"] for row in even_spectrum
            ),
            "minimum_balance": str(min(
                Fraction(row["balance"]) for row in cycle_rows
            )),
            "long_witnesses": len(long_witnesses),
            "long_balance_one_half": sum(
                cycle_info[witness]["balance"] == "1/2"
                for witness in long_witnesses
            ),
            "long_bilateral_certificates": sum(
                certificate == "bilateral"
                for _, _, _, certificate, _ in long_rows
            ),
            "long_widths": sorted({width for _, _, _, _, width in long_rows}),
            "long_transposing_automorphism": sum(
                transposing for _, _, transposing, _, _ in long_rows
            ),
            "long_trivial_automorphism_group": sum(
                order == 1 for _, order, _, _, _ in long_rows
            ),
            "length_8_bipartite": sum(
                cycle_info[witness]["cyclic_part_bipartite"]
                for witness in full_by_length.get(8, set())
            ),
        },
        "tail": {
            "records": len(tail_records),
            "distinct_witnesses": len(distinct_tail_witnesses),
            "distinct_values": len(representative_by_value),
            "no_pair_certificate_all_witnesses": sum(
                not gc.is_pair(row["certificate"]) for row in tail_rows
            ),
            "no_pair_certificate_one_per_value": sum(
                not gc.is_pair(tail_info[witness]["certificate"])
                for witness in value_representatives
            ),
            "widths": sorted({row["width"] for row in tail_rows}),
            "witnesses_with_majority_cycle": sum(
                row["has_cycle"] for row in tail_rows
            ),
            "L14_1_9_certificate": tail_info[
                representative_by_value[Fraction(254, 725)]
            ]["certificate"],
        },
        "equality": {
            "representatives": len(equality_rows),
            "widths": sorted({width for _, width in equality_rows}),
        },
    }


EXPECTED = {
    "payloads": 16_384,
    "cycle": {
        "full_and_restricted_witness_sets_equal": True,
        "distinct_witnesses": 44_013,
        "with_comparable_pair_in_cyclic_part": 166,
        "all_even_spectrum": 3_212,
        "all_even_spectrum_nonbipartite": 7,
        "minimum_balance": "2869/5810",
        "long_witnesses": 37,
        "long_balance_one_half": 37,
        "long_bilateral_certificates": 37,
        "long_widths": [7, 8, 9, 10],
        "long_transposing_automorphism": 35,
        "long_trivial_automorphism_group": 2,
        "length_8_bipartite": 9,
        "records_by_length": {
            "3": {
                "witnesses": 16_384,
                "balance_one_half": 11_626,
                "cyclic_part_has_comparable_pair": 31,
            },
            "4": {
                "witnesses": 16_384,
                "balance_one_half": 8_162,
                "cyclic_part_has_comparable_pair": 11,
            },
            "5": {
                "witnesses": 8_428,
                "balance_one_half": 2_296,
                "cyclic_part_has_comparable_pair": 35,
            },
            "6": {
                "witnesses": 3_103,
                "balance_one_half": 3_067,
                "cyclic_part_has_comparable_pair": 118,
            },
            "7": {
                "witnesses": 28,
                "balance_one_half": 28,
                "cyclic_part_has_comparable_pair": 0,
            },
            "8": {
                "witnesses": 13,
                "balance_one_half": 13,
                "cyclic_part_has_comparable_pair": 0,
            },
        },
    },
    "tail": {
        "records": 180,
        "distinct_witnesses": 180,
        "distinct_values": 42,
        "no_pair_certificate_all_witnesses": 64,
        "no_pair_certificate_one_per_value": 21,
        "widths": [2, 3],
        "witnesses_with_majority_cycle": 0,
        "L14_1_9_certificate": "triple",
    },
    "equality": {
        "representatives": 68,
        "widths": [2],
    },
}


def check_expected(actual: dict, expected: dict, path: str = "") -> None:
    for key, wanted in expected.items():
        name = f"{path}.{key}" if path else key
        if key not in actual:
            raise SystemExit(f"missing result: {name}")
        if isinstance(wanted, dict):
            check_expected(actual[key], wanted, name)
        elif actual[key] != wanted:
            raise SystemExit(
                f"{name}: recomputed {actual[key]!r}, paper expects {wanted!r}"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument(
        "--jobs", type=int, default=min(8, os.cpu_count() or 1),
        help="worker processes (default: up to 8)",
    )
    parser.add_argument("--output", type=Path, help="write JSON to this path")
    parser.add_argument(
        "--check-paper", action="store_true",
        help="fail unless every statistic reported by the paper matches",
    )
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be positive")

    result = summarize(args.archive, args.jobs)
    if args.check_paper:
        check_expected(result, EXPECTED)
        result["paper_check"] = "PASS"
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered)
    else:
        sys.stdout.write(rendered)


if __name__ == "__main__":
    main()
