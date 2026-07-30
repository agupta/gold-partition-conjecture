/*
 * Exact balance and linear-extension-majority census.
 *
 * This file is included as a genposetg plugin.  It computes one exact
 * orientation count for every incomparable pair, the balance constant,
 * and the lengths of all simple cycles in the strict majority relation.
 * Dual pairs are reduced by an inexpensive invariant; invariant ties are
 * both processed.  Ordinal sums are evaluated through their summands.
 */

#include "poset_dp.h"

struct lem_analysis {
    uint64_t best_num, best_den;
    uint16_t cycle_lengths;
    int chain;
};

static uint64_t lem_total_, lem_chain_, lem_cyclic_,
                lem_cycle_[POSET_MAXN + 1], lem_third_, lem_above_,
                lem_viol_;
static uint64_t lem_skipdual_, lem_dualpair_;
static uint64_t lem_dualtie_;

static int has_directed_cycle(const uint16_t *adj, int n)
{
    int indeg[POSET_MAXN] = {0};
    uint16_t remaining = (uint16_t)((1u << n) - 1);
    for (int x = 0; x < n; x++) {
        uint16_t t = adj[x];
        while (t) {
            const int y = __builtin_ctz(t);
            t &= (uint16_t)(t - 1);
            indeg[y]++;
        }
    }
    for (;;) {
        int x = -1;
        for (int i = 0; i < n; i++)
            if ((remaining & (1u << i)) && indeg[i] == 0) {
                x = i;
                break;
            }
        if (x < 0) break;
        remaining &= (uint16_t)~(1u << x);
        uint16_t t = adj[x] & remaining;
        while (t) {
            const int y = __builtin_ctz(t);
            t &= (uint16_t)(t - 1);
            indeg[y]--;
        }
    }
    return remaining != 0;
}

static int cycle_dfs(const uint16_t *adj, int start, int current,
                     uint16_t used, int vertices_left)
{
    if (vertices_left == 0)
        return (adj[current] >> start) & 1u;
    /* Make start the least-numbered vertex of the cycle. */
    uint16_t candidates = adj[current] & (uint16_t)~used;
    candidates &= (uint16_t)~((1u << (start + 1)) - 1u);
    while (candidates) {
        const int y = __builtin_ctz(candidates);
        candidates &= (uint16_t)(candidates - 1);
        if (cycle_dfs(adj, start, y, (uint16_t)(used | (1u << y)),
                      vertices_left - 1))
            return 1;
    }
    return 0;
}

static int has_cycle_length(const uint16_t *adj, int n, int length)
{
    for (int start = 0; start < n; start++)
        if (cycle_dfs(adj, start, start, (uint16_t)(1u << start),
                      length - 1))
            return 1;
    return 0;
}

/* The connected components of the incomparability graph are the proper
 * ordinal summands.  Relations between distinct components are total and
 * consistently oriented, so a majority cycle cannot cross components. */
static int incomparability_components(const uint16_t *up,
                                      const uint16_t *down, int n,
                                      uint16_t *components)
{
    const uint16_t full = (uint16_t)((1u << n) - 1);
    uint16_t unseen = full;
    int count = 0;
    while (unseen) {
        const int root = __builtin_ctz(unseen);
        uint16_t component = 0;
        uint16_t frontier = (uint16_t)(1u << root);
        unseen &= (uint16_t)~frontier;
        while (frontier) {
            const int x = __builtin_ctz(frontier);
            frontier &= (uint16_t)(frontier - 1);
            component |= (uint16_t)(1u << x);
            const uint16_t incomparable =
                (uint16_t)(full & ~(up[x] | down[x] | (1u << x)));
            const uint16_t add = (uint16_t)(incomparable & unseen);
            unseen &= (uint16_t)~add;
            frontier |= add;
        }
        components[count++] = component;
    }
    return count;
}

static void induced_poset(const uint16_t *up, uint16_t vertices,
                          uint16_t *sub_up, int *sub_n)
{
    int old[POSET_MAXN], n = 0;
    uint16_t t = vertices;
    while (t) {
        old[n++] = __builtin_ctz(t);
        t &= (uint16_t)(t - 1);
    }
    for (int x = 0; x < n; x++) {
        sub_up[x] = 0;
        for (int y = 0; y < n; y++)
            if ((up[old[x]] >> old[y]) & 1u)
                sub_up[x] |= (uint16_t)(1u << y);
    }
    *sub_n = n;
}

