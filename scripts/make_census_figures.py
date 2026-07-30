#!/usr/bin/env python3
"""Generate the figures for the order-14 census paper.

Every figure is derived from a witness string, never hand-drawn, so a figure
cannot drift from the poset it claims to depict.  Each witness is re-verified
with `census_witness.py` before it is drawn: if the poset does not have the
property the caption asserts, this script fails rather than emitting a picture.

Usage:
    make_census_figures.py OUTDIR --tail FILE --tail-order N

The featured length-8 witness is fixed because the prose and caption assert
properties specific to that poset.  `--tail` reads a tail table in the
aggregate report's format and is required for the tail figure: there is no
built-in fallback, because a hard-coded table silently goes stale.
`--tail-order` labels the tail figure with the order represented by that table.
"""

from __future__ import annotations

import argparse
import math
import re
import sys
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import census_witness as cw  # noqa: E402


# A verified order-14 poset whose majority digraph contains an 8-cycle and no
# odd cycle at all.  Recorded by the census; re-verified below on every run.
WITNESS_8 = "14:0000000000000003000500030005000300050002000401ff043f03c7"

# Peczarski's conjectured gap.  A decimal printed in his paper for a
# conjectured limit, not an exact rational threshold.
GAP_END = Fraction(348_843, 1_000_000)



def cyclic_part(adjacency: list[int]) -> list[int]:
    """Vertices lying on at least one directed cycle."""
    n = len(adjacency)
    reach = list(adjacency)
    for k in range(n):
        for x in range(n):
            if (reach[x] >> k) & 1:
                reach[x] |= reach[k]
    return [x for x in range(n) if (reach[x] >> x) & 1]


def bipartition(adjacency: list[int], vertices: list[int]) -> dict[int, int] | None:
    """Two-colour the cyclic part, or None if an odd closed walk exists."""
    members = set(vertices)
    colour: dict[int, int] = {}
    for seed in sorted(members):
        if seed in colour:
            continue
        colour[seed] = 0
        stack = [seed]
        while stack:
            u = stack.pop()
            neighbours = [v for v in cw.bits(adjacency[u]) if v in members]
            neighbours += [v for v in members if (adjacency[v] >> u) & 1]
            for v in neighbours:
                if v not in colour:
                    colour[v] = 1 - colour[u]
                    stack.append(v)
                elif colour[v] == colour[u]:
                    return None
    return colour


def find_cycle(adjacency: list[int], length: int,
               vertices: list[int]) -> list[int] | None:
    """One simple directed cycle of the given length, as a vertex list."""
    members = set(vertices)
    for start in sorted(members):
        path = [start]
        used = {start}

        def walk(current: int) -> bool:
            if len(path) == length:
                return bool((adjacency[current] >> start) & 1)
            for nxt in cw.bits(adjacency[current]):
                if nxt in members and nxt not in used and nxt >= start:
                    used.add(nxt)
                    path.append(nxt)
                    if walk(nxt):
                        return True
                    used.discard(nxt)
                    path.pop()
            return False

        if walk(start):
            return list(path)
    return None


def levels(up: tuple[int, ...]) -> list[list[int]]:
    """Group elements by longest-chain-below, giving a layered drawing.

    Within each layer the order is chosen by repeated barycentre sweeps
    against the neighbouring layers, which removes most edge crossings in a
    dense three-level poset.  This is presentation only; the drawn relation is
    always the Hasse diagram of `up`.
    """
    down = cw.downsets(up)
    depth = [0] * len(up)
    for x in sorted(range(len(up)), key=lambda v: bin(down[v]).count("1")):
        below = list(cw.bits(down[x]))
        depth[x] = 1 + max((depth[y] for y in below), default=-1)
    layers: list[list[int]] = [[] for _ in range(max(depth) + 1)]
    for x, d in enumerate(depth):
        layers[d].append(x)

    hasse = cw.hasse(up)
    covers_up = {x: list(cw.bits(mask)) for x, mask in enumerate(hasse)}
    covers_down: dict[int, list[int]] = {x: [] for x in range(len(up))}
    for x, above in covers_up.items():
        for y in above:
            covers_down[y].append(x)

    def sweep(indices: list[list[int]], neighbours, reference: int,
              target: int) -> None:
        rank = {x: i for i, x in enumerate(indices[reference])}
        def key(x: int) -> tuple[float, int]:
            near = [rank[y] for y in neighbours[x] if y in rank]
            return (sum(near) / len(near) if near else 0.0, x)
        indices[target].sort(key=key)

    for _ in range(4):
        for d in range(1, len(layers)):
            sweep(layers, covers_down, d - 1, d)
        for d in range(len(layers) - 2, -1, -1):
            sweep(layers, covers_up, d + 1, d)
    return layers


