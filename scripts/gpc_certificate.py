#!/usr/bin/env python3
"""Which Gold Partition certificate resolves a given poset?

`src/gpc.c` counts certificates but does not retain the posets it assigns
them to, and `src/balance_census.c` retains extremal witnesses but knows
nothing about certificates.  This module joins the two: given a witness string
from the census, it reports which of Peczarski's conditions resolves that
poset, so the extremal objects of the census can be located inside the
certificate partition of the Gold Partition run.

The conditions are Peczarski's Definitions 1--2 and Lemmas 1--2, together with
the half-balanced pair.  The cascade order matches the production verifier:
the bilateral screen, a low-slave pair, a half-balanced pair, then a balanced
triple.  The reported split is pair-first: ``pair`` means that at least one
pair certificate exists; ``triple`` means that no pair certificate exists and
a balanced-triple certificate does.  Ordering among the pair screens changes
only their unpublished sub-buckets.

Nothing here is translated from `src/gpc.c`.  Extension counts come from the
ideal-lattice routines of `census_witness.py`; the certificate tests are
written directly from the published definitions.  `--self-test` runs two
checks: a differential one against `tests/reference_gpc.py`, which enumerates
linear extensions explicitly and compares the pair/triple class of every small
poset, and an external one against Peczarski's published Table I.

Usage:
    gpc_certificate.py WITNESS [WITNESS ...]
    gpc_certificate.py --self-test [ORDER]   (default 8)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import census_witness as cw  # noqa: E402


PAIR = ("bilateral", "low-slave", "half-balanced")


def slave_count(up: tuple[int, ...], down: list[int], x: int, y: int) -> int:
    """Peczarski's slaves of the ordered incomparable pair `(x, y)`.

    `z` is a slave when `z > x` and `z` is incomparable to `y`, or when
    `z < y` and `z` is incomparable to `x`.
    """
    full = (1 << len(up)) - 1
    free_y = full & ~(up[y] | down[y] | (1 << y))
    free_x = full & ~(up[x] | down[x] | (1 << x))
    return (up[x] & free_y).bit_count() + (down[y] & free_x).bit_count()


def _count_chain(analysis: cw.Analysis, x: int, y: int, z: int) -> int:
    """Extensions with `x` before `y` before `z`, i.e. `e(P + xy + yz)`.

    One constrained pass over the ideal lattice: reject any prefix that admits
    `y` without `x`, or `z` without `y`.
    """
    counts = [0] * (analysis.full + 1)
    counts[0] = 1
    mx, my, mz = 1 << x, 1 << y, 1 << z
    for ideal in analysis.ideals:
        running = counts[ideal]
        if not running:
            continue
        for v in cw.bits(analysis.full & ~ideal):
            if analysis.down[v] & ~ideal:
                continue
            nxt = ideal | (1 << v)
            if (nxt & my) and not (nxt & mx):
                continue
            if (nxt & mz) and not (nxt & my):
                continue
            counts[nxt] += running
    return counts[analysis.full]


def classify(up: tuple[int, ...]) -> str:
    """One of `bilateral`, `low-slave`, `half-balanced`, `triple`, `chain`,
    or `open`.  Everything but `triple`, `chain`, and `open` is a pair
    certificate."""
    analysis = cw.Analysis(up)
    total, n = analysis.extensions, analysis.n
    down = analysis.down
    incomparable = list(analysis.incomparable_pairs())
    if not incomparable:
        return "chain"

    for x, y in incomparable:
        if slave_count(up, down, x, y) <= 1 and slave_count(up, down, y, x) <= 1:
            return "bilateral"

    for x, y in incomparable:
        for a, b in ((x, y), (y, x)):
            if (slave_count(up, down, a, b) <= 1
                    and 2 * analysis.precedence[(a, b)] >= total):
                return "low-slave"

    for x, y in incomparable:
        if 2 * analysis.precedence[(x, y)] == total:
            return "half-balanced"

    for x in range(n):
        for y in range(n):
            if y == x:
                continue
            yx = analysis.precedence[(y, x)]
            if 2 * yx > total:
                continue
            for z in range(n):
                if z == x or z == y:
                    continue
                bound = max(yx, analysis.precedence[(z, y)])
                if 2 * bound > total:
                    continue
                if _count_chain(analysis, x, y, z) <= bound:
                    return "triple"
    return "open"


def is_pair(kind: str) -> bool:
    return kind in PAIR


def coarse_kind(kind: str) -> str:
    """The order-independent class reported by the paper."""
    return "pair" if is_pair(kind) else kind


# M. Peczarski, "The Gold Partition Conjecture", Order 23 (2006), Table I.
# The universe is the non-chain, ordinal-indecomposable classes with dual pairs
# identified.  Columns are |B_n|, Lemma 2, half-balanced, Lemma 3, Lemma 1; the
# pair certificate is the first two and the balanced triple the last two.
PECZARSKI_TABLE_I = {
    4: (6, 6, 0, 0, 0),
    5: (21, 19, 0, 0, 2),
    6: (111, 103, 2, 0, 6),
    7: (725, 702, 2, 0, 21),
    8: (6474, 6293, 29, 0, 152),
}


def peczarski_universe(posets: list) -> list:
    """Non-chain, ordinal-indecomposable, one representative per dual pair."""
    seen, universe = set(), []
    for up in posets:
        if not list(cw.Analysis(up).incomparable_pairs()):
            continue
        if len(cw.ordinal_summands(up)) > 1:
            continue
        n = len(up)
        down = [0] * n
        for x in range(n):
            for y in cw.bits(up[x]):
                down[y] |= 1 << x
        tag = min(cw.canonical(up), cw.canonical(tuple(down)))
        if tag in seen:
            continue
        seen.add(tag)
        universe.append(up)
    return universe


def self_test(order: int = 8) -> int:
    """Two checks, because agreeing on *whether* a certificate exists is not
    enough: a classify() that always returned `bilateral` would pass that and
    still be useless, since every reported statistic turns on the pair/triple
    boundary.

    1. Differential, against `tests/reference_gpc.py`, which enumerates linear
       extensions explicitly: same chain/pair/triple/open class on every
       unlabeled poset up to `order`.
    2. External, against Peczarski's published Table I: same class count and
       same pair/triple split on his universe, which is the only published
       data that constrains the boundary itself.
    """
    root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root))
    from tests import reference_gpc as reference

    posets = reference.generate_posets(order)
    checked = disagreed = 0
    for n in sorted(posets):
        if n < 2:
            continue
        for up in posets[n]:
            kind = classify(up)
            reference_kind = reference.certificate_kind(up)
            if coarse_kind(kind) != reference_kind:
                disagreed += 1
                print(f"disagree at order {n}: {cw.encode(up)} "
                      f"fast={kind} reference={reference_kind}")
            checked += 1
        print(f"order {n}: {len(posets[n])} posets checked")
    print(f"differential: {checked} posets, {disagreed} disagreements")

    failed = disagreed
    for n, (size, lemma2, half, lemma3, lemma1) in sorted(
            PECZARSKI_TABLE_I.items()):
        if n > order:
            continue
        universe = peczarski_universe(posets[n])
        pair = sum(1 for up in universe if is_pair(classify(up)))
        triple = len(universe) - pair
        want_pair, want_triple = lemma2 + half, lemma3 + lemma1
        ok = (len(universe) == size and pair == want_pair
              and triple == want_triple)
        failed += not ok
        print(f"Table I n={n}: classes {len(universe)}/{size}, "
              f"pair {pair}/{want_pair}, triple {triple}/{want_triple}"
              f"  {'ok' if ok else 'MISMATCH'}")
    return 1 if failed else 0


def main() -> None:
    args = sys.argv[1:]
    if not args:
        raise SystemExit(__doc__)
    if args[0] == "--self-test":
        raise SystemExit(self_test(int(args[1]) if len(args) > 1 else 8))
    for witness in args:
        up = cw.decode(witness)
        analysis = cw.Analysis(up)
        print(f"{witness}\n  balance {analysis.balance()}  "
              f"width {cw.width(up)}  extensions {analysis.extensions:,}  "
              f"certificate {classify(up)}")


if __name__ == "__main__":
    main()