static int fraction_greater(uint64_t a, uint64_t b,
                            uint64_t c, uint64_t d)
{
    return (unsigned __int128)a * d > (unsigned __int128)c * b;
}

/*
 * Compare an isomorphism invariant of P with the same invariant of P^d.
 * A nonzero result safely chooses one member of a dual pair.  Zero is
 * deliberately inconclusive: the profile is only a filter, never an
 * isomorphism test.  Under duality the profile matrix is transposed.
 */
static int dual_invariant_cmp(const uint16_t *up, const uint16_t *down, int n)
{
    uint8_t profile[POSET_MAXN][POSET_MAXN] = {{0}};
    for (int x = 0; x < n; x++)
        profile[__builtin_popcount((unsigned)down[x])]
               [__builtin_popcount((unsigned)up[x])]++;
    for (int lower = 0; lower < n; lower++)
        for (int upper = 0; upper < n; upper++)
            if (profile[lower][upper] != profile[upper][lower])
                return profile[lower][upper] < profile[upper][lower] ? -1 : 1;
    return 0;
}

/*
 * Compute one orientation of every incomparable pair.  For x < y as
 * integer labels, pairs[x][y] is e(P + x<y); the complementary count is
 * e(P)-pairs[x][y].  The generic GPC routine computes both orientations,
 * although the second is redundant for this census.
 */
static void dp_unordered_pairs(int n, const uint16_t *up,
                               const uint16_t *down,
                               const uint16_t *ideals, int nid,
                               const uint64_t *prefix, uint64_t *back,
                               uint64_t pairs[POSET_MAXN][POSET_MAXN])
{
    const uint16_t full = (uint16_t)((1u << n) - 1);
    uint16_t incomparable_below[POSET_MAXN];
    static uint16_t available_after[1 << POSET_MAXN];
    memset(pairs, 0, sizeof(uint64_t) * POSET_MAXN * POSET_MAXN);
    for (int y = 0; y < n; y++)
        incomparable_below[y] = (uint16_t)(
            ((1u << y) - 1u) & ~(up[y] | down[y]));

    for (int k = 0; k < nid; k++) {
        const uint16_t I = ideals[k];
        uint16_t candidates = (uint16_t)(full & ~I);
        uint16_t available = 0;
        while (candidates) {
            const int y = __builtin_ctz(candidates);
            candidates &= (uint16_t)(candidates - 1);
            if (!(down[y] & ~I))
                available |= (uint16_t)(1u << y);
        }
        available_after[I] = available;
    }

    back[full] = 1;
    for (int k = nid - 2; k >= 0; k--) {
        const uint16_t I = ideals[k];
        uint16_t available = available_after[I];
        uint64_t sum = 0;
        while (available) {
            const int y = __builtin_ctz(available);
            available &= (uint16_t)(available - 1);
            sum += back[I | (1u << y)];
        }
        back[I] = sum;
    }
    if (back[0] != prefix[full]) {
        fprintf(stderr,
                "FATAL unordered-pairs total: forward=%llu backward=%llu\n",
                (unsigned long long)prefix[full],
                (unsigned long long)back[0]);
        exit(3);
    }

    for (int k = 0; k < nid - 1; k++) {
        const uint16_t I = ideals[k];
        uint16_t available = available_after[I];
        while (available) {
            const int y = __builtin_ctz(available);
            available &= (uint16_t)(available - 1);
            const uint16_t by = (uint16_t)(1u << y);
            const uint64_t weight = prefix[I] * back[I | by];
            uint16_t earlier = (uint16_t)(I & incomparable_below[y]);
            while (earlier) {
                const int x = __builtin_ctz(earlier);
                earlier &= (uint16_t)(earlier - 1);
                pairs[x][y] += weight;
            }
        }
    }
}

static struct lem_analysis analyze_poset(const uint16_t *up, int n)
{
    struct lem_analysis result = {0, 1, 0, 0};
    uint16_t down[POSET_MAXN];

    poset_downsets(up, n, down);

    uint16_t components[POSET_MAXN];
    const int component_count =
        incomparability_components(up, down, n, components);
    if (component_count == n) {
        result.chain = 1;
        return result;
    }
    if (component_count > 1) {
        for (int k = 0; k < component_count; k++) {
            if ((components[k] & (components[k] - 1)) == 0)
                continue;
            uint16_t sub_up[POSET_MAXN];
            int sub_n;
            induced_poset(up, components[k], sub_up, &sub_n);
            const struct lem_analysis sub =
                analyze_poset(sub_up, sub_n);
            result.cycle_lengths |= sub.cycle_lengths;
            if (fraction_greater(sub.best_num, sub.best_den,
                                 result.best_num, result.best_den)) {
                result.best_num = sub.best_num;
                result.best_den = sub.best_den;
            }
        }
        return result;
    }

