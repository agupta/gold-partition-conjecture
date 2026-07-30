#!/usr/bin/env python3
"""Independent small-order reference for the balance/majority census.

This program neither calls nor translates `src/balance_census.c`.  It reads
digraph6 Hasse diagrams on standard input, enumerates the linear extensions of
each poset one at a time, and counts precedences directly.  It performs **no**
ordinal-sum decomposition and **no** ideal-lattice dynamic programming, so it
shares no algorithm with the census beyond the definitions themselves.

Each output line is

    n chain connected num den cycles_full cycles_inc

matching `tests/census_driver.c` byte for byte.  `num/den` is the reduced
balance constant, `0/1` for a chain.  The two cycle fields are four-digit
hexadecimal masks whose bit L is set exactly when the majority digraph has a
simple cycle on L vertices; `cycles_full` uses the relation of De Loof, De
Baets, and De Meyer over all ordered pairs, and `cycles_inc` its restriction to
incomparable pairs.
"""

from __future__ import annotations

from math import gcd
import sys


def bits(mask: int):
    while mask:
        low = mask & -mask
        yield low.bit_length() - 1
        mask ^= low


def read_digraph6(line: str) -> list[int] | None:
    """Decode one digraph6 record into adjacency masks."""
    if not line.startswith("&"):
        return None
    data = [ord(character) - 63 for character in line.rstrip("\n")[1:]]
    n = data[0]
    if not 1 <= n <= 15:
        raise SystemExit(f"unsupported digraph6 order {n}")
    stream: list[int] = []
    for value in data[1:]:
        if not 0 <= value <= 63:
            raise SystemExit("truncated digraph6 record")
        stream.extend((value >> shift) & 1 for shift in range(5, -1, -1))
    if len(stream) < n * n:
        raise SystemExit("truncated digraph6 record")
    adjacency = [0] * n
    for x in range(n):
        for y in range(n):
            if stream[x * n + y]:
                adjacency[x] |= 1 << y
    return adjacency


def transitive_closure(adjacency: list[int]) -> list[int]:
    n = len(adjacency)
    up = list(adjacency)
    for k in range(n):
        for x in range(n):
            if (up[x] >> k) & 1:
                up[x] |= up[k]
    return up


def linear_extensions(up: list[int]):
    """Yield every linear extension as a tuple of elements, low to high."""
    n = len(up)
    down = [0] * n
    for x in range(n):
        for y in bits(up[x]):
            down[y] |= 1 << x
    full = (1 << n) - 1
    order: list[int] = []

    def extend(used: int):
        if used == full:
            yield tuple(order)
            return
        for x in bits(full & ~used):
            if down[x] & ~used:
                continue
            order.append(x)
            yield from extend(used | (1 << x))
            order.pop()

    yield from extend(0)


def precedence_matrix(up: list[int]) -> tuple[int, list[list[int]]]:
    n = len(up)
    before = [[0] * n for _ in range(n)]
    total = 0
    for order in linear_extensions(up):
        total += 1
        for index, x in enumerate(order):
            row = before[x]
            for y in order[index + 1:]:
                row[y] += 1
    return total, before


def incomparability_components(up: list[int]) -> int:
    n = len(up)
    down = [0] * n
    for x in range(n):
        for y in bits(up[x]):
            down[y] |= 1 << x
    full = (1 << n) - 1
    unseen = full
    count = 0
    while unseen:
        root = (unseen & -unseen).bit_length() - 1
        frontier = 1 << root
        unseen &= ~frontier
        while frontier:
            x = (frontier & -frontier).bit_length() - 1
            frontier &= frontier - 1
            addition = (full & ~(up[x] | down[x] | (1 << x))) & unseen
            unseen &= ~addition
            frontier |= addition
        count += 1
    return count


def cycle_mask(adjacency: list[int]) -> int:
    """Bit L set exactly when a simple cycle on L vertices exists.

    Deliberately naive: every simple path from every start vertex, with no
    strongly-connected-component pruning.
    """
    n = len(adjacency)
    found = 0

    def walk(start: int, current: int, used: int, depth: int) -> None:
        nonlocal found
        if depth >= 3 and (adjacency[current] >> start) & 1:
            found |= 1 << depth
        allowed = adjacency[current] & ~used & ~((1 << start) - 1)
        for nxt in bits(allowed):
            walk(start, nxt, used | (1 << nxt), depth + 1)

    for start in range(n):
        walk(start, start, 1 << start, 1)
    return found


def analyze(hasse: list[int]) -> str:
    up = transitive_closure(hasse)
    n = len(up)
    components = incomparability_components(up)
    connected = 1 if components == 1 else 0
    if components == n:
        return f"{n} 1 {connected} 0 1 0000 0000"

    total, before = precedence_matrix(up)
    best = 0
    for x in range(n):
        for y in range(x + 1, n):
            if ((up[x] >> y) & 1) or ((up[y] >> x) & 1):
                continue
            best = max(best, min(before[x][y], before[y][x]))
    divisor = gcd(best, total)

    full_adjacency = [0] * n
    inc_adjacency = [0] * n
    for x in range(n):
        for y in range(n):
            if x == y or 2 * before[x][y] <= total:
                continue
            full_adjacency[x] |= 1 << y
            if not (((up[x] >> y) & 1) or ((up[y] >> x) & 1)):
                inc_adjacency[x] |= 1 << y

    return (
        f"{n} 0 {connected} {best // divisor} {total // divisor} "
        f"{cycle_mask(full_adjacency):04x} {cycle_mask(inc_adjacency):04x}"
    )


def main() -> None:
    for line in sys.stdin:
        hasse = read_digraph6(line)
        if hasse is None:
            continue
        print(analyze(hasse))


if __name__ == "__main__":
    main()
