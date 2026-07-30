#ifndef POSET_DP_H
#define POSET_DP_H

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define POSET_MAXN 15

/*
 * A poset is represented by its strict transitive closure.  Bit y of up[x]
 * is set precisely when x < y.  All arithmetic is exact: 15! fits easily
 * in uint64_t.
 */

static void poset_downsets(const uint16_t *up, int n, uint16_t *down)
{
    memset(down, 0, (size_t)n * sizeof(*down));
    for (int x = 0; x < n; x++) {
        uint16_t successors = up[x];
        while (successors) {
            const int y = __builtin_ctz(successors);
            successors &= (uint16_t)(successors - 1);
            down[y] |= (uint16_t)(1u << x);
        }
    }
}

static int ideals_recursive(const uint16_t *down, int n, uint16_t ideal,
                            int next, uint16_t *ideals, int count)
{
    for (int x = next; x < n; x++)
        if ((down[x] & ~ideal) == 0) {
            const uint16_t enlarged =
                (uint16_t)(ideal | (uint16_t)(1u << x));
            ideals[count++] = enlarged;
            count = ideals_recursive(
                down, n, enlarged, x + 1, ideals, count);
        }
    return count;
}

/*
 * List the order ideals in an order compatible with deletion of a maximal
 * element.  genposetg's internal labels need not be topological, so the
 * general branch orders ideals by their integer masks.
 */
static int poset_ideals(const uint16_t *up, const uint16_t *down, int n,
                        uint16_t *ideals, uint16_t *maximal)
{
    int topological = 1;
    for (int x = 0; x < n; x++)
        if (down[x] >> x) {
            topological = 0;
            break;
        }

    int count = 1;
    ideals[0] = 0;
    if (topological) {
        static uint16_t unordered[1 << POSET_MAXN];
        count = ideals_recursive(down, n, 0, 0, unordered, 1);

        int sizes[POSET_MAXN + 1] = {0};
        int offsets[POSET_MAXN + 2] = {0};
        for (int k = 1; k < count; k++)
            sizes[__builtin_popcount((unsigned)unordered[k])]++;
        offsets[0] = 1;
        for (int size = 0; size <= POSET_MAXN; size++)
            offsets[size + 1] = offsets[size] + sizes[size];

        int position[POSET_MAXN + 1];
        memcpy(position, offsets, sizeof(position));
        for (int k = 1; k < count; k++) {
            const int size =
                __builtin_popcount((unsigned)unordered[k]);
            ideals[position[size]++] = unordered[k];
        }
    } else {
        const int full = (1 << n) - 1;
        static uint16_t required[1 << POSET_MAXN];
        required[0] = 0;
        for (int set = 1; set <= full; set++) {
            required[set] = (uint16_t)(
                required[set & (set - 1)] |
                down[__builtin_ctz((unsigned)set)]);
            if ((required[set] & ~set) == 0)
                ideals[count++] = (uint16_t)set;
        }
    }

    for (int k = 0; k < count; k++) {
        uint16_t candidates = ideals[k];
        uint16_t mask = 0;
        while (candidates) {
            const int x = __builtin_ctz(candidates);
            candidates &= (uint16_t)(candidates - 1);
            if ((up[x] & ideals[k]) == 0)
                mask |= (uint16_t)(1u << x);
        }
        maximal[k] = mask;
    }
    return count;
}

static uint64_t poset_extensions(
    int n, const uint16_t *ideals, const uint16_t *maximal,
    int ideal_count, uint64_t *prefix)
{
    prefix[0] = 1;
    for (int k = 1; k < ideal_count; k++) {
        const uint16_t ideal = ideals[k];
        uint16_t choices = maximal[k];
        uint64_t count = 0;
        while (choices) {
            const int x = __builtin_ctz(choices);
            choices &= (uint16_t)(choices - 1);
            count += prefix[ideal ^ (uint16_t)(1u << x)];
        }
        prefix[ideal] = count;
    }
    return prefix[(1 << n) - 1];
}

#ifdef POSET_DP_GPC

