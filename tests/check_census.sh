#!/usr/bin/env bash
# End-to-end checks for the balance/majority census.
#
#   tests/check_census.sh          fast checks, about a minute
#   tests/check_census.sh --slow   adds the order-8 and order-9 differentials
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
build="$root/build"
slow=0
[[ ${1:-} == --slow ]] && slow=1

for program in genposetg balance_census balance_census_nodecompose \
               census_driver; do
    [[ -x "$build/$program" ]] || {
        echo "missing $build/$program; run scripts/build_census.sh" >&2
        exit 2
    }
done

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

echo "== aggregator and witness unit tests =="
(cd "$root" && python3 -m unittest -q tests.test_aggregate_census)

echo
echo "== per-poset differential against the independent reference =="
orders=(5 6 7)
(( slow )) && orders=(5 6 7 8 9)
for n in "${orders[@]}"; do
    "$build/genposetg" "$n" o q 2>/dev/null > "$work/p$n.d6"
    "$build/census_driver" < "$work/p$n.d6" > "$work/c$n.txt"
    python3 "$root/tests/reference_census.py" \
        < "$work/p$n.d6" > "$work/r$n.txt"
    if ! cmp -s "$work/r$n.txt" "$work/c$n.txt"; then
        diff -u "$work/r$n.txt" "$work/c$n.txt" | head -40 >&2
        echo "FAIL: order $n differs from the reference" >&2
        exit 1
    fi
    echo "PASS: order $n, $(wc -l < "$work/p$n.d6") classes"
done

echo
echo "== the ordinal-sum decomposition is an optimization, not a shortcut =="
for n in 6 7 8 9; do
    "$build/balance_census" "$n" o q 2>/dev/null \
        | grep -v '^CENSUS-PARAM ' > "$work/d$n.txt"
    "$build/balance_census_nodecompose" "$n" o q 2>/dev/null \
        | grep -v '^CENSUS-PARAM ' > "$work/u$n.txt"
    if ! cmp -s "$work/d$n.txt" "$work/u$n.txt"; then
        diff -u "$work/u$n.txt" "$work/d$n.txt" | head -40 >&2
        echo "FAIL: decomposition changes the order-$n census" >&2
        exit 1
    fi
    echo "PASS: order $n decomposed and undecomposed censuses agree"
done

echo
echo "== shard runner, durable publication, and aggregation =="
for residue in 0 1 2 3 4 5 6; do
    "$root/scripts/run_census_shard.sh" 9 "$residue" 7 "$work/shards" \
        > /dev/null
done
# Rerunning a complete shard must revalidate it rather than recompute it.
"$root/scripts/run_census_shard.sh" 9 0 7 "$work/shards" | grep -q "already complete"
python3 "$root/scripts/aggregate_census.py" 9 7 "$work/shards" > "$work/agg.txt"
grep -q "PASS: 7 complete, disjoint shards" "$work/agg.txt"
echo "PASS: order 9 sharded round trip"

echo
echo "== a truncated shard must be refused =="
truncate -s -1 "$work/shards/s3.out"
if python3 "$root/scripts/aggregate_census.py" 9 7 "$work/shards" \
        > /dev/null 2>&1; then
    echo "FAIL: the aggregator accepted a truncated shard" >&2
    exit 1
fi
echo "PASS: truncated shard refused"

echo
echo "== published order-9, order-10, and order-11 cycle regressions =="
for n in 9 10; do
    "$build/balance_census" "$n" o q 2>/dev/null > "$work/reg$n.txt"
done
grep -q "cyclic=5 cyclic_inc=5 " "$work/reg9.txt"
grep -q " c3=5 c4=0 " "$work/reg9.txt"
grep -q "cyclic=153 cyclic_inc=153 " "$work/reg10.txt"
grep -q " c3=148 c4=6 " "$work/reg10.txt"
echo "PASS: orders 9 and 10 match De Loof, De Baets, and De Meyer"
echo "NOTE: orders 11, 12, and 13 are separate long-running launch gates"

echo
# The released source differs from the production source in one comment.
# Enforce its exact public byte hash and the recorded hash after comments are
# stripped.  The latter was computed for both historical versions.
rel_hash=$(awk '/src\/balance_census.c \(as released\)/{print $1}' data/census-n14.txt)
semantic_hash=$(awk '/src\/balance_census.c \(comments stripped\)/{print $1}' \
    data/census-n14.txt)
here=$(sha256sum src/balance_census.c | cut -d' ' -f1)
if [[ "$here" != "$rel_hash" ]]; then
    echo "FAIL: src/balance_census.c is $here, data/census-n14.txt records $rel_hash" >&2
    exit 1
fi
semantic_here=$(
    gcc -x c -fpreprocessed -E -P - < src/balance_census.c 2>/dev/null \
        | sha256sum | cut -d' ' -f1
)
if [[ "$semantic_here" != "$semantic_hash" ]]; then
    echo "FAIL: comment-stripped census source is $semantic_here, expected $semantic_hash" >&2
    exit 1
fi
echo "census source matches the released and comment-stripped hashes"

echo "PASS: census checks"
