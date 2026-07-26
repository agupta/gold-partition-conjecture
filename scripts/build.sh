#!/usr/bin/env bash
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

for program in gpc majority_census; do
    plugin="$root/src/$program.c"
    "$cc" "${flags[@]}" "${third_party_flags[@]}" \
        "-DPLUGIN=\"$plugin\"" "$GENPOSETG_C" "$NAUTY_LIB" \
        -o "$build/$program"
done

"$cc" "${flags[@]}" "${third_party_flags[@]}" \
    "$GENPOSETG_C" "$NAUTY_LIB" -o "$build/genposetg"
"$cc" "${flags[@]}" -Wno-unused-function \
    "$root/tests/gpc_classifier_driver.c" \
    -o "$build/gpc_classifier_driver"
"$cc" "${flags[@]}" \
    "$root/tests/reference_gpc.c" \
    -o "$build/reference_gpc"

sha256sum "$GENPOSETG_C" "$NAUTY_LIB" \
    "$root/src/poset_dp.h" "$root/src/gpc.c" \
    "$root/src/majority_census.c" "$build/gpc" \
    "$build/majority_census" "$build/genposetg" \
    "$build/gpc_classifier_driver" "$build/reference_gpc"
