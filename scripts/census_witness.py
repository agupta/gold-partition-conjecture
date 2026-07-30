#!/usr/bin/env python3
"""Independent exact recomputation of balance-census witnesses.

Nothing here translates or calls `src/balance_census.c`.  The census computes
pair probabilities from one forward and one backward pass over the ideal
lattice, multiplying prefix and suffix counts at each transition.  This module
instead counts, separately for every ordered pair, the linear extensions of the
poset with that pair's relation adjoined, by a plain forward recurrence over
order ideals.  Agreement between the two is a real check, not a tautology.

All arithmetic uses Python integers and `fractions.Fraction`.  No
floating-point value is ever compared.

A poset is represented as a tuple `up` of bitmasks: bit `y` of `up[x]` is set
exactly when `x < y` in the strict transitive closure.
"""

from __future__ import annotations

from fractions import Fraction
from itertools import permutations
import re


WITNESS_PATTERN = re.compile(r"^([0-9]{1,2}):((?:[0-9a-f]{4})*)$")
MAX_ORDER = 15


class WitnessError(ValueError):
    """A witness string is malformed or does not encode a poset."""


def bits(mask: int):
    while mask:
        low = mask & -mask
        yield low.bit_length() - 1
        mask ^= low


def decode(text: str) -> tuple[int, ...]:
    """Decode `n:xxxx...` into the tuple of strict upper-set masks."""
    match = WITNESS_PATTERN.match(text)
    if not match:
        raise WitnessError(f"malformed witness: {text!r}")
    n = int(match.group(1))
    digits = match.group(2)
    if not 1 <= n <= MAX_ORDER:
        raise WitnessError(f"witness order {n} out of range")
    if len(digits) != 4 * n:
        raise WitnessError(f"witness declares {n} elements, carries "
                           f"{len(digits) // 4}")
    up = tuple(int(digits[4 * x:4 * x + 4], 16) for x in range(n))
    validate_order(up)
    return up


def encode(up: tuple[int, ...]) -> str:
    return f"{len(up)}:" + "".join(f"{mask:04x}" for mask in up)


def validate_order(up: tuple[int, ...]) -> None:
    """Check that `up` is the strict transitive closure of a partial order."""
    n = len(up)
    full = (1 << n) - 1
    for x in range(n):
        if up[x] & ~full:
            raise WitnessError(f"element {x} refers outside the ground set")
        if (up[x] >> x) & 1:
            raise WitnessError(f"element {x} is below itself")
        for y in bits(up[x]):
            if (up[y] >> x) & 1:
                raise WitnessError(f"elements {x} and {y} are mutually below")
            if up[y] & ~up[x]:
                raise WitnessError(f"relation is not transitively closed "
                                   f"at {x} < {y}")


def downsets(up: tuple[int, ...]) -> list[int]:
    down = [0] * len(up)
    for x, above in enumerate(up):
        for y in bits(above):
            down[y] |= 1 << x
    return down


def order_ideals(up: tuple[int, ...]) -> list[int]:
    """Every down-closed subset, listed in increasing mask order."""
    n = len(up)
    down = downsets(up)
    return [
        subset
        for subset in range(1 << n)
        if all(down[x] & ~subset == 0 for x in bits(subset))
    ]


def _count(
    ideals: list[int], down: list[int], full: int,
    forbidden: int = 0, required: int = 0,
) -> int:
    """Linear extensions, optionally forbidding every prefix that contains
    `forbidden` without containing `required`.

    With `forbidden = 1 << y` and `required = 1 << x` this counts exactly the
    extensions in which `x` precedes `y`: an extension places `x` before `y`
    precisely when no prefix admits `y` first.

    Ideals are visited in increasing mask order, and every ideal is a strict
    subset of its successors, so each count is complete when it is read.
    """
    counts = [0] * (full + 1)
    counts[0] = 1
    for ideal in ideals:
        running = counts[ideal]
        if not running:
            continue
        for x in bits(full & ~ideal):
            if down[x] & ~ideal:
                continue
            larger = ideal | (1 << x)
            if (larger & forbidden) and not (larger & required):
                continue
            counts[larger] += running
    return counts[full]


