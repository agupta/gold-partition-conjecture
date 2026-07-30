#!/usr/bin/env bash
# Run a contiguous range of census residues with N parallel workers.
#
#   run_census_range.sh N LO HI MODULUS [WORKERS] [OUTDIR]
#
# Resumable and preemption-safe: an already published shard is revalidated by
# the shard runner, and a shard interrupted mid-run leaves no completion
# marker, so it simply reruns.
# Disjointness across hosts is the caller's responsibility: give each host a
# range that does not overlap any other's.
set -uo pipefail

if (( $# < 4 || $# > 6 )); then
    echo "usage: $0 N LO HI MODULUS [WORKERS] [OUTDIR]" >&2
    exit 2
fi

n=$1
lo=$2
hi=$3
modulus=$4
workers=${5:-$(nproc)}
root=$(cd "$(dirname "$0")/.." && pwd)
out=${6:-$root/out}
log=$out/progress.log

[[ "$n$lo$hi$modulus$workers" =~ ^[0-9]+$ ]] ||
    { echo "N, LO, HI, MODULUS, and WORKERS must be integers" >&2; exit 2; }
(( lo <= hi && hi < modulus )) ||
    { echo "require LO <= HI < MODULUS" >&2; exit 2; }
(( workers >= 1 )) || { echo "WORKERS must be positive" >&2; exit 2; }

mkdir -p "$out"
state=$(mktemp -d "$out/.range-$lo-$hi.XXXXXX")
trap 'rm -rf "$state"' EXIT
echo "$(date -u +%FT%TZ) start n=$n range $lo-$hi modulus=$modulus workers=$workers" >> "$log"

for residue in $(seq "$lo" "$hi"); do
    while (( $(jobs -rp | wc -l) >= workers )); do
        wait -n
    done
    (
        start=$(date +%s)
        if "$root/scripts/run_census_shard.sh" "$n" "$residue" "$modulus" \
                "$out" > /dev/null 2>&1; then
            : > "$state/s$residue.ok"
            echo "$(date -u +%FT%TZ) shard $residue ok $(( $(date +%s) - start ))s" >> "$log"
        else
            : > "$state/s$residue.failed"
            echo "$(date -u +%FT%TZ) shard $residue FAILED" >> "$log"
        fi
    ) &
done
wait

published=$(find "$state" -name 's*.ok' -type f | wc -l)
failed=$(find "$state" -name 's*.failed' -type f | wc -l)
echo "$(date -u +%FT%TZ) range $lo-$hi finished: $published published, $failed failed" >> "$log"
(( failed == 0 ))