def tikz_cycle_figure() -> str:
    """Hasse diagram beside the majority digraph of the cyclic part."""
    witness = WITNESS_8
    up = cw.decode(witness)
    analysis = cw.Analysis(up)
    adjacency = analysis.majority_digraph(True)
    core = cyclic_part(adjacency)
    spectrum = sorted(cw.cycle_lengths(adjacency))
    colour = bipartition(adjacency, core)
    cycle = find_cycle(adjacency, 8, core)

    restricted_spectrum = sorted(
        cw.cycle_lengths(analysis.majority_digraph(False))
    )
    if spectrum != [4, 8] or restricted_spectrum != spectrum:
        raise SystemExit(
            f"featured witness spectra are full={spectrum}, "
            f"restricted={restricted_spectrum}; expected [4, 8]"
        )
    if cycle is None:
        raise SystemExit("no explicit 8-cycle recovered")
    if cycle != [3, 4, 6, 7, 5, 9, 8, 10]:
        raise SystemExit(f"featured 8-cycle changed unexpectedly: {cycle}")
    if analysis.balance() != Fraction(1, 2):
        raise SystemExit(f"witness balance is {analysis.balance()}, expected 1/2")
    if len(core) != 8 or any(
        (up[source] >> target) & 1
        for source in core for target in core
    ):
        raise SystemExit("featured cyclic part is not an eight-element antichain")
    if colour is None:
        raise SystemExit("featured cyclic part is not bipartite")
    minimal = sum(
        not any((up[other] >> vertex) & 1 for other in range(len(up)))
        for vertex in range(len(up))
    )
    maximal = sum(up[vertex] == 0 for vertex in range(len(up)))
    if (minimal, maximal) != (3, 3):
        raise SystemExit(
            f"featured witness has {minimal} minima and {maximal} maxima"
        )

    layers = levels(up)
    hasse = cw.hasse(up)
    rank = {x: i for layer in layers for i, x in enumerate(layer)}

    lines = [
        "% Generated by scripts/make_census_figures.py -- do not edit by hand.",
        "\\begin{tikzpicture}[",
        "  x=1cm, y=1cm,",
        "  every node/.style={inner sep=1pt},",
        "  el/.style={circle, draw=black!65, minimum size=4.4mm,",
        "              font=\\scriptsize},",
        "  cyc/.style={el, draw=black, line width=0.9pt},",
        "  odd/.style={el, fill=black!12},",
        "  cov/.style={draw=black!55, line width=0.35pt},",
        "  maj/.style={->, >=stealth, draw=black!30, line width=0.4pt},",
        "  hot/.style={->, >=stealth, draw=black, line width=1.0pt},",
        "]",
    ]

    # ---- panel (a): the poset -------------------------------------------
    widest = max(len(layer) for layer in layers)
    pos: dict[int, tuple[float, float]] = {}
    pitch = 0.78
    for depth, layer in enumerate(layers):
        span = len(layer)
        for index, x in enumerate(layer):
            px = (index - (span - 1) / 2) * (widest / max(span, 1)) * pitch
            pos[x] = (px, depth * 1.55)
    for x, (px, py) in pos.items():
        style = "cyc" if x in core else "el"
        lines.append(f"  \\node[{style}] (p{x}) at ({px:.3f},{py:.3f}) {{{x}}};")
    for x, mask in enumerate(hasse):
        for y in cw.bits(mask):
            lines.append(f"  \\draw[cov] (p{x}) -- (p{y});")
    lines.append(
        f"  \\node[font=\\footnotesize] at (0,-0.95) "
        f"{{(a) $P$, with $\\mathrm{{e}}(P)={analysis.extensions:,}$}};"
    )

    # ---- panel (b): the majority digraph on the cyclic part --------------
    offset = widest * pitch / 2 + 3.3
    radius = 1.75
    order = cycle
    place: dict[int, tuple[float, float]] = {}
    for index, x in enumerate(order):
        angle = math.pi / 2 - 2 * math.pi * index / len(order)
        place[x] = (offset + radius * math.cos(angle),
                    1.55 + radius * math.sin(angle))
    for x, (px, py) in place.items():
        style = "odd" if colour and colour[x] == 0 else "el"
        lines.append(f"  \\node[{style}] (m{x}) at ({px:.3f},{py:.3f}) {{{x}}};")
    hot = {(order[i], order[(i + 1) % len(order)]) for i in range(len(order))}
    for x in core:
        for y in cw.bits(adjacency[x]):
            if y not in place:
                continue
            style = "hot" if (x, y) in hot else "maj"
            bend = "" if (x, y) in hot else "[bend left=12]"
            lines.append(f"  \\draw[{style}] (m{x}) to{bend} (m{y});")
    lines.append(
        f"  \\node[font=\\footnotesize] at ({offset:.3f},-0.95) "
        f"{{(b) $D(P)$ restricted to the cyclic part}};"
    )
    lines.append("\\end{tikzpicture}")
    return "\n".join(lines) + "\n"


