#!/usr/bin/env python3
"""Independent small-order check of the Gold Partition certificates.

This program neither calls nor translates the C implementation.  It generates
unlabeled posets by adjoining a maximal element over every order ideal, removes
isomorphic duplicates by canonical relabeling, enumerates linear extensions,
and tests the three sufficient conditions in Peczarski's formulation.
"""

from __future__ import annotations

from itertools import permutations
import sys


A000112 = {1: 1, 2: 2, 3: 5, 4: 16, 5: 63, 6: 318, 7: 2_045}


def bits(mask: int):
    while mask:
        bit = mask & -mask
        yield bit.bit_length() - 1
        mask ^= bit


def downsets_from_up(up: tuple[int, ...]) -> list[int]:
    down = [0] * len(up)
    for x, above in enumerate(up):
        for y in bits(above):
            down[y] |= 1 << x
    return down


def invariant_colors(up: tuple[int, ...]) -> list[int]:
    down = downsets_from_up(up)
    keys = [(up[x].bit_count(), down[x].bit_count()) for x in range(len(up))]
    while True:
        distinct = {key: rank for rank, key in enumerate(sorted(set(keys)))}
        colors = [distinct[key] for key in keys]
        refined = [
            (
                colors[x],
                tuple(sorted(colors[y] for y in bits(up[x]))),
                tuple(sorted(colors[y] for y in bits(down[x]))),
            )
            for x in range(len(up))
        ]
        if refined == keys:
            return colors
        keys = refined


def canonical(up: tuple[int, ...]) -> tuple[int, ...]:
    n = len(up)
    colors = invariant_colors(up)
    blocks: dict[int, list[int]] = {}
    for vertex, color in enumerate(colors):
        blocks.setdefault(color, []).append(vertex)
    ordered_blocks = [blocks[color] for color in sorted(blocks)]
    relabel = [0] * n
    best: tuple[int, ...] | None = None

    def search(block_index: int, next_label: int) -> None:
        nonlocal best
        if block_index == len(ordered_blocks):
            candidate = [0] * n
            for x in range(n):
                candidate[relabel[x]] = sum(
                    1 << relabel[y] for y in bits(up[x])
                )
            encoded = tuple(candidate)
            if best is None or encoded < best:
                best = encoded
            return
        block = ordered_blocks[block_index]
        for ordering in permutations(block):
            for offset, vertex in enumerate(ordering):
                relabel[vertex] = next_label + offset
            search(block_index + 1, next_label + len(block))

    search(0, 0)
    assert best is not None
    return best


def order_ideals(up: tuple[int, ...]) -> list[int]:
    down = downsets_from_up(up)
    return [
        subset
        for subset in range(1 << len(up))
        if all(not (down[x] & ~subset) for x in bits(subset))
    ]


def generate_posets(maximum_order: int) -> dict[int, list[tuple[int, ...]]]:
    result = {1: [(0,)]}
    for n in range(2, maximum_order + 1):
        seen: set[tuple[int, ...]] = set()
        for smaller in result[n - 1]:
            for ideal in order_ideals(smaller):
                extended = list(smaller) + [0]
                for x in bits(ideal):
                    extended[x] |= 1 << (n - 1)
                seen.add(canonical(tuple(extended)))
        result[n] = sorted(seen)
        if len(result[n]) != A000112[n]:
            raise AssertionError(
                f"order {n}: generated {len(result[n])}, "
                f"expected {A000112[n]}"
            )
    return result


def linear_extensions(up: tuple[int, ...]) -> list[tuple[int, ...]]:
    n = len(up)
    down = downsets_from_up(up)
    extensions: list[tuple[int, ...]] = []

    def visit(prefix: tuple[int, ...], used: int) -> None:
        if len(prefix) == n:
            extensions.append(prefix)
            return
        for x in range(n):
            if not (used >> x) & 1 and not (down[x] & ~used):
                visit(prefix + (x,), used | (1 << x))

    visit((), 0)
    return extensions


def slave_count(
    up: tuple[int, ...], down: list[int], x: int, y: int
) -> int:
    n = len(up)
    full = (1 << n) - 1
    incomparable_y = full & ~(up[y] | down[y] | (1 << y))
    incomparable_x = full & ~(up[x] | down[x] | (1 << x))
    return (up[x] & incomparable_y).bit_count() + (
        down[y] & incomparable_x
    ).bit_count()


def has_certificate(up: tuple[int, ...]) -> bool:
    n = len(up)
    down = downsets_from_up(up)
    incomparable = [
        (x, y)
        for x in range(n)
        for y in range(x + 1, n)
        if not ((up[x] >> y) & 1) and not ((up[y] >> x) & 1)
    ]
    if not incomparable:
        return True

    for x, y in incomparable:
        if (
            slave_count(up, down, x, y) <= 1
            and slave_count(up, down, y, x) <= 1
        ):
            return True

    extensions = linear_extensions(up)
    positions = [
        {vertex: index for index, vertex in enumerate(extension)}
        for extension in extensions
    ]
    total = len(extensions)

    def before(x: int, y: int) -> int:
        return sum(position[x] < position[y] for position in positions)

    for x, y in incomparable:
        xy = before(x, y)
        if 2 * xy == total:
            return True
        if 2 * xy >= total and slave_count(up, down, x, y) <= 1:
            return True
        if 2 * (total - xy) >= total and slave_count(up, down, y, x) <= 1:
            return True

    for x in range(n):
        for y in range(n):
            if y == x:
                continue
            yx = before(y, x)
            if 2 * yx > total:
                continue
            for z in range(n):
                if z == x or z == y:
                    continue
                zy = before(z, y)
                bound = max(yx, zy)
                if 2 * bound > total:
                    continue
                xyz = sum(
                    position[x] < position[y] < position[z]
                    for position in positions
                )
                if xyz <= bound:
                    return True
    return False


def main() -> None:
    maximum_order = int(sys.argv[1]) if len(sys.argv) == 2 else 7
    if maximum_order not in A000112:
        raise SystemExit("maximum order must lie between 1 and 7")
    posets = generate_posets(maximum_order)
    for n in range(1, maximum_order + 1):
        chains = 0
        open_classes = 0
        for up in posets[n]:
            incomparable = sum(
                not ((up[x] >> y) & 1) and not ((up[y] >> x) & 1)
                for x in range(n)
                for y in range(x + 1, n)
            )
            chains += incomparable == 0
            open_classes += not has_certificate(up)
        if chains != 1 or open_classes:
            raise SystemExit(
                f"order {n}: chains={chains}, open={open_classes}"
            )
        print(
            f"REFERENCE n={n} total={len(posets[n])} "
            f"chain={chains} open={open_classes}"
        )
    print("PASS: independent small-order certificate check")


if __name__ == "__main__":
    main()