    static uint16_t ideals[1 << POSET_MAXN], maxmask[1 << POSET_MAXN];
    static uint64_t prefix[1 << POSET_MAXN], suffix[1 << POSET_MAXN];
    static uint64_t pairs[POSET_MAXN][POSET_MAXN];
    const int nid = poset_ideals(up, down, n, ideals, maxmask);
    const uint64_t e = poset_extensions(n, ideals, maxmask, nid, prefix);
    dp_unordered_pairs(n, up, down, ideals, nid, prefix, suffix, pairs);

    uint16_t majority[POSET_MAXN] = {0};
    uint64_t best = 0;
    for (int x = 0; x < n; x++)
        for (int y = x + 1; y < n; y++) {
            if ((up[x] >> y) & 1u || (up[y] >> x) & 1u) continue;
            const uint64_t xy = pairs[x][y], yx = e - xy;
            const uint64_t balanced = xy < yx ? xy : yx;
            if (balanced > best) best = balanced;
            if (2 * xy > e) majority[x] |= (uint16_t)(1u << y);
            if (2 * yx > e) majority[y] |= (uint16_t)(1u << x);
        }
    result.best_num = best;
    result.best_den = e;

    if (has_directed_cycle(majority, n))
        for (int length = 3; length <= n; length++)
            if (has_cycle_length(majority, n, length))
                result.cycle_lengths |= (uint16_t)(1u << length);
    return result;
}

static void record_analysis(struct lem_analysis result, uint64_t mult)
{
    if (result.chain) {
        lem_chain_ += mult;
        return;
    }
    if (3 * result.best_num == result.best_den) lem_third_ += mult;
    if (3 * result.best_num > result.best_den) lem_above_ += mult;
    if (3 * result.best_num < result.best_den) lem_viol_ += mult;
    if (result.cycle_lengths) lem_cyclic_ += mult;
    for (int length = 3; length <= POSET_MAXN; length++)
        if ((result.cycle_lengths >> length) & 1u)
            lem_cycle_[length] += mult;
}

static void lem_print(FILE *f)
{
    fprintf(f,
            "LEM-FINAL total=%llu chain=%llu cyclic=%llu"
            " third=%llu above=%llu viol=%llu"
            " skipdual=%llu dualpair=%llu dualtie=%llu",
            (unsigned long long)lem_total_,
            (unsigned long long)lem_chain_,
            (unsigned long long)lem_cyclic_,
            (unsigned long long)lem_third_,
            (unsigned long long)lem_above_,
            (unsigned long long)lem_viol_,
            (unsigned long long)lem_skipdual_,
            (unsigned long long)lem_dualpair_,
            (unsigned long long)lem_dualtie_);
    for (int length = 3; length <= POSET_MAXN; length++)
        fprintf(f, " c%d=%llu", length,
                (unsigned long long)lem_cycle_[length]);
    fputc('\n', f);
}

static void lem_classify(const graph *hasse, int n)
{
    uint16_t up[POSET_MAXN];
    if (n > POSET_MAXN) {
        fprintf(stderr, "orders above %d are not supported\n", POSET_MAXN);
        exit(2);
    }
    for (int x = 0; x < n; x++) {
        up[x] = 0;
        for (int y = 0; y < n; y++)
            if (hasse[x] & bit[y])
                up[x] |= (uint16_t)(1u << y);
    }
    for (int k = 0; k < n; k++)
        for (int x = 0; x < n; x++)
            if ((up[x] >> k) & 1u)
                up[x] |= up[k];
    lem_total_++;
    uint64_t mult = 1;
    uint16_t down[POSET_MAXN];
    poset_downsets(up, n, down);
    const int invariant = dual_invariant_cmp(up, down, n);
    if (invariant < 0) {
        lem_skipdual_++;
        return;
    }
    if (invariant > 0) {
        lem_dualpair_++;
        mult = 2;
    } else {
        lem_dualtie_++;
    }
    record_analysis(analyze_poset(up, n), mult);
}

static void lem_summary(void)
{
    lem_print(stdout);
    fflush(stdout);
    if (lem_viol_)
        exit(1);
}

#define POSET_PRUNE0(pos, n) do { lem_classify((pos), (n)); return; } while (0)
#define POSET_SUMMARY lem_summary()