def tikz_ladder_figure(n: int = 14, broken: tuple[int, ...] = (1, 9)) -> str:
    """The worst broken-rung ladder at order n."""
    up = cw.broken_rung_ladder(n, broken)
    analysis = cw.Analysis(up)
    value, best_broken, _ = cw.worst_broken_rung_ladder(n)
    if analysis.balance() != value or tuple(best_broken) != broken:
        raise SystemExit(
            f"L{n},{broken} is not the worst ladder: worst is {best_broken} "
            f"at {value}, this one is {analysis.balance()}"
        )

    hasse = cw.hasse(up)
    lines = [
        "% Generated by scripts/make_census_figures.py -- do not edit by hand.",
        "\\begin{tikzpicture}[",
        "  x=1cm, y=1cm,",
        "  el/.style={circle, draw, minimum size=4.2mm, inner sep=1pt,",
        "             font=\\scriptsize},",
        "  rail/.style={draw=black!60, line width=0.5pt},",
        "  rung/.style={draw=black!60, line width=0.5pt},",
        "]",
    ]
    for x in range(n):
        column = x % 2
        row = x // 2
        lines.append(
            f"  \\node[el] (l{x}) at ({row * 1.05:.2f},{column * 1.1:.2f}) "
            f"{{{x}}};"
        )
    for x, mask in enumerate(hasse):
        for y in cw.bits(mask):
            style = "rail" if (x % 2) == (y % 2) else "rung"
            lines.append(f"  \\draw[{style}] (l{x}) -- (l{y});")
    for position in broken:
        row = position // 2
        lines.append(
            f"  \\node[font=\\scriptsize, black!55] at ({row * 1.05:.2f},-0.75) "
            f"{{broken}};"
        )
    lines.append("\\end{tikzpicture}")
    return "\n".join(lines) + "\n"


def parse_tail(path: Path) -> list[tuple[Fraction, int, int]]:
    """Read the tail table out of an aggregate report."""
    rows: list[tuple[Fraction, int, int]] = []
    pattern = re.compile(
        r"^\s*(\d+)/(\d+)\s+[\d.]+\s+([\d,]+)\s+([\d,]+)\s"
    )
    for line in path.read_text().splitlines():
        match = pattern.match(line)
        if match:
            rows.append((
                Fraction(int(match.group(1)), int(match.group(2))),
                int(match.group(3).replace(",", "")),
                int(match.group(4).replace(",", "")),
            ))
    if not rows:
        raise SystemExit(f"no tail rows found in {path}")
    return rows