class Analysis:
    """Exact linear-extension statistics of one poset."""

    def __init__(self, up: tuple[int, ...]) -> None:
        self.up = up
        self.n = len(up)
        self.down = downsets(up)
        self.full = (1 << self.n) - 1
        self.ideals = order_ideals(up)
        self.extensions = _count(self.ideals, self.down, self.full)
        if self.extensions <= 0:
            raise WitnessError("poset has no linear extension")

        self.precedence: dict[tuple[int, int], int] = {}
        for x in range(self.n):
            for y in range(x + 1, self.n):
                if (up[x] >> y) & 1:
                    forward = self.extensions
                elif (up[y] >> x) & 1:
                    forward = 0
                else:
                    forward = _count(
                        self.ideals, self.down, self.full, 1 << y, 1 << x
                    )
                self.precedence[(x, y)] = forward
                self.precedence[(y, x)] = self.extensions - forward

    def incomparable_pairs(self):
        for x in range(self.n):
            for y in range(x + 1, self.n):
                if not (((self.up[x] >> y) & 1) or ((self.up[y] >> x) & 1)):
                    yield x, y

    def balance(self) -> Fraction | None:
        """The balance constant, or None when the poset is a chain."""
        best: Fraction | None = None
        for x, y in self.incomparable_pairs():
            forward = self.precedence[(x, y)]
            value = Fraction(
                min(forward, self.extensions - forward), self.extensions
            )
            if best is None or value > best:
                best = value
        return best

    def majority_digraph(self, full_relation: bool) -> list[int]:
        """Strict linear-extension-majority digraph.

        With `full_relation` the relation is that of De Loof, De Baets, and
        De Meyer: every ordered pair whose probability exceeds one half,
        comparable pairs included.  Otherwise only incomparable pairs
        contribute.
        """
        adjacency = [0] * self.n
        for x in range(self.n):
            for y in range(self.n):
                if x == y:
                    continue
                comparable = ((self.up[x] >> y) & 1) or ((self.up[y] >> x) & 1)
                if comparable and not full_relation:
                    continue
                if 2 * self.precedence[(x, y)] > self.extensions:
                    adjacency[x] |= 1 << y
        return adjacency


def extensions(up: tuple[int, ...]) -> int:
    return Analysis(up).extensions


def balance(up: tuple[int, ...]) -> Fraction | None:
    return Analysis(up).balance()


def cycle_lengths(adjacency: list[int]) -> set[int]:
    """Lengths of all simple directed cycles, by exhaustive path search.

    The search is confined to strongly connected components, and each cycle is
    found from its least vertex, so every cycle is reached exactly once.
    """
    n = len(adjacency)
    reach = list(adjacency)
    for k in range(n):
        for x in range(n):
            if (reach[x] >> k) & 1:
                reach[x] |= reach[k]
    on_cycle = sum(1 << x for x in range(n) if (reach[x] >> x) & 1)

    found: set[int] = set()
    remaining = on_cycle
    while remaining:
        root = (remaining & -remaining).bit_length() - 1
        component = 1 << root
        for y in bits(reach[root] & on_cycle):
            if (reach[y] >> root) & 1:
                component |= 1 << y
        remaining &= ~component
        if bin(component).count("1") < 3:
            continue

        for start in bits(component):
            allowed = component & ~((1 << start) - 1)

            def walk(current: int, used: int, depth: int) -> None:
                if depth >= 3 and (adjacency[current] >> start) & 1:
                    found.add(depth)
                for nxt in bits(adjacency[current] & allowed & ~used):
                    walk(nxt, used | (1 << nxt), depth + 1)

            walk(start, 1 << start, 1)
    return found


