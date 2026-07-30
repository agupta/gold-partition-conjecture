#!/usr/bin/env python3
"""Validate and aggregate a complete balance/majority census partition.

Every extremal claim a shard makes is recomputed here from the witness alone,
by the independent exact implementation in `census_witness.py`.  A shard's
numbers are treated as a claim to be checked, never as a result to be copied.

Usage:
    aggregate_census.py N MODULUS OUTDIR [--verify all|extremal|none]
"""

from __future__ import annotations

from collections import Counter
from fractions import Fraction
import hashlib
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import census_witness as witness_module
from census_witness import Analysis, WitnessError


POSET_COUNTS = {
    1: 1,
    2: 2,
    3: 5,
    4: 16,
    5: 63,
    6: 318,
    7: 2_045,
    8: 16_999,
    9: 183_231,
    10: 2_567_284,
    11: 46_749_427,
    12: 1_104_891_746,
    13: 33_823_827_452,
    14: 1_338_193_159_771,
    15: 68_275_077_901_156,
}

# De Loof, De Baets, and De Meyer, Comput. Math. Appl. 59 (2010), Table 2:
# counts of posets whose mutual-rank-probability majority relation has a
# simple cycle on the given number of elements, and the number with any cycle.
CYCLE_REGRESSION = {
    8: {"any": 0},
    9: {"any": 5, 3: 5},
    10: {"any": 153, 3: 148, 4: 6},
    11: {"any": 5_815, 3: 5_740, 4: 101},
    12: {"any": 218_097, 3: 216_573, 4: 2_885, 5: 5, 6: 21, 7: 0},
    13: {"any": 9_348_400, 3: 9_318_881, 4: 102_127, 5: 471, 6: 363, 7: 1},
}

# M. Peczarski, "The worst balanced posets are ladders with broken rungs",
# Experimental Mathematics 28 (2019), 181--184, Table 1.  These are width-two
# records, not proven global minima.
PECZARSKI_LADDER = {
    12: Fraction(97, 277),
    13: Fraction(157, 448),
    14: Fraction(254, 725),
}

# The same paper's conjectured gap: no poset has a balance constant strictly
# between 1/3 and this limit.  The value is the decimal printed in the paper,
# so it is an approximation of a conjectured limit, not an exact threshold.
PECZARSKI_GAP = Fraction(348_843, 1_000_000)

# A000112(n), the number of unlabeled posets on n points, as published by
# Heitzig--Reinhold and confirmed by Brinkmann--McKay.  Ordinal decomposition
# into indecomposable summands is unique, so with A(x) = sum a(n) x^n (a(0)=1)
# and B(x) the series of the ordinal-indecomposables, A = 1/(1 - B).  Inverting
# predicts the census's `connected` counter from published data alone, which is
# an external check on the ordinal-sum decomposition that nothing else tests.
POSET_TOTALS = [1, 1, 2, 5, 16, 63, 318, 2045, 16999, 183231, 2567284,
                46749427, 1104891746, 33823827452, 1338193159771]


def indecomposable_count(n: int) -> int | None:
    """Ordinal-indecomposable classes on n points, from A000112 alone."""
    if n >= len(POSET_TOTALS):
        return None
    b = [0] * (n + 1)
    for m in range(1, n + 1):
        b[m] = POSET_TOTALS[m] - sum(b[k] * POSET_TOTALS[m - k]
                                     for k in range(1, m))
    return b[n]


ONE_THIRD = Fraction(1, 3)

HASH_LINE = re.compile(r"^([0-9a-f]{64})\s+\S+$")

FINAL_FIELDS = {
    "total", "chain", "third", "above", "viol", "connected",
    "cyclic", "cyclic_inc", "skipdual", "dualpair", "dualtie",
    "tail_values", "equality_classes", "maxscc", "overflow",
    *(f"c{length}" for length in range(3, 16)),
    *(f"i{length}" for length in range(3, 16)),
}

