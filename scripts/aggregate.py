#!/usr/bin/env python3
"""Validate and aggregate a complete modulus partition."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import re
import sys


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

# The division between the two pair-certificate searches depends on their
# order.  Their union, the triple count, and the open count do not.
GPC_REGRESSION = {
    8: (16_633, 365),
    9: (178_771, 4_459),
    10: (2_499_347, 67_936),
    11: (45_338_393, 1_411_033),
    12: (1_066_006_204, 38_885_541),
    13: (32_418_324_910, 1_405_502_541),
}

# De Loof, De Baets, and De Meyer, Comput. Math. Appl. 59 (2010),
# Table 2.
MAJORITY_REGRESSION = {
    8: (0, 0, 0),
    9: (5, 5, 0),
    10: (153, 148, 6),
    11: (5_815, 5_740, 101),
}

PRODUCTION_GPC_SHA256 = (
    "86329fb3b084e26de7246eb1e77e18334cb7ff09dd327720d5ac9104a8e9f839"
)
# These preserved calculations predate the generator_options metadata field.
# The exception is confined to their exact mode, order, modulus, and binary.
LEGACY_GPC_PROFILES = {
    ("gpc", 10, 64, PRODUCTION_GPC_SHA256),
    ("gpc", 11, 64, PRODUCTION_GPC_SHA256),
    ("gpc", 12, 64, PRODUCTION_GPC_SHA256),
    ("gpc", 13, 1024, PRODUCTION_GPC_SHA256),
    ("gpc", 14, 4096, PRODUCTION_GPC_SHA256),
}

HASH_LINE = re.compile(r"^([0-9a-f]{64})\s+\S+$")
GPC_FIELDS = {
    "total", "chain", "low_slave", "half_pair", "triple", "open"
}
MAJORITY_FIELDS = {
    "total", "chain", "cyclic", "third", "above", "viol",
    "skipdual", "dualpair", "dualtie",
    *(f"c{length}" for length in range(3, 16)),
}


def fail(message: str) -> "NoReturn":
    raise SystemExit(message)


def parse_summary(line: str, expected_fields: set[str]) -> dict[str, int]:
    fields: dict[str, int] = {}
    for token in line.split()[1:]:
        if "=" not in token:
            fail(f"malformed summary token: {token!r}")
        key, value = token.split("=", 1)
        if key in fields:
            fail(f"duplicate summary field: {key}")
        try:
            fields[key] = int(value)
        except ValueError:
            fail(f"non-integer summary field: {token!r}")
        if fields[key] < 0:
            fail(f"negative summary field: {token!r}")
    if set(fields) != expected_fields:
        missing = expected_fields.difference(fields)
        extra = set(fields).difference(expected_fields)
        details = []
        if missing:
            details.append("missing " + ", ".join(sorted(missing)))
        if extra:
            details.append("unexpected " + ", ".join(sorted(extra)))
        fail("invalid summary fields: " + "; ".join(details))
    return fields


def parse_metadata(path: Path) -> dict[str, str]:
    metadata: dict[str, str] = {}
    binary_hash: str | None = None
    used_bare_hash = False
    for line in path.read_text().splitlines():
        match = HASH_LINE.fullmatch(line)
        if match:
            if binary_hash is not None:
                fail(f"{path}: duplicate binary hash")
            binary_hash = match.group(1)
            used_bare_hash = True
            continue
        if "=" not in line:
            fail(f"{path}: malformed metadata line: {line!r}")
        key, value = line.split("=", 1)
        if key in metadata:
            fail(f"{path}: duplicate metadata field: {key}")
        metadata[key] = value
    if "binary_sha256" in metadata:
        if binary_hash is not None:
            fail(f"{path}: binary hash recorded twice")
        binary_hash = metadata["binary_sha256"]
    if binary_hash is None or not re.fullmatch(r"[0-9a-f]{64}", binary_hash):
        fail(f"{path}: missing or invalid binary SHA-256")
    metadata["binary_sha256"] = binary_hash
    # The preserved order-14 run predates the key-value hash and
    # generator-options fields.  Its bare sha256sum line is retained so the
    # released aggregator can be rerun on that archive.  New shards always
    # record generator_options explicitly.
    metadata["_legacy_bare_hash"] = "yes" if used_bare_hash else "no"
    return metadata


def accepts_legacy_profile(
    mode: str, n: int, modulus: int, metadata: dict[str, str]
) -> bool:
    profile = (mode, n, modulus, metadata["binary_sha256"])
    return metadata["_legacy_bare_hash"] == "yes" and profile in LEGACY_GPC_PROFILES


def validate_shard_summary(mode: str, fields: dict[str, int], residue: int) -> None:
    if mode == "gpc":
        partition = sum(
            fields[key]
            for key in ("chain", "low_slave", "half_pair", "triple", "open")
        )
        if partition != fields["total"]:
            fail(f"shard {residue}: GPC classes do not partition the input")
    # The majority census weights one representative of a dual pair by two
    # and skips the other.  The two representatives can occupy different
    # modulus residues, so its partition and duality checks are necessarily
    # aggregate rather than per-shard.


def read_totals(
    mode: str, n: int, modulus: int, outdir: Path
) -> tuple[Counter[str], str]:
    prefix = "GPC-FINAL " if mode == "gpc" else "LEM-FINAL "
    expected_fields = GPC_FIELDS if mode == "gpc" else MAJORITY_FIELDS
    totals: Counter[str] = Counter()
    binary_hashes: set[str] = set()
    failed_residues = {
        int(match.group(1))
        for path in outdir.glob("s*.failed*")
        if (match := re.match(r"^s([0-9]+)\.failed", path.name))
    }

    for residue in range(modulus):
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
        if residue in failed_residues:
            fail(f"failure artifact remains for shard {residue}")

        metadata = parse_metadata(metadata_path)
        expected = {
            "mode": mode,
            "n": str(n),
            "residue": str(residue),
            "modulus": str(modulus),
        }
        for key, value in expected.items():
            if metadata.get(key) != value:
                fail(
                    f"{metadata_path}: {key}={metadata.get(key)!r}; "
                    f"expected {value!r}"
                )
        for key in ("started_utc", "finished_utc"):
            if not metadata.get(key):
                fail(f"{metadata_path}: missing {key}")
        generator_options = metadata.get("generator_options")
        if generator_options is None:
            if not accepts_legacy_profile(mode, n, modulus, metadata):
                fail(
                    f"{metadata_path}: missing generator_options outside an "
                    "accepted historical profile"
                )
        elif generator_options != "o,q,m":
            fail(
                f"{metadata_path}: generator_options={generator_options!r}; "
                "expected 'o,q,m'"
            )
        binary_hashes.add(metadata["binary_sha256"])

        summaries = [
            line
            for line in output.read_text().splitlines()
            if line.startswith(prefix)
        ]
        if len(summaries) != 1:
            fail(f"shard {residue} has {len(summaries)} final summaries")
        fields = parse_summary(summaries[0], expected_fields)
        validate_shard_summary(mode, fields, residue)
        totals.update(fields)

    if len(binary_hashes) != 1:
        fail(f"shards record {len(binary_hashes)} distinct binary hashes")
    return totals, binary_hashes.pop()


def require_fields(totals: Counter[str], fields: set[str]) -> None:
    absent = fields.difference(totals)
    if absent:
        fail("missing summary fields: " + ", ".join(sorted(absent)))


def check_gpc(n: int, totals: Counter[str]) -> None:
    require_fields(
        totals, {"total", "chain", "low_slave", "half_pair", "triple", "open"}
    )
    pair_total = totals["low_slave"] + totals["half_pair"]
    partition = (
        totals["chain"] + pair_total + totals["triple"] + totals["open"]
    )
    if partition != totals["total"]:
        fail("GPC certificate classes do not partition the input")
    if totals["open"]:
        fail(f"open={totals['open']}")
    expected = GPC_REGRESSION.get(n)
    if expected is not None:
        observed = (pair_total, totals["triple"])
        if observed != expected:
            fail(f"GPC regression mismatch: {observed} != {expected}")


def check_majority(n: int, totals: Counter[str]) -> None:
    require_fields(
        totals,
        {
            "total",
            "chain",
            "third",
            "above",
            "viol",
            "skipdual",
            "dualpair",
            "cyclic",
            "c3",
            "c4",
        },
    )
    partition = (
        totals["chain"] + totals["third"] + totals["above"] + totals["viol"]
    )
    if partition != totals["total"]:
        fail("balance classes do not partition the input")
    if totals["skipdual"] != totals["dualpair"]:
        fail("retained and omitted dual classes do not balance")
    expected = MAJORITY_REGRESSION.get(n)
    if expected is not None:
        observed = (totals["cyclic"], totals["c3"], totals["c4"])
        if observed != expected:
            fail(f"majority-cycle regression mismatch: {observed} != {expected}")


def main() -> None:
    if len(sys.argv) != 5:
        fail("usage: aggregate.py {gpc|majority} N MODULUS OUTDIR")
    mode = sys.argv[1]
    if mode not in {"gpc", "majority"}:
        fail("mode must be gpc or majority")
    try:
        n = int(sys.argv[2])
        modulus = int(sys.argv[3])
    except ValueError:
        fail("N and MODULUS must be integers")
    if n not in POSET_COUNTS:
        fail(f"no unlabeled-poset total is recorded for n={n}")
    if modulus < 1:
        fail("MODULUS must be positive")

    totals, binary_hash = read_totals(mode, n, modulus, Path(sys.argv[4]))
    if totals["total"] != POSET_COUNTS[n]:
        fail(f"total={totals['total']:,}; expected {POSET_COUNTS[n]:,}")
    if totals["chain"] != 1:
        fail(f"expected one chain; observed {totals['chain']}")

    if mode == "gpc":
        check_gpc(n, totals)
    else:
        check_majority(n, totals)

    for key in sorted(totals):
        print(f"{key:12s} {totals[key]:15,d}")
    if mode == "gpc":
        pair_total = totals["low_slave"] + totals["half_pair"]
        print(f"{'pair_total':12s} {pair_total:15,d}")
    print(f"{'binary':12s} {binary_hash}")
    print(f"PASS: {modulus} complete, disjoint shards")


if __name__ == "__main__":
    main()