def brute_force_balance(up: tuple[int, ...]) -> Fraction | None:
    """Balance constant by enumerating every linear extension.

    Exponential; used only to check `balance` on small witnesses.
    """
    n = len(up)
    down = downsets(up)
    before = [[0] * n for _ in range(n)]
    total = 0
    for order in permutations(range(n)):
        position = [0] * n
        for index, element in enumerate(order):
            position[element] = index
        if not all(position[x] < position[y]
                   for y in range(n) for x in bits(down[y])):
            continue
        total += 1
        for x in range(n):
            for y in range(n):
                if position[x] < position[y]:
                    before[x][y] += 1
    best: Fraction | None = None
    for x in range(n):
        for y in range(x + 1, n):
            if ((up[x] >> y) & 1) or ((up[y] >> x) & 1):
                continue
            value = Fraction(min(before[x][y], before[y][x]), total)
            if best is None or value > best:
                best = value
    return best


def ordinal_summands(up: tuple[int, ...]) -> list[int]:
    """Vertex masks of the finest ordinal-sum decomposition, in order.

    These are the connected components of the incomparability graph.
    """
    n = len(up)
    down = downsets(up)
    full = (1 << n) - 1
    unseen = full
    components = []
    while unseen:
        root = (unseen & -unseen).bit_length() - 1
        component = 0
        frontier = 1 << root
        unseen &= ~frontier
        while frontier:
            x = (frontier & -frontier).bit_length() - 1
            frontier &= frontier - 1
            component |= 1 << x
            incomparable = full & ~(up[x] | down[x] | (1 << x))
            addition = incomparable & unseen
            unseen &= ~addition
            frontier |= addition
        components.append(component)
    # Order the summands by the ordinal order: a summand is below another
    # exactly when one of its elements is below one of theirs.
    def rank(component: int) -> int:
        x = (component & -component).bit_length() - 1
        return bin(down[x] | component).count("1")
    components.sort(key=rank)
    return components


def induced(up: tuple[int, ...], vertices: int) -> tuple[int, ...]:
    labels = list(bits(vertices))
    index = {label: position for position, label in enumerate(labels)}
    return tuple(
        sum(1 << index[y] for y in bits(up[x]) if (vertices >> y) & 1)
        for x in labels
    )


def is_equality_family(up: tuple[int, ...]) -> bool:
    """Recognize an ordinal sum of singletons and copies of T.

    T is the three-element poset consisting of a two-element chain and an
    isolated element.  At least one copy of T must occur, which excludes the
    chain.  The recognizer is structural: it never computes a probability.
    """
    saw_t = False
    for component in ordinal_summands(up):
        size = bin(component).count("1")
        if size == 1:
            continue
        if size != 3:
            return False
        block = induced(up, component)
        relations = sum(bin(mask).count("1") for mask in block)
        if relations != 1:
            return False
        saw_t = True
    return saw_t


def equality_family_count(n: int) -> int:
    """Number of non-chain ordinal sums of singletons and copies of T.

    Ordinal-sum decomposition into indecomposable summands is unique, so these
    posets correspond bijectively to compositions of n into parts 1 and 3.
    Splitting on the first part gives c(n) = c(n-1) + c(n-3) with
    c(0) = c(1) = c(2) = 1.  Removing the all-singleton chain leaves c(n) - 1.
    """
    c = [1, 1, 1]
    for order in range(3, n + 1):
        c.append(c[order - 1] + c[order - 3])
    return c[n] - 1


def width(up: tuple[int, ...]) -> int:
    """Size of a largest antichain.

    Peczarski's search above order 11 was restricted to width two, so the
    width of the extremal posets says how far the census reaches beyond the
    region he could enumerate.
    """
    n = len(up)
    best = 0
    for subset in range(1 << n):
        size = bin(subset).count("1")
        if size <= best:
            continue
        if all(up[x] & subset == 0 for x in bits(subset)):
            best = size
    return best


def height(up: tuple[int, ...]) -> int:
    """Number of elements in a longest chain."""
    n = len(up)
    down = downsets(up)
    longest = [0] * n
    for x in sorted(range(n), key=lambda v: bin(down[v]).count("1")):
        longest[x] = 1 + max((longest[y] for y in bits(down[x])), default=0)
    return max(longest, default=0)