PARAM_FIELDS = {
    "version", "n", "maxn", "tail_num", "tail_den", "tail_capacity",
    "equality_capacity", "dfs_budget", "decompose",
}


class Failure(Exception):
    pass


def fail(message: str) -> "NoReturn":
    raise Failure(message)


def parse_fields(line: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for token in line.split()[1:]:
        if "=" not in token:
            fail(f"malformed token: {token!r}")
        key, value = token.split("=", 1)
        if key in fields:
            fail(f"duplicate field: {key}")
        fields[key] = value
    return fields


def parse_integers(line: str, expected: set[str]) -> dict[str, int]:
    raw = parse_fields(line)
    fields: dict[str, int] = {}
    for key, value in raw.items():
        try:
            fields[key] = int(value)
        except ValueError:
            fail(f"non-integer field: {key}={value!r}")
        if fields[key] < 0:
            fail(f"negative field: {key}={value!r}")
    if set(fields) != expected:
        missing = sorted(expected - set(fields))
        extra = sorted(set(fields) - expected)
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if extra:
            details.append("unexpected " + ", ".join(extra))
        fail("invalid summary fields: " + "; ".join(details))
    return fields


def parse_metadata(path: Path) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if HASH_LINE.fullmatch(line):
            fail(f"{path}: bare hash lines are not accepted for the census")
        if "=" not in line:
            fail(f"{path}: malformed metadata line: {line!r}")
        key, value = line.split("=", 1)
        if key in metadata:
            fail(f"{path}: duplicate metadata field: {key}")
        metadata[key] = value
    digest = metadata.get("binary_sha256", "")
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        fail(f"{path}: missing or invalid binary SHA-256")
    return metadata


class Extremum:
    """Least balance value seen, with its lexicographically least witness."""

    def __init__(self) -> None:
        self.value: Fraction | None = None
        self.num = 0
        self.den = 1
        self.witness: str | None = None

    def offer(self, num: int, den: int, witness: str) -> None:
        value = Fraction(num, den)
        if self.value is None or value < self.value:
            self.value, self.num, self.den, self.witness = (
                value, num, den, witness
            )
        elif value == self.value and (
            self.witness is None or witness < self.witness
        ):
            self.witness = witness


class TailEntry:
    def __init__(self, num: int, den: int) -> None:
        self.num = num
        self.den = den
        self.value = Fraction(num, den)
        self.count = 0
        self.connected = 0
        self.witness: str | None = None

    def offer(self, count: int, connected: int, witness: str) -> None:
        self.count += count
        self.connected += connected
        if self.witness is None or witness < self.witness:
            self.witness = witness


class Census:
    def __init__(self, n: int, modulus: int) -> None:
        self.n = n
        self.modulus = modulus
        self.totals: Counter[str] = Counter()
        self.params: dict[str, int] | None = None
        self.binary_hashes: set[str] = set()
        self.minima: dict[str, Extremum] = {}
        self.tail: dict[tuple[int, int], TailEntry] = {}
        self.equality: dict[str, tuple[int, int]] = {}
        self.cycle_witness: dict[tuple[str, int], str] = {}
        self.cycle_count: Counter[tuple[str, int]] = Counter()
        self.overflow_witnesses: list[str] = []
        self.max_scc = 0
        self.ladder = None

    # ---------------------------------------------------------------- reading

    def read_shard(self, residue: int, outdir: Path) -> None:
        base = outdir / f"s{residue}"
        marker = base.with_suffix(".done")
        output = base.with_suffix(".out")
        metadata_path = base.with_suffix(".meta")
        error = base.with_suffix(".err")

        if not marker.is_file() or marker.read_bytes() != b"done\n":
            fail(f"missing or invalid completion marker for shard {residue}")
        for path in (output, metadata_path, error):
            if not path.is_file():
                fail(f"missing {path.name} for shard {residue}")

        metadata = parse_metadata(metadata_path)
        expected = {
            "mode": "census",
            "n": str(self.n),
            "residue": str(residue),
            "modulus": str(self.modulus),
            "generator_options": "o,q,m",
        }
        for key, value in expected.items():
            if metadata.get(key) != value:
                fail(f"{metadata_path}: {key}={metadata.get(key)!r}; "
                     f"expected {value!r}")
        for key in ("started_utc", "finished_utc"):
            if not metadata.get(key):
                fail(f"{metadata_path}: missing {key}")
        self.binary_hashes.add(metadata["binary_sha256"])

        # The payload digest is written before the shard is renamed into
        # place, so a shard that was truncated or corrupted after publication
        # fails here rather than contributing silently wrong counts.
        payload = output.read_bytes()
        recorded = metadata.get("out_sha256", "")
        if not re.fullmatch(r"[0-9a-f]{64}", recorded):
            fail(f"{metadata_path}: missing or invalid payload digest")
        if hashlib.sha256(payload).hexdigest() != recorded:
            fail(f"shard {residue}: payload digest does not match the "
                 f"recorded {recorded}")

        finals, params = [], []
        for line in payload.decode().splitlines():
            if line.startswith("CENSUS-FINAL "):
                finals.append(line)
            elif line.startswith("CENSUS-PARAM "):
                params.append(line)
            elif line.startswith("CENSUS-MIN "):
                self._read_min(line, residue)
            elif line.startswith("CENSUS-TAIL "):
                self._read_tail(line, residue)
            elif line.startswith("CENSUS-EQUALITY "):
                self._read_equality(line, residue)
            elif line.startswith("CENSUS-CYCLE "):
                self._read_cycle(line, residue)
            elif line.startswith("CENSUS-OVERFLOW "):
                self.overflow_witnesses.append(
                    parse_fields(line).get("witness", "-")
                )

        if len(finals) != 1:
            fail(f"shard {residue} has {len(finals)} final summaries")
        if len(params) != 1:
            fail(f"shard {residue} has {len(params)} parameter lines")

        # The census weights one representative of a dual pair by two and
        # skips the other.  The two representatives can occupy different
        # modulus residues, so the partition and duality identities close only
        # in aggregate, never per shard.
        fields = parse_integers(finals[0], FINAL_FIELDS)
        # These three are per-shard diagnostics, not additive class counts.
        self.max_scc = max(self.max_scc, fields.pop("maxscc"))
        fields.pop("tail_values")
        fields.pop("equality_classes")
        self.totals.update(fields)

        param_fields = parse_integers(params[0], PARAM_FIELDS)
        declared = param_fields.pop("n")
        if declared not in (self.n, 0):
            fail(f"shard {residue}: parameter line declares n={declared}")
        if declared == 0 and fields["total"] != 0:
            fail(f"shard {residue}: no order declared for a nonempty shard")
        if self.params is None:
            self.params = param_fields
        elif self.params != param_fields:
            fail(f"shard {residue}: census parameters differ from earlier "
                 f"shards")

    def _witness(self, fields: dict[str, str], residue: int) -> str:
        value = fields.get("witness")
        if not value or value == "-":
            fail(f"shard {residue}: record without a witness")
        return value

    def _read_min(self, line: str, residue: int) -> None:
        fields = parse_fields(line)
        kind = fields.get("kind")
        if kind not in {"above", "above_connected", "violation"}:
            fail(f"shard {residue}: unknown minimum kind {kind!r}")
        extremum = self.minima.setdefault(kind, Extremum())
        extremum.offer(
            int(fields["num"]), int(fields["den"]),
            self._witness(fields, residue),
        )

    def _read_tail(self, line: str, residue: int) -> None:
        fields = parse_fields(line)
        key = (int(fields["num"]), int(fields["den"]))
        entry = self.tail.setdefault(key, TailEntry(*key))
        entry.offer(
            int(fields["count"]), int(fields["connected"]),
            self._witness(fields, residue),
        )

    def _read_equality(self, line: str, residue: int) -> None:
        fields = parse_fields(line)
        text = self._witness(fields, residue)
        if text in self.equality:
            fail(f"shard {residue}: equality witness {text} seen twice")
        self.equality[text] = (int(fields["count"]), int(fields["connected"]))

    def _read_cycle(self, line: str, residue: int) -> None:
        fields = parse_fields(line)
        relation = fields.get("relation")
        if relation not in {"full", "inc"}:
            fail(f"shard {residue}: unknown cycle relation {relation!r}")
        key = (relation, int(fields["length"]))
        text = self._witness(fields, residue)
        self.cycle_count[key] += int(fields["count"])
        current = self.cycle_witness.get(key)
        if current is None or text < current:
            self.cycle_witness[key] = text

    # --------------------------------------------------------------- checking

    def check_aggregate(self) -> None:
        totals = self.totals
        if len(self.binary_hashes) != 1:
            fail(f"shards record {len(self.binary_hashes)} distinct binary "
                 f"hashes")
        if totals["total"] != POSET_COUNTS[self.n]:
            fail(f"total={totals['total']:,}; "
                 f"expected {POSET_COUNTS[self.n]:,}")
        if totals["chain"] != 1:
            fail(f"expected one chain; observed {totals['chain']}")
        predicted = indecomposable_count(self.n)
        if predicted is not None and totals["connected"] != predicted:
            fail(f"connected={totals['connected']:,}; A000112 predicts "
                 f"{predicted:,} ordinal-indecomposable classes")
        if totals["skipdual"] != totals["dualpair"]:
            fail("retained and omitted dual classes do not balance")
        if (totals["skipdual"] + totals["dualpair"] + totals["dualtie"]
                != totals["total"]):
            fail("duality classes do not partition the input")
        if totals["viol"]:
            fail(f"viol={totals['viol']}: the 1/3--2/3 bound is violated")
        if totals["overflow"] or self.overflow_witnesses:
            fail("a cycle search exhausted its budget; results are incomplete")
        if "violation" in self.minima:
            fail("a shard reported a violating poset")

        expected = CYCLE_REGRESSION.get(self.n)
        if expected is not None:
            if totals["cyclic"] != expected["any"]:
                fail(f"cyclic={totals['cyclic']}; published value is "
                     f"{expected['any']}")
            for length, count in expected.items():
                if length == "any":
                    continue
                if totals[f"c{length}"] != count:
                    fail(f"c{length}={totals[f'c{length}']}; published value "
                         f"is {count}")

        for length in range(3, 16):
            if self.cycle_count[("full", length)] != totals[f"c{length}"]:
                fail(f"cycle witness count disagrees with c{length}")
            if self.cycle_count[("inc", length)] != totals[f"i{length}"]:
                fail(f"cycle witness count disagrees with i{length}")

        if sum(count for count, _ in self.equality.values()) != totals["third"]:
            fail("equality witness counts do not sum to the equality class "
                 "count")

        predicted = witness_module.equality_family_count(self.n)
        if totals["third"] != predicted:
            fail(f"equality classes: observed {totals['third']}, the ordinal "
                 f"sum family predicts {predicted}")

        if self.params is None:
            fail("no census parameters were recorded")
        cutoff = Fraction(self.params["tail_num"], self.params["tail_den"])
        above = self.minima.get("above")
        if above is None or above.value is None:
            fail("no minimum above 1/3 was recorded")
        if above.value <= ONE_THIRD:
            fail("the recorded minimum is not strictly above 1/3")
        if self.tail:
            least = min(entry.value for entry in self.tail.values())
            if least != above.value:
                fail(f"least tail value {least} differs from the recorded "
                     f"minimum {above.value}")
        elif above.value <= cutoff:
            fail("the minimum lies inside the tail window but the tail table "
                 "is empty")

        connected = self.minima.get("above_connected")
        if connected is not None and connected.value is not None:
            if connected.value < above.value:
                fail("the non-ordinal-sum minimum is below the global minimum")
            if connected.value <= cutoff:
                candidates = [
                    entry.value for entry in self.tail.values()
                    if entry.connected
                ]
                if not candidates or min(candidates) != connected.value:
                    fail("the non-ordinal-sum minimum is not the least tail "
                         "value with a connected witness")

    # ----------------------------------------------------------- verification

    def verify_witnesses(self, scope: str) -> list[str]:
        """Recompute every witness from scratch.  Returns report lines."""
        report: list[str] = []
        if scope == "none":
            return ["witness verification skipped"]

        checked = 0
        for kind, extremum in sorted(self.minima.items()):
            assert extremum.witness is not None
            self._verify_balance(
                extremum.witness, Fraction(extremum.num, extremum.den),
                f"minimum '{kind}'",
                require_connected=True if kind == "above_connected" else None,
            )
            checked += 1

        for key, text in sorted(self.cycle_witness.items()):
            relation, length = key
            self._verify_cycle(text, relation, length)
            checked += 1

        if scope == "all":
            for key in sorted(self.tail, key=lambda item: Fraction(*item)):
                entry = self.tail[key]
                assert entry.witness is not None
                self._verify_balance(
                    entry.witness, entry.value,
                    f"tail value {entry.num}/{entry.den}",
                    require_connected=None,
                )
                checked += 1
            for text in sorted(self.equality):
                self._verify_equality(text)
                checked += 1

        report.append(f"independently recomputed {checked} witnesses")
        return report

    def _decode(self, text: str, context: str) -> tuple[int, ...]:
        try:
            up = witness_module.decode(text)
        except WitnessError as error:
            fail(f"{context}: {error}")
        if len(up) != self.n:
            fail(f"{context}: witness has order {len(up)}, expected {self.n}")
        return up

    def _verify_balance(
        self, text: str, claimed: Fraction, context: str,
        require_connected: bool | None,
    ) -> None:
        up = self._decode(text, context)
        observed = Analysis(up).balance()
        if observed is None:
            fail(f"{context}: witness is a chain")
        if observed != claimed:
            fail(f"{context}: witness has balance {observed}, "
                 f"shard claimed {claimed}")
        if require_connected is not None:
            connected = len(witness_module.ordinal_summands(up)) == 1
            if connected != require_connected:
                fail(f"{context}: witness connectivity is {connected}, "
                     f"expected {require_connected}")

    def _verify_cycle(self, text: str, relation: str, length: int) -> None:
        context = f"{relation} cycle of length {length}"
        up = self._decode(text, context)
        adjacency = Analysis(up).majority_digraph(relation == "full")
        lengths = witness_module.cycle_lengths(adjacency)
        if length not in lengths:
            fail(f"{context}: witness has cycle lengths {sorted(lengths)}")

    def _verify_equality(self, text: str) -> None:
        context = f"equality witness {text}"
        up = self._decode(text, context)
        observed = Analysis(up).balance()
        if observed != ONE_THIRD:
            fail(f"{context}: balance is {observed}, expected 1/3")
        if not witness_module.is_equality_family(up):
            fail(f"{context}: not an ordinal sum of singletons and copies "
                 f"of T")
        dual = tuple(
            sum(1 << y for y in range(len(up)) if (up[y] >> x) & 1)
            for x in range(len(up))
        )
        if not witness_module.is_equality_family(dual):
            fail(f"{context}: the order dual leaves the claimed family")

    # -------------------------------------------------------------- reporting

    def report(self) -> list[str]:
        totals = self.totals
        lines = [
            f"order {self.n}, {self.modulus} residues, "
            f"binary {next(iter(self.binary_hashes))}",
            "",
            "Aggregate",
            "---------",
        ]
        for key in ("total", "chain", "third", "above", "viol", "connected",
                    "cyclic", "cyclic_inc"):
            lines.append(f"{key:16s} {totals[key]:>18,d}")
        lines.append(f"{'max scc':16s} {self.max_scc:>18,d}")

        lines += ["", "Majority cycles by length", "-------------------------",
                  f"{'length':>6}  {'full':>16}  {'incomparable only':>18}"]
        for length in range(3, self.n + 1):
            full, restricted = totals[f"c{length}"], totals[f"i{length}"]
            if full or restricted:
                lines.append(f"{length:>6}  {full:>16,d}  {restricted:>18,d}")
        if all(totals[f"c{length}"] == totals[f"i{length}"]
               for length in range(3, 16)):
            lines.append("the two relations agree at every length")
        else:
            lines.append("the two relations DIFFER; see decision 0003")

        lines += ["", "Extremal balance constants", "--------------------------"]
        for kind, label in (
            ("above", "minimum above 1/3"),
            ("above_connected", "minimum, no nontrivial ordinal sum"),
        ):
            extremum = self.minima.get(kind)
            if extremum is None or extremum.value is None:
                continue
            lines.append(
                f"{label:36s} {extremum.num}/{extremum.den} = "
                f"{float(extremum.value):.9f}"
            )
            lines.append(f"{'witness':36s} {extremum.witness}")
            up = witness_module.decode(extremum.witness)
            lines.append(
                f"{'width, height, extensions':36s} "
                f"{witness_module.width(up)}, {witness_module.height(up)}, "
                f"{Analysis(up).extensions:,}"
            )
            canonical = witness_module.canonical(up)
            if canonical is not None:
                lines.append(
                    f"{'canonical form':36s} "
                    f"{witness_module.encode(canonical)}"
                )
            lines.append(
                f"{'Hasse digraph6':36s} "
                f"{witness_module.digraph6(witness_module.hasse(up))}"
            )

        lines += ["", "Comparison with Peczarski's ladder",
                  "----------------------------------"]
        connected = self.minima.get("above_connected")
        quoted = PECZARSKI_LADDER.get(self.n)
        if quoted is not None:
            lines.append(
                f"{'quoted Table 1 record':30s} {quoted.numerator}/"
                f"{quoted.denominator} = {float(quoted):.9f}"
            )
        if self.ladder is not None:
            value, broken, up = self.ladder
            name = f"L{self.n}" + "".join(f",{rung}" for rung in broken)
            lines.append(
                f"{'worst broken-rung ladder':30s} {value.numerator}/"
                f"{value.denominator} = {float(value):.9f}   {name}"
            )
            lines.append(
                f"{'  its Hasse digraph6':30s} "
                f"{witness_module.digraph6(witness_module.hasse(up))}"
            )
            if quoted is not None:
                lines.append(
                    "the recomputed ladder record "
                    + ("CONFIRMS" if value == quoted else "CONTRADICTS")
                    + " the quoted value"
                )
        else:
            lines.append("the broken-rung ladder search was not run")

        if connected is None or connected.value is None:
            lines.append("no non-ordinal-sum minimum was recorded")
        else:
            lines.append(
                f"{'census minimum, not a sum':30s} {connected.num}/"
                f"{connected.den} = {float(connected.value):.9f}"
            )
            reference = self.ladder[0] if self.ladder is not None else quoted
            if reference is not None and reference <= ONE_THIRD:
                lines.append("the worst ladder attains the 1/3 equality case, "
                             "so it is not comparable with a minimum taken "
                             "strictly above 1/3")
                reference = None
            if reference is None:
                pass
            elif connected.value == reference:
                lines.append("the census minimum EQUALS the worst ladder: "
                             "Peczarski's conjecture holds at this order")
            elif connected.value < reference:
                lines.append("the census minimum is BELOW the worst ladder: "
                             "Peczarski's conjecture FAILS at this order")
            else:
                lines.append("the census minimum is ABOVE the worst ladder, "
                             "which is impossible if the ladder is a poset of "
                             "this order; investigate before publishing")

        inside = sorted(
            (entry for entry in self.tail.values()
             if ONE_THIRD < entry.value < PECZARSKI_GAP),
            key=lambda entry: entry.value,
        )
        lines.append("")
        lines.append(f"proposed gap upper end        "
                     f"{float(PECZARSKI_GAP):.9f} (stated decimal)")
        if inside:
            lines.append(f"{len(inside)} distinct balance values lie strictly "
                         f"inside the proposed gap:")
            for entry in inside:
                lines.append(f"  {entry.num}/{entry.den} = "
                             f"{float(entry.value):.9f}  count {entry.count:,}"
                             f"  witness {entry.witness}")
        else:
            lines.append("no balance value lies strictly inside the proposed "
                         "gap")

        lines += ["", "Low balance tail", "----------------"]
        cutoff = Fraction(self.params["tail_num"], self.params["tail_den"])
        lines.append(f"window (1/3, {self.params['tail_num']}/"
                     f"{self.params['tail_den']}] = (0.333333333, "
                     f"{float(cutoff):.9f}]")
        lines.append(f"{'value':>18}  {'decimal':>11}  {'posets':>16}  "
                     f"{'not a sum':>12}  {'wid':>3}  witness")
        for key in sorted(self.tail, key=lambda item: Fraction(*item)):
            entry = self.tail[key]
            up = witness_module.decode(entry.witness)
            lines.append(
                f"{entry.num:>8}/{entry.den:<9} {float(entry.value):>11.9f}  "
                f"{entry.count:>16,d}  {entry.connected:>12,d}  "
                f"{witness_module.width(up):>3}  {entry.witness}"
            )

        lines += ["", "Equality cases", "--------------",
                  f"{totals['third']} isomorphism classes with balance "
                  f"exactly 1/3",
                  f"{len(self.equality)} stored representatives "
                  f"(dual pairs share one)",
                  f"the ordinal-sum family predicts "
                  f"{witness_module.equality_family_count(self.n)}"]
        for text in sorted(self.equality):
            count, is_connected = self.equality[text]
            lines.append(f"  count {count}  connected {is_connected}  {text}")

        lines += ["", "Majority-cycle witnesses", "------------------------"]
        for (relation, length), text in sorted(self.cycle_witness.items()):
            lines.append(
                f"  relation {relation:4s} length {length:>2}  "
                f"count {self.cycle_count[(relation, length)]:>14,d}  {text}"
            )
        return lines


def main() -> None:
    arguments = sys.argv[1:]
    scope = "all"
    ladder_search = True
    if "--no-ladder" in arguments:
        ladder_search = False
        arguments.remove("--no-ladder")
    if "--verify" in arguments:
        index = arguments.index("--verify")
        if index + 1 >= len(arguments):
            raise SystemExit("--verify needs a value")
        scope = arguments[index + 1]
        if scope not in {"all", "extremal", "none"}:
            raise SystemExit("--verify must be all, extremal, or none")
        del arguments[index:index + 2]

    if len(arguments) != 3:
        raise SystemExit(
            "usage: aggregate_census.py N MODULUS OUTDIR "
            "[--verify all|extremal|none] [--no-ladder]"
        )
    try:
        n = int(arguments[0])
        modulus = int(arguments[1])
    except ValueError:
        raise SystemExit("N and MODULUS must be integers")
    if n not in POSET_COUNTS:
        raise SystemExit(f"no unlabeled-poset total is recorded for n={n}")
    if modulus < 1:
        raise SystemExit("MODULUS must be positive")
    outdir = Path(arguments[2])

    census = Census(n, modulus)
    try:
        failed = sorted(outdir.glob("s*.failed*"))
        if failed:
            fail(f"failure artifacts remain: {failed[0].name}")
        for residue in range(modulus):
            census.read_shard(residue, outdir)
        census.check_aggregate()
        if ladder_search:
            census.ladder = witness_module.worst_broken_rung_ladder(n)
        verification = census.verify_witnesses(scope)
        lines = census.report()
    except Failure as error:
        print(f"FAIL: {error}", file=sys.stderr)
        raise SystemExit(1)

    print("\n".join(lines))
    print()
    for line in verification:
        print(line)
    print(f"PASS: {modulus} complete, disjoint shards")


if __name__ == "__main__":
    main()