/* Number of extensions in which x precedes y. */
static uint64_t poset_extensions_xy(
    const uint16_t *ideals, const uint16_t *maximal, int ideal_count,
    int x, int y, uint64_t *work)
{
    const uint16_t bx = (uint16_t)(1u << x);
    const uint16_t by = (uint16_t)(1u << y);
    work[0] = 1;
    for (int k = 1; k < ideal_count; k++) {
        const uint16_t ideal = ideals[k];
        if ((ideal & by) && !(ideal & bx)) {
            work[ideal] = 0;
            continue;
        }
        uint16_t choices = maximal[k];
        uint64_t count = 0;
        while (choices) {
            const int z = __builtin_ctz(choices);
            choices &= (uint16_t)(choices - 1);
            count += work[ideal ^ (uint16_t)(1u << z)];
        }
        work[ideal] = count;
    }
    return work[ideals[ideal_count - 1]];
}

/* Number of extensions in which x precedes y and y precedes z. */
static uint64_t poset_extensions_xyz(
    const uint16_t *ideals, const uint16_t *maximal, int ideal_count,
    int x, int y, int z, uint64_t *work)
{
    const uint16_t bx = (uint16_t)(1u << x);
    const uint16_t by = (uint16_t)(1u << y);
    const uint16_t bz = (uint16_t)(1u << z);
    work[0] = 1;
    for (int k = 1; k < ideal_count; k++) {
        const uint16_t ideal = ideals[k];
        if (((ideal & by) && !(ideal & bx)) ||
            ((ideal & bz) && !(ideal & by))) {
            work[ideal] = 0;
            continue;
        }
        uint16_t choices = maximal[k];
        uint64_t count = 0;
        while (choices) {
            const int w = __builtin_ctz(choices);
            choices &= (uint16_t)(choices - 1);
            count += work[ideal ^ (uint16_t)(1u << w)];
        }
        work[ideal] = count;
    }
    return work[ideals[ideal_count - 1]];
}

/*
 * All ordered pair counts from one forward and one backward recurrence.
 * For a transition I -> I+{y}, prefix[I] suffix[I+{y}] counts exactly the
 * extensions whose next element is y.  Adding that weight for x in I gives
 * the number of extensions in which x precedes y.
 */
static void poset_all_pairs(
    int n, const uint16_t *up, const uint16_t *down,
    const uint16_t *ideals, int ideal_count, const uint64_t *prefix,
    uint64_t *suffix, uint64_t pairs[POSET_MAXN][POSET_MAXN])
{
    const uint16_t full = (uint16_t)((1u << n) - 1);
    memset(pairs, 0, sizeof(uint64_t) * POSET_MAXN * POSET_MAXN);

    suffix[full] = 1;
    for (int k = ideal_count - 2; k >= 0; k--) {
        const uint16_t ideal = ideals[k];
        uint16_t missing = (uint16_t)(full & ~ideal);
        uint64_t count = 0;
        while (missing) {
            const int y = __builtin_ctz(missing);
            missing &= (uint16_t)(missing - 1);
            if ((down[y] & ~ideal) == 0)
                count += suffix[ideal | (uint16_t)(1u << y)];
        }
        suffix[ideal] = count;
    }
    if (suffix[0] != prefix[full]) {
        fprintf(stderr, "inconsistent forward and backward counts\n");
        exit(3);
    }

    for (int k = 0; k < ideal_count - 1; k++) {
        const uint16_t ideal = ideals[k];
        uint16_t missing = (uint16_t)(full & ~ideal);
        while (missing) {
            const int y = __builtin_ctz(missing);
            missing &= (uint16_t)(missing - 1);
            const uint16_t by = (uint16_t)(1u << y);
            if (down[y] & ~ideal)
                continue;
            const uint64_t weight = prefix[ideal] * suffix[ideal | by];
            uint16_t earlier = (uint16_t)(
                ideal & full & ~(up[y] | down[y] | by));
            while (earlier) {
                const int x = __builtin_ctz(earlier);
                earlier &= (uint16_t)(earlier - 1);
                pairs[x][y] += weight;
            }
        }
    }
}

#endif

#endif
