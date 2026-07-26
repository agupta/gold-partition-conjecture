#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 3 ]]; then
    echo "usage: $0 GENPOSETG CLASSIFIER REFERENCE" >&2
    exit 2
fi

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

for n in 8 9; do
    case $n in
        8) expected=16999 ;;
        9) expected=183231 ;;
    esac

    "$1" "$n" o q > "$work/posets.d6"
    "$2" < "$work/posets.d6" > "$work/classifier.txt"
    "$3" < "$work/posets.d6" > "$work/reference.txt"

    records=$(wc -l < "$work/posets.d6")
    [[ "$records" -eq "$expected" ]] || {
        echo "expected $expected order-$n posets; observed $records" >&2
        exit 1
    }
    cmp "$work/classifier.txt" "$work/reference.txt" || {
        diff -u "$work/reference.txt" "$work/classifier.txt" | head -80 >&2
        exit 1
    }

    echo "PASS: per-poset differential check, n=$n ($records classes)"
done
