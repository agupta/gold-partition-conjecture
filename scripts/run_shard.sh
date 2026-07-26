#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 5 ]]; then
    echo "usage: $0 {gpc|majority} N RESIDUE MODULUS OUTDIR" >&2
    exit 2
fi

mode=$1
n=$2
residue=$3
modulus=$4
outdir=$5
root=$(cd "$(dirname "$0")/.." && pwd)

case "$mode" in
    gpc) binary="$root/build/gpc" ;;
    majority) binary="$root/build/majority_census" ;;
    *) echo "mode must be gpc or majority" >&2; exit 2 ;;
esac

[[ -x "$binary" ]] || { echo "build the programs first" >&2; exit 2; }
[[ "$n" =~ ^[0-9]+$ && "$residue" =~ ^[0-9]+$ &&
   "$modulus" =~ ^[1-9][0-9]*$ ]] ||
    { echo "N, residue, and modulus must be nonnegative integers" >&2; exit 2; }
(( n >= 1 && n <= 15 )) || { echo "N must lie between 1 and 15" >&2; exit 2; }
(( residue < modulus )) || { echo "residue must be below modulus" >&2; exit 2; }

mkdir -p "$outdir"
base="$outdir/s$residue"
binary_sha256=$(sha256sum "$binary" | cut -d' ' -f1)

if [[ -e "$base.done" ]]; then
    python3 "$root/scripts/shard_io.py" validate-complete \
        "$base" "$mode" "$n" "$residue" "$modulus" "$binary_sha256"
    echo "shard $residue is already complete"
    exit 0
fi
if compgen -G "$base.*" >/dev/null; then
    echo "refusing to overwrite incomplete artifacts for shard $residue" >&2
    exit 2
fi

temporary="$outdir/.s${residue}.$$"
trap 'rm -f "$temporary.out" "$temporary.err" \
    "$temporary.meta" "$temporary.open" "$temporary.done"' EXIT

{
    echo "mode=$mode"
    echo "n=$n"
    echo "residue=$residue"
    echo "modulus=$modulus"
    echo "generator_options=o,q,m"
    echo "host=$(hostname)"
    echo "started_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "binary_sha256=$binary_sha256"
} > "$temporary.meta"

set +e
GPC_OPEN="$temporary.open" /usr/bin/time \
    -f 'TIME user=%U system=%S wall=%e maxrss_kb=%M' \
    "$binary" "$n" o q m "$residue" "$modulus" \
    > "$temporary.out" 2> "$temporary.err"
status=$?
set -e

summary='^GPC-FINAL '
[[ "$mode" == majority ]] && summary='^LEM-FINAL '
summary_count=$(grep -c "$summary" "$temporary.out" || true)

if (( status != 0 )) ||
   [[ "$mode" == gpc && -s "$temporary.open" ]] ||
   (( summary_count != 1 )); then
    open_dump_nonempty=no
    [[ ! -s "$temporary.open" ]] || open_dump_nonempty=yes
    {
        echo "failed_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
        echo "exit_status=$status"
        echo "summary_count=$summary_count"
        echo "open_dump_nonempty=$open_dump_nonempty"
    } >> "$temporary.meta"
    for suffix in out err meta; do
        mv "$temporary.$suffix" "$base.failed.$suffix"
    done
    if [[ -s "$temporary.open" ]]; then
        mv "$temporary.open" "$base.failed.open"
    else
        rm -f "$temporary.open"
    fi
    printf 'failed\n' > "$base.failed"
    trap - EXIT
    if (( status != 0 )); then
        echo "shard $residue failed with status $status" >&2
        exit "$status"
    fi
    if [[ "$mode" == gpc && -s "$base.failed.open" ]]; then
        echo "shard $residue reported an open GPC class" >&2
    else
        echo "shard $residue produced $summary_count final summaries" >&2
    fi
    exit 1
fi

echo "finished_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$temporary.meta"
rm -f "$temporary.open"
python3 "$root/scripts/shard_io.py" publish-success "$temporary" "$base"
trap - EXIT
echo "completed shard $residue"
