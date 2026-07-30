#!/usr/bin/env bash
# Run one residue class of the balance/majority census.
#
# Kept separate from scripts/run_shard.sh: the two runners publish different
# payload sets and validate different completion markers.
set -euo pipefail

if [[ $# -ne 4 ]]; then
    echo "usage: $0 N RESIDUE MODULUS OUTDIR" >&2
    exit 2
fi

n=$1
residue=$2
modulus=$3
outdir=$4
root=$(cd "$(dirname "$0")/.." && pwd)
binary="$root/build/balance_census"

[[ -x "$binary" ]] || { echo "build the census first" >&2; exit 2; }
[[ "$n" =~ ^[0-9]+$ && "$residue" =~ ^[0-9]+$ &&
   "$modulus" =~ ^[1-9][0-9]*$ ]] ||
    { echo "N, residue, and modulus must be nonnegative integers" >&2; exit 2; }
(( n >= 1 && n <= 15 )) || { echo "N must lie between 1 and 15" >&2; exit 2; }
(( residue < modulus )) || { echo "residue must be below modulus" >&2; exit 2; }

mkdir -p "$outdir"
base="$outdir/s$residue"
binary_sha256=$(sha256sum "$binary" | cut -d' ' -f1)

if [[ -e "$base.done" ]]; then
    python3 "$root/scripts/census_io.py" validate-complete \
        "$base" "$n" "$residue" "$modulus" "$binary_sha256"
    echo "shard $residue is already complete"
    exit 0
fi
if compgen -G "$base.*" >/dev/null; then
    echo "refusing to overwrite incomplete artifacts for shard $residue" >&2
    exit 2
fi

temporary="$outdir/.s${residue}.$$"
trap 'rm -f "$temporary.out" "$temporary.err" "$temporary.meta" \
    "$temporary.done"' EXIT

{
    echo "mode=census"
    echo "n=$n"
    echo "residue=$residue"
    echo "modulus=$modulus"
    echo "generator_options=o,q,m"
    echo "host=$(hostname)"
    echo "started_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "binary_sha256=$binary_sha256"
} > "$temporary.meta"

set +e
/usr/bin/time -f 'TIME user=%U system=%S wall=%e maxrss_kb=%M' \
    "$binary" "$n" o q m "$residue" "$modulus" \
    > "$temporary.out" 2> "$temporary.err"
status=$?
set -e

summary_count=$(grep -c '^CENSUS-FINAL ' "$temporary.out" || true)
param_count=$(grep -c '^CENSUS-PARAM ' "$temporary.out" || true)
overflow_count=$(grep -c '^CENSUS-OVERFLOW ' "$temporary.out" || true)

# A violating poset, an exhausted cycle-search budget, or a full witness table
# all make the binary exit nonzero.  Any of them must quarantine the shard
# rather than publish it.
if (( status != 0 )) || (( summary_count != 1 )) || (( param_count != 1 )) ||
   (( overflow_count != 0 )); then
    {
        echo "failed_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
        echo "exit_status=$status"
        echo "summary_count=$summary_count"
        echo "param_count=$param_count"
        echo "overflow_count=$overflow_count"
    } >> "$temporary.meta"
    for suffix in out err meta; do
        mv "$temporary.$suffix" "$base.failed.$suffix"
    done
    printf 'failed\n' > "$base.failed"
    trap - EXIT
    echo "shard $residue failed with status $status" >&2
    exit "$(( status != 0 ? status : 1 ))"
fi

echo "finished_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$temporary.meta"
python3 "$root/scripts/census_io.py" publish-success "$temporary" "$base"
trap - EXIT
echo "completed shard $residue"
