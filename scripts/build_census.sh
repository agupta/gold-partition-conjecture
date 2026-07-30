#!/usr/bin/env bash
# Build the balance/majority census programs.
#
# Kept separate from scripts/build.sh because the two programs have different
# compile-time parameters; `make census-programs` runs this one and
# `make check` depends on it.
set -euo pipefail

: "${GENPOSETG_C:?path to genposetg.c}"
: "${NAUTY_INCLUDE:?directory containing gtools.h}"
: "${NAUTY_LIB:?path to libnautyS1.a or an equivalent nauty library}"

root=$(cd "$(dirname "$0")/.." && pwd)
build="$root/build"
cc=${CC:-gcc}

mkdir -p "$build"

flags=(
    -O3 -std=gnu2x
    -Wall -Wextra -Werror
    -Wno-unused-parameter -Wno-char-subscripts
    "-I$NAUTY_INCLUDE"
)

# genposetg 1.1 triggers this GCC diagnostic in its own source.  The plugin
# interface compiles the generator and plugin as one translation unit, so the
# warning remains visible but is not promoted to an error.
third_party_flags=(-Wno-error=array-bounds)

if [[ ${NATIVE:-0} == 1 ]]; then
    flags+=(-march=native -funroll-loops)
elif [[ ${NATIVE:-0} != 0 ]]; then
    echo "NATIVE must be 0 or 1" >&2
    exit 2
fi

plugin="$root/src/balance_census.c"

"$cc" "${flags[@]}" "${third_party_flags[@]}" \
    "-DPLUGIN=\"$plugin\"" "$GENPOSETG_C" "$NAUTY_LIB" \
    -o "$build/balance_census"

# A second binary with the ordinal-sum decomposition disabled.  It must agree
# with the production binary on every poset; it exists only to test that the
# decomposition is an optimization and not an approximation.
"$cc" "${flags[@]}" "${third_party_flags[@]}" \
    -DCENSUS_NO_DECOMPOSE \
    "-DPLUGIN=\"$plugin\"" "$GENPOSETG_C" "$NAUTY_LIB" \
    -o "$build/balance_census_nodecompose"

"$cc" "${flags[@]}" -Wno-unused-function \
    "$root/tests/census_driver.c" \
    -o "$build/census_driver"

sha256sum "$GENPOSETG_C" "$NAUTY_LIB" \
    "$root/src/poset_dp.h" "$root/src/balance_census.c" \
    "$build/balance_census" "$build/balance_census_nodecompose" \
    "$build/census_driver"