def broken_rung_ladder(n: int, broken: tuple[int, ...] = ()) -> tuple[int, ...]:
    """Peczarski's ladder `L_n` with the listed rungs removed.

    From "The worst balanced partially ordered sets - ladders with broken
    rungs", Experimental Mathematics 28 (2019), section 1: on the ground set
    `x_0, ..., x_{n-1}`, take `x_i < x_{i+2}` for every `i`, add the rungs
    `x_i < x_{i+3}` for every `i` not listed in `broken`, and close
    transitively.
    """
    up = [0] * n
    for i in range(n - 2):
        up[i] |= 1 << (i + 2)
    for i in range(n - 3):
        if i not in broken:
            up[i] |= 1 << (i + 3)
    for k in range(n):
        for x in range(n):
            if (up[x] >> k) & 1:
                up[x] |= up[k]
    return tuple(up)


def worst_broken_rung_ladder(n: int):
    """The least balance constant over every ladder with broken rungs.

    Returns `(value, broken, up)`.  Ladders that decompose as a nontrivial
    ordinal sum are skipped, matching Peczarski's restriction to posets that
    are not linear sums.
    """
    from itertools import combinations

    best = None
    rungs = range(max(0, n - 3))
    for size in range(len(rungs) + 1):
        for broken in combinations(rungs, size):
            up = broken_rung_ladder(n, broken)
            if len(ordinal_summands(up)) != 1:
                continue
            value = Analysis(up).balance()
            if value is not None and (best is None or value < best[0]):
                best = (value, broken, up)
    return best


def hasse(up: tuple[int, ...]) -> list[int]:
    """Covering relation of the closure."""
    n = len(up)
    covers = []
    for x in range(n):
        mask = up[x]
        for y in bits(up[x]):
            mask &= ~up[y]
        covers.append(mask)
    return covers


def digraph6(adjacency: list[int]) -> str:
    """digraph6 encoding, matching the format genposetg writes."""
    n = len(adjacency)
    stream = []
    for x in range(n):
        for y in range(n):
            stream.append((adjacency[x] >> y) & 1)
    while len(stream) % 6:
        stream.append(0)
    body = "".join(
        chr(63 + sum(bit << (5 - index)
                     for index, bit in enumerate(stream[position:position + 6])))
        for position in range(0, len(stream), 6)
    )
    return "&" + chr(63 + n) + body


def refine_colors(up: tuple[int, ...]) -> list[int]:
    down = downsets(up)
    n = len(up)
    keys = [(bin(up[x]).count("1"), bin(down[x]).count("1")) for x in range(n)]
    while True:
        ranks = {key: rank for rank, key in enumerate(sorted(set(keys)))}
        colors = [ranks[key] for key in keys]
        refined = [
            (
                colors[x],
                tuple(sorted(colors[y] for y in bits(up[x]))),
                tuple(sorted(colors[y] for y in bits(down[x]))),
            )
            for x in range(n)
        ]
        if refined == keys:
            return colors
        keys = refined


def canonical(up: tuple[int, ...], budget: int = 200_000
              ) -> tuple[int, ...] | None:
    """Lexicographically least relabeling, or None if the search is too wide.

    Colour refinement partitions the ground set; only relabelings that respect
    the partition can be least, so the search runs over the product of the
    blocks' permutations.
    """
    n = len(up)
    colors = refine_colors(up)
    blocks: dict[int, list[int]] = {}
    for vertex, color in enumerate(colors):
        blocks.setdefault(color, []).append(vertex)
    ordered = [blocks[color] for color in sorted(blocks)]

    width = 1
    for block in ordered:
        for size in range(2, len(block) + 1):
            width *= size
        if width > budget:
            return None

    best: tuple[int, ...] | None = None
    for choice in _block_permutations(ordered):
        relabel = [0] * n
        for label, vertex in enumerate(choice):
            relabel[vertex] = label
        image = [0] * n
        for x in range(n):
            image[relabel[x]] = sum(1 << relabel[y] for y in bits(up[x]))
        candidate = tuple(image)
        if best is None or candidate < best:
            best = candidate
    return best


def _block_permutations(blocks: list[list[int]]):
    if not blocks:
        yield []
        return
    head, *rest = blocks
    for arrangement in permutations(head):
        for tail in _block_permutations(rest):
            yield list(arrangement) + tail
