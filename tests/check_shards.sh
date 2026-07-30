#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

for mode in gpc majority; do
    output="$work/$mode"
    for residue in 0 1 2; do
        "$root/scripts/run_shard.sh" "$mode" 6 "$residue" 3 "$output"
    done
    "$root/scripts/aggregate.py" "$mode" 6 3 "$output"
done

for mode in gpc majority; do
    output="$work/${mode}-n9"
    for residue in 0 1 2 3 4 5 6; do
        "$root/scripts/run_shard.sh" "$mode" 9 "$residue" 7 "$output"
    done
    "$root/scripts/aggregate.py" "$mode" 9 7 "$output"
done

echo "PASS: shard runner and aggregator"
