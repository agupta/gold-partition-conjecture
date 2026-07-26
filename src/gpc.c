/*
 * Exact certificate-directed verifier for the Gold Partition Conjecture.
 *
 * This file is included as a genposetg plugin.  Each Hasse diagram is
 * converted to a transitive closure and tested against the three sufficient
 * conditions used by Peczarski (Order 23 (2006), 89--95).
 */

#define POSET_DP_GPC
#include "poset_dp.h"

#define MAX_PAIRS (POSET_MAXN * (POSET_MAXN - 1) / 2)
#define MAX_TRIPLES \
    (POSET_MAXN * (POSET_MAXN - 1) * (POSET_MAXN - 2))

static uint64_t total_count;
static uint64_t chain_count;
static uint64_t low_slave_count;
static uint64_t half_pair_count;
static uint64_t triple_count;
static uint64_t open_count;

static int slave_count(const uint16_t *up, const uint16_t *down,
                       int n, int x, int y)
{
    const uint16_t full = (uint16_t)((1u << n) - 1);
    const uint16_t incomparable_y =
        (uint16_t)(full & ~(up[y] | down[y] | (1u << y)));
    const uint16_t incomparable_x =
        (uint16_t)(full & ~(up[x] | down[x] | (1u << x)));
    return __builtin_popcount((unsigned)(up[x] & incomparable_y)) +
           __builtin_popcount((unsigned)(down[y] & incomparable_x));
}

/*
 * If both orientations have at most one slave, one orientation occurs in
 * at least half of the linear extensions and Peczarski's low-slave
 * condition applies.
 */
static int bilateral_low_slave(
    const uint16_t *up, const uint16_t *down, int n,
    const int *left, const int *right, int pair_count)
{
    for (int k = 0; k < pair_count; k++) {
        const int x = left[k];
        const int y = right[k];
        if (slave_count(up, down, n, x, y) <= 1 &&
            slave_count(up, down, n, y, x) <= 1)
            return 1;
    }
    return 0;
}

struct triple_candidate {
    uint64_t bound;
    uint8_t x;
    uint8_t y;
    uint8_t z;
};

static int compare_triples(const void *aa, const void *bb)
{
    const struct triple_candidate *a = aa;
    const struct triple_candidate *b = bb;
    if (a->bound != b->bound)
        return a->bound < b->bound ? 1 : -1;
    if (a->x != b->x)
        return (int)a->x - (int)b->x;
    if (a->y != b->y)
        return (int)a->y - (int)b->y;
    return (int)a->z - (int)b->z;
}

static uint64_t ordered_pair_count(
    const uint16_t *up, uint64_t pairs[POSET_MAXN][POSET_MAXN],
    uint64_t extensions, int x, int y)
{
    if ((up[x] >> y) & 1u)
        return extensions;
    if ((up[y] >> x) & 1u)
        return 0;
    return pairs[x][y];
}

static void report_open_class(const uint16_t *up, int n)
{
    const char *path = getenv("GPC_OPEN");
    FILE *out = path ? fopen(path, "a") : stderr;
    if (!out)
        return;
    fprintf(out, "OPEN %d", n);
    for (int x = 0; x < n; x++)
        fprintf(out, " %x", (unsigned)up[x]);
    fputc('\n', out);
    if (path)
        fclose(out);
}