def tikz_tail_figure(rows: list[tuple[Fraction, int, int]], order: int,
                     labelled: int = 6) -> str:
    """The low balance tail on a number line, with the conjectured gap.

    Stem height encodes how many classes attain the value.  Only the lowest
    few values and the least non-ordinal-sum value carry labels, on staggered
    tiers, so the figure stays legible as the number of distinct values grows
    with the order.
    """
    rows = sorted(rows)
    lo, hi = Fraction(1, 3), Fraction(9, 25)
    span, top = 12.0, 2.70

    def place(value: Fraction) -> float:
        return float((value - lo) / (hi - lo)) * span

    least_nonsum = next((v for v, _, k in rows if k), None)
    to_label = {v for v, _, _ in rows[:labelled]}
    if least_nonsum is not None:
        to_label.add(least_nonsum)

    lines = [
        "% Generated by scripts/make_census_figures.py -- do not edit by hand.",
        "\\begin{tikzpicture}[x=1cm, y=1cm,",
        "  axis/.style={draw=black!75, line width=0.4pt},",
        "  nonsum/.style={draw=black, line width=0.9pt},",
        "  sum/.style={draw=black!45, line width=0.6pt},",
        "  lead/.style={draw=black!35, line width=0.3pt},",
        "]",
        f"  \\fill[black!8] (0,0) rectangle ({place(GAP_END):.3f},{top:.2f});",
        f"  \\draw[axis, densely dashed] ({place(GAP_END):.3f},0) -- "
        f"({place(GAP_END):.3f},{top:.2f});",
        f"  \\node[font=\\scriptsize, anchor=south east, black!55] at "
        f"({place(GAP_END) - 0.1:.3f},{top - 0.28:.2f}) "
        f"{{conjectured gap: no class here}};",
        f"  \\draw[axis] (0,0) -- ({span:.2f},0);",
        "  \\node[font=\\scriptsize, anchor=north] at (0,-0.08) "
        "{$\\tfrac13$};",
        f"  \\node[font=\\scriptsize, anchor=north] at ({span:.2f},-0.08) "
        f"{{$\\tfrac9{{25}}$}};",
    ]

    tallest = max(count for _, count, _ in rows)
    labelled_rows = [
        row for row in rows if row[0] in to_label
    ]
    rows_per_column = math.ceil(len(labelled_rows) / 2)
    tiers = [1.02 + 0.60 * index for index in range(rows_per_column)]
    label_start = min(place(value) for value, _, _ in labelled_rows)
    label_positions = {
        value: (
            label_start + 2.25 * (index // rows_per_column),
            tiers[index % rows_per_column],
        )
        for index, (value, _, _) in enumerate(labelled_rows)
    }
    for value, count, nonsum in rows:
        x = place(value)
        height = 0.18 + 0.72 * math.log1p(count) / math.log1p(tallest)
        lines.append(
            f"  \\draw[{'nonsum' if nonsum else 'sum'}] ({x:.3f},0) -- "
            f"({x:.3f},{height:.3f});"
        )
        if value in to_label:
            label_x, y = label_positions[value]
            lines.append(
                f"  \\draw[lead] ({x:.3f},{height:.3f}) -- "
                f"({label_x - 0.03:.3f},{y:.2f});"
            )
            lines.append(
                f"  \\node[font=\\tiny, anchor=west, inner sep=1pt, "
                f"fill=white, fill opacity=.9, text opacity=1] at "
                f"({label_x:.3f},{y:.2f}) "
                f"{{$\\frac{{{value.numerator}}}{{{value.denominator}}}$"
                f"{'$^{\\ast}$' if nonsum else ''}\\,{{\\scriptsize$\\times$}}{count}}};"
            )

    lines.append("\\end{tikzpicture}")
    # The narrative belongs in the LaTeX caption, not in an unbreakable TikZ
    # node: a long node makes the picture wider than the text block.
    hidden = len(rows) - len(to_label)
    note = (f"{hidden} further value{'s are' if hidden != 1 else ' is'} "
            f"drawn but not labelled.  " if hidden > 0 else "")
    lines.append(
        f"% caption: {len(rows)} distinct balance constants of order-{order} "
        f"posets lie in $(1/3, 9/25]$.  Stem height grows with the number of "
        f"classes attaining the value.  {note}"
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("outdir", type=Path)
    parser.add_argument("--tail", type=Path)
    parser.add_argument("--tail-order", type=int, required=True)
    args = parser.parse_args()

    args.outdir.mkdir(parents=True, exist_ok=True)
    if args.tail is None:
        raise SystemExit(
            "--tail is required: pass the aggregate report whose tail table "
            "the figure should draw, e.g. --tail data/census-n14.txt "
            "--tail-order 14")
    rows = parse_tail(args.tail)
    order = args.tail_order

    written = {
        "fig-cycle8.tex": tikz_cycle_figure(),
        "fig-ladder.tex": tikz_ladder_figure(),
        "fig-tail.tex": tikz_tail_figure(rows, order),
    }
    for name, body in written.items():
        (args.outdir / name).write_text(body)
        print(f"wrote {args.outdir / name}")


if __name__ == "__main__":
    main()