static void verify_gpc(const uint16_t *up, int n)
{
    uint16_t down[POSET_MAXN];
    int left[MAX_PAIRS];
    int right[MAX_PAIRS];
    int pair_count = 0;

    total_count++;
    poset_downsets(up, n, down);
    for (int x = 0; x < n; x++)
        for (int y = x + 1; y < n; y++)
            if (!((up[x] >> y) & 1u) && !((up[y] >> x) & 1u)) {
                left[pair_count] = x;
                right[pair_count] = y;
                pair_count++;
            }
    if (pair_count == 0) {
        chain_count++;
        return;
    }

    if (bilateral_low_slave(up, down, n, left, right, pair_count)) {
        low_slave_count++;
        return;
    }

    static uint16_t ideals[1 << POSET_MAXN];
    static uint16_t maximal[1 << POSET_MAXN];
    static uint64_t prefix[1 << POSET_MAXN];
    static uint64_t suffix[1 << POSET_MAXN];
    static uint64_t work[1 << POSET_MAXN];
    static uint64_t pairs[POSET_MAXN][POSET_MAXN];

    const int ideal_count =
        poset_ideals(up, down, n, ideals, maximal);
    const uint64_t extensions =
        poset_extensions(n, ideals, maximal, ideal_count, prefix);

    int order[MAX_PAIRS];
    int score[MAX_PAIRS];
    for (int k = 0; k < pair_count; k++) {
        order[k] = k;
        score[k] = __builtin_popcount((unsigned)(
            (up[left[k]] ^ up[right[k]]) |
            (down[left[k]] ^ down[right[k]])));
    }
    for (int i = 1; i < pair_count; i++) {
        const int candidate = order[i];
        const int candidate_score = score[candidate];
        int j = i - 1;
        while (j >= 0 && score[order[j]] > candidate_score) {
            order[j + 1] = order[j];
            j--;
        }
        order[j + 1] = candidate;
    }

    /*
     * Test the most promising pair directly.  If it fails, one
     * forward/backward pass supplies every remaining pair count.
     */
    int all_pairs_ready = 0;
    for (int position = 0; position < pair_count; position++) {
        const int k = order[position];
        const int x = left[k];
        const int y = right[k];
        if (!all_pairs_ready && position == 1) {
            poset_all_pairs(
                n, up, down, ideals, ideal_count, prefix, suffix, pairs);
            all_pairs_ready = 1;
        }

        uint64_t xy;
        if (all_pairs_ready) {
            xy = pairs[x][y];
        } else {
            xy = poset_extensions_xy(
                ideals, maximal, ideal_count, x, y, work);
            pairs[x][y] = xy;
            pairs[y][x] = extensions - xy;
        }

        if (n >= 3 && 2 * xy == extensions) {
            half_pair_count++;
            return;
        }
        if (2 * xy >= extensions &&
            slave_count(up, down, n, x, y) <= 1) {
            low_slave_count++;
            return;
        }
        if (2 * (extensions - xy) >= extensions &&
            slave_count(up, down, n, y, x) <= 1) {
            low_slave_count++;
            return;
        }
    }

    struct triple_candidate candidates[MAX_TRIPLES];
    int candidate_count = 0;
    for (int x = 0; x < n; x++)
        for (int y = 0; y < n; y++) {
            if (x == y)
                continue;
            const uint64_t yx =
                ordered_pair_count(up, pairs, extensions, y, x);
            if (2 * yx > extensions)
                continue;
            for (int z = 0; z < n; z++) {
                if (z == x || z == y)
                    continue;
                const uint64_t zy =
                    ordered_pair_count(up, pairs, extensions, z, y);
                if (2 * zy > extensions)
                    continue;
                struct triple_candidate *candidate =
                    &candidates[candidate_count++];
                candidate->bound = yx > zy ? yx : zy;
                candidate->x = (uint8_t)x;
                candidate->y = (uint8_t)y;
                candidate->z = (uint8_t)z;
            }
        }
    qsort(candidates, (size_t)candidate_count,
          sizeof(candidates[0]), compare_triples);

    for (int k = 0; k < candidate_count; k++) {
        const int x = candidates[k].x;
        const int y = candidates[k].y;
        const int z = candidates[k].z;
        uint64_t xyz;
        if ((up[z] >> x) & 1u) {
            xyz = 0;
        } else if ((up[x] >> z) & 1u) {
            const uint64_t yx =
                ordered_pair_count(up, pairs, extensions, y, x);
            const uint64_t zy =
                ordered_pair_count(up, pairs, extensions, z, y);
            if (yx > extensions || zy > extensions - yx) {
                fprintf(stderr, "invalid triple-count identity\n");
                exit(3);
            }
            xyz = extensions - yx - zy;
        } else {
            xyz = poset_extensions_xyz(
                ideals, maximal, ideal_count, x, y, z, work);
        }
        if (xyz <= candidates[k].bound) {
            triple_count++;
            return;
        }
    }

    open_count++;
    report_open_class(up, n);
}

static void classify_hasse_diagram(const graph *hasse, int n)
{
    if (n > POSET_MAXN) {
        fprintf(stderr, "orders above %d are not supported\n", POSET_MAXN);
        exit(2);
    }

    uint16_t up[POSET_MAXN] = {0};
    for (int x = 0; x < n; x++)
        for (int y = 0; y < n; y++)
            if (hasse[x] & bit[y])
                up[x] |= (uint16_t)(1u << y);
    for (int z = 0; z < n; z++)
        for (int x = 0; x < n; x++)
            if ((up[x] >> z) & 1u)
                up[x] |= up[z];

    verify_gpc(up, n);
}

static void print_gpc_summary(void)
{
    printf(
        "GPC-FINAL total=%llu chain=%llu low_slave=%llu "
        "half_pair=%llu triple=%llu open=%llu\n",
        (unsigned long long)total_count,
        (unsigned long long)chain_count,
        (unsigned long long)low_slave_count,
        (unsigned long long)half_pair_count,
        (unsigned long long)triple_count,
        (unsigned long long)open_count);
    fflush(stdout);
    if (open_count)
        exit(1);
}

#define POSET_PRUNE0(pos, n) \
    do { classify_hasse_diagram((pos), (n)); return; } while (0)
#define POSET_SUMMARY print_gpc_summary()
