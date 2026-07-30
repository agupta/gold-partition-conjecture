/*
 * Exact balance and linear-extension-majority census.
 *
 * This file is included as a genposetg plugin.  For every unlabeled poset it
 * computes one exact orientation count for each incomparable pair, the exact
 * balance constant as a reduced fraction, and the set of simple-cycle lengths
 * of the linear-extension-majority digraph.
 *
 * It records, in addition to aggregate class counts:
 *
 *   - the minimum balance constant strictly above 1/3, with a witness;
 *   - the same minimum restricted to posets that are not nontrivial ordinal
 *     sums, with a witness;
 *   - a witness for every poset whose balance constant is exactly 1/3;
 *   - an exact count and witness for every distinct balance value in the low
 *     tail (1/3, tail_num/tail_den];
 *   - per-length majority-cycle counts and a witness for each length.
 *
 * All fraction comparisons use exact unsigned __int128 cross products.  No
 * floating-point arithmetic occurs anywhere in this file.
 *
 * The majority digraph is the full relation of De Loof, De Baets, and De
 * Meyer: every ordered pair with Pr[x<y] > 1/2, comparable pairs included.
 * The restricted spectrum over incomparable pairs only is reported alongside
 * it, because only the length-3 case is proved: no 3-cycle uses a comparable
 * edge, and the shortening argument closes only there.  The ordinal-sum
 * decomposition is exact for both relations.
 *
 * Witness selection is deterministic and independent of shard order: among
 * all posets attaining an extremal value, the census keeps the one whose
 * encoded strict order relation is lexicographically least.
 */

#include "poset_dp.h"

/*
 * Frozen parameters.  They are printed in the CENSUS-PARAM line and are
 * covered by the binary hash recorded with every shard.
 */
#ifndef CENSUS_TAIL_NUM
#define CENSUS_TAIL_NUM 9
#endif
#ifndef CENSUS_TAIL_DEN
#define CENSUS_TAIL_DEN 25
#endif
#ifndef CENSUS_TAIL_CAPACITY
#define CENSUS_TAIL_CAPACITY 4096
#endif
#ifndef CENSUS_TAIL_BUCKETS
#define CENSUS_TAIL_BUCKETS 16384
#endif
#ifndef CENSUS_EQUALITY_CAPACITY
#define CENSUS_EQUALITY_CAPACITY 4096
#endif
#ifndef CENSUS_DFS_BUDGET
#define CENSUS_DFS_BUDGET 4000000
#endif

#define CENSUS_VERSION 1

#ifdef CENSUS_NO_DECOMPOSE
#define CENSUS_DECOMPOSE 0
#else
#define CENSUS_DECOMPOSE 1
#endif

/* ---------------------------------------------------------------- witnesses */

struct census_witness {
    uint16_t up[POSET_MAXN];
    uint8_t n;
    uint8_t present;
};

static int witness_cmp(const struct census_witness *a,
                       const struct census_witness *b)
{
    if (a->n != b->n)
        return a->n < b->n ? -1 : 1;
    for (int x = 0; x < a->n; x++)
        if (a->up[x] != b->up[x])
            return a->up[x] < b->up[x] ? -1 : 1;
    return 0;
}

static void witness_build(struct census_witness *w, const uint16_t *up, int n)
{
    for (int x = 0; x < POSET_MAXN; x++)
        w->up[x] = x < n ? up[x] : 0;
    w->n = (uint8_t)n;
    w->present = 1;
}

/* Keep the lexicographically least encoding seen so far. */
static void witness_keep_least(struct census_witness *w,
                               const uint16_t *up, int n)
{
    struct census_witness candidate;
    witness_build(&candidate, up, n);
    if (!w->present || witness_cmp(&candidate, w) < 0)
        *w = candidate;
}

static void witness_print(FILE *f, const struct census_witness *w)
{
    if (!w->present) {
        fputs("-", f);
        return;
    }
    fprintf(f, "%u:", (unsigned)w->n);
    for (int x = 0; x < w->n; x++)
        fprintf(f, "%04x", (unsigned)w->up[x]);
}

/* ---------------------------------------------------------------- fractions */

/*
 * Balance values are num/den with den = e(P) <= 15! < 2^41 and num < den, so
 * every cross product below is far inside the range of unsigned __int128.
 */
static uint64_t gcd64(uint64_t a, uint64_t b)
{
    while (b) {
        const uint64_t r = a % b;
        a = b;
        b = r;
    }
    return a;
}

static int frac_less(uint64_t a, uint64_t b, uint64_t c, uint64_t d)
{
    return (unsigned __int128)a * d < (unsigned __int128)c * b;
}

static int frac_greater(uint64_t a, uint64_t b, uint64_t c, uint64_t d)
{
    return (unsigned __int128)a * d > (unsigned __int128)c * b;
}

static int frac_leq(uint64_t a, uint64_t b, uint64_t c, uint64_t d)
{
    return (unsigned __int128)a * d <= (unsigned __int128)c * b;
}

/* --------------------------------------------------------------- accumulator */

struct census_extremum {
    uint64_t num, den;
    struct census_witness witness;
};

struct census_tail_entry {
    uint64_t num, den;
    uint64_t count, connected_count;
    struct census_witness witness;
};

struct census_equality_entry {
    uint64_t count;
    int connected;
    struct census_witness witness;
};

static uint64_t census_total_, census_chain_, census_third_, census_above_,
                census_viol_, census_connected_, census_cyclic_,
                census_cyclic_inc_;
static uint64_t census_skipdual_, census_dualpair_, census_dualtie_;
static uint64_t census_cycle_[POSET_MAXN + 1], census_cycle_inc_[POSET_MAXN + 1];
static struct census_witness census_cycle_witness_[POSET_MAXN + 1];
static struct census_witness census_cycle_inc_witness_[POSET_MAXN + 1];
static struct census_extremum census_min_above_, census_min_connected_,
                              census_min_viol_;
static int census_max_scc_;
static uint64_t census_overflow_;
static struct census_witness census_overflow_witness_;

static struct census_tail_entry census_tail_[CENSUS_TAIL_CAPACITY];
static int census_tail_count_;
static int census_tail_bucket_[CENSUS_TAIL_BUCKETS];

static struct census_equality_entry
    census_equality_[CENSUS_EQUALITY_CAPACITY];
static int census_equality_count_;

static void census_fatal(const char *message)
{
    fprintf(stderr, "FATAL census: %s\n", message);
    exit(3);
}

static void extremum_update(struct census_extremum *m, uint64_t num,
                            uint64_t den, const uint16_t *up, int n)
{
    if (!m->witness.present || frac_less(num, den, m->num, m->den)) {
        m->num = num;
        m->den = den;
        m->witness.present = 0;
        witness_keep_least(&m->witness, up, n);
        return;
    }
    /* Values are reduced, so equality of value is equality of the pair. */
    if (num == m->num && den == m->den)
        witness_keep_least(&m->witness, up, n);
}

static void tail_record(uint64_t num, uint64_t den, uint64_t mult,
                        int connected, const uint16_t *up, int n)
{
    unsigned slot = (unsigned)((num * 1000003u + den * 65537u) &
                               (CENSUS_TAIL_BUCKETS - 1));
    for (;;) {
        const int index = census_tail_bucket_[slot];
        if (index == 0) {
            if (census_tail_count_ >= CENSUS_TAIL_CAPACITY)
                census_fatal("low-balance tail table is full");
            struct census_tail_entry *entry =
                &census_tail_[census_tail_count_];
            entry->num = num;
            entry->den = den;
            entry->count = mult;
            entry->connected_count = connected ? mult : 0;
            entry->witness.present = 0;
            witness_keep_least(&entry->witness, up, n);
            census_tail_bucket_[slot] = ++census_tail_count_;
            return;
        }
        struct census_tail_entry *entry = &census_tail_[index - 1];
        if (entry->num == num && entry->den == den) {
            entry->count += mult;
            if (connected)
                entry->connected_count += mult;
            witness_keep_least(&entry->witness, up, n);
            return;
        }
        slot = (slot + 1u) & (CENSUS_TAIL_BUCKETS - 1);
    }
}

static void equality_record(uint64_t mult, int connected,
                            const uint16_t *up, int n)
{
    if (census_equality_count_ >= CENSUS_EQUALITY_CAPACITY)
        census_fatal("equality witness table is full");
    struct census_equality_entry *entry =
        &census_equality_[census_equality_count_++];
    entry->count = mult;
    entry->connected = connected;
    entry->witness.present = 0;
    witness_keep_least(&entry->witness, up, n);
}

/* ------------------------------------------------------------ majority cycles */

static uint64_t census_dfs_budget_;
static int census_dfs_overflow_;

/*
 * Enumerate simple paths inside one strongly connected component, marking the
 * length of every simple cycle closed back to `start`.  Each cycle is found
 * exactly once because `mask` excludes every vertex below its minimum.
 */
static void cycle_paths(const uint16_t *adj, int start, int current,
                        uint16_t used, uint16_t mask, int depth,
                        uint16_t *found)
{
    if (census_dfs_budget_ == 0) {
        census_dfs_overflow_ = 1;
        return;
    }
    census_dfs_budget_--;

    if (depth >= 3 && ((adj[current] >> start) & 1u))
        *found |= (uint16_t)(1u << depth);

    uint16_t candidates = (uint16_t)(adj[current] & mask & ~used);
    while (candidates) {
        const int y = __builtin_ctz(candidates);
        candidates &= (uint16_t)(candidates - 1);
        cycle_paths(adj, start, y, (uint16_t)(used | (1u << y)), mask,
                    depth + 1, found);
    }
}

/*
 * Cycle-length spectrum of a digraph on n vertices.  Simple cycles lie inside
 * strongly connected components, so the reachability closure prunes the search
 * to the vertices that can actually carry one.
 */
static uint16_t cycle_spectrum(const uint16_t *adj, int n, int *max_scc)
{
    uint16_t reach[POSET_MAXN];
    for (int x = 0; x < n; x++)
        reach[x] = adj[x];
    for (int k = 0; k < n; k++)
        for (int x = 0; x < n; x++)
            if ((reach[x] >> k) & 1u)
                reach[x] |= reach[k];

    uint16_t on_cycle = 0;
    for (int x = 0; x < n; x++)
        if ((reach[x] >> x) & 1u)
            on_cycle |= (uint16_t)(1u << x);

    uint16_t found = 0;
    uint16_t remaining = on_cycle;
    while (remaining) {
        const int root = __builtin_ctz(remaining);
        uint16_t component = (uint16_t)(1u << root);
        uint16_t forward = (uint16_t)(reach[root] & on_cycle);
        while (forward) {
            const int y = __builtin_ctz(forward);
            forward &= (uint16_t)(forward - 1);
            if ((reach[y] >> root) & 1u)
                component |= (uint16_t)(1u << y);
        }
        remaining &= (uint16_t)~component;

        const int size = __builtin_popcount((unsigned)component);
        if (size < 3)
            continue;
        if (size > *max_scc)
            *max_scc = size;

        uint16_t starts = component;
        while (starts) {
            const int start = __builtin_ctz(starts);
            starts &= (uint16_t)(starts - 1);
            const uint16_t mask =
                (uint16_t)(component & ~((1u << start) - 1u));
            cycle_paths(adj, start, start, (uint16_t)(1u << start), mask, 1,
                        &found);
        }
    }
    return found;
}

/* ----------------------------------------------------------- poset structure */

/*
 * The connected components of the incomparability graph are the summands of
 * the finest ordinal-sum decomposition.  A poset is a nontrivial ordinal sum
 * exactly when this count exceeds one.
 */
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
                          uint16_t *sub_up, int *labels, int *sub_n)
{
    int n = 0;
    uint16_t t = vertices;
    while (t) {
        labels[n++] = __builtin_ctz(t);
        t &= (uint16_t)(t - 1);
    }
    for (int x = 0; x < n; x++) {
        sub_up[x] = 0;
        for (int y = 0; y < n; y++)
            if ((up[labels[x]] >> labels[y]) & 1u)
                sub_up[x] |= (uint16_t)(1u << y);
    }
    *sub_n = n;
}

/*
 * Compare an isomorphism invariant of P with the same invariant of its dual.
 * A nonzero result safely chooses one member of a dual pair.  Zero is
 * deliberately inconclusive: the profile is a filter, never an isomorphism
 * test.  Under duality the profile matrix is transposed.
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

/* ------------------------------------------------------------------ block DP */

static uint16_t census_ideals_[1 << POSET_MAXN];
static uint16_t census_maxmask_[1 << POSET_MAXN];
static uint16_t census_available_[1 << POSET_MAXN];
static uint64_t census_prefix_[1 << POSET_MAXN];
static uint64_t census_suffix_[1 << POSET_MAXN];
static uint64_t census_pairs_[POSET_MAXN][POSET_MAXN];

/*
 * One orientation count for every incomparable pair.  For x < y as integer
 * labels, pairs[x][y] is the number of linear extensions placing x before y;
 * the complementary count is e(P) - pairs[x][y].
 *
 * For a transition I -> I+{y}, prefix[I] * suffix[I+{y}] counts exactly the
 * extensions whose next element is y.  Adding that weight for every x in I
 * incomparable with y accumulates the extensions in which x precedes y.
 */
static void dp_unordered_pairs(int n, const uint16_t *up,
                               const uint16_t *down,
                               const uint16_t *ideals, int nid,
                               const uint64_t *prefix, uint64_t *back)
{
    const uint16_t full = (uint16_t)((1u << n) - 1);
    uint16_t incomparable_below[POSET_MAXN];
    memset(census_pairs_, 0, sizeof(census_pairs_));
    for (int y = 0; y < n; y++)
        incomparable_below[y] =
            (uint16_t)(((1u << y) - 1u) & ~(up[y] | down[y]));

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
        census_available_[I] = available;
    }

    back[full] = 1;
    for (int k = nid - 2; k >= 0; k--) {
        const uint16_t I = ideals[k];
        uint16_t available = census_available_[I];
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
                "FATAL census pair totals: forward=%llu backward=%llu\n",
                (unsigned long long)prefix[full],
                (unsigned long long)back[0]);
        exit(3);
    }

    for (int k = 0; k < nid - 1; k++) {
        const uint16_t I = ideals[k];
        uint16_t available = census_available_[I];
        while (available) {
            const int y = __builtin_ctz(available);
            available &= (uint16_t)(available - 1);
            const uint16_t by = (uint16_t)(1u << y);
            const uint64_t weight = prefix[I] * back[I | by];
            uint16_t earlier = (uint16_t)(I & incomparable_below[y]);
            while (earlier) {
                const int x = __builtin_ctz(earlier);
                earlier &= (uint16_t)(earlier - 1);
                census_pairs_[x][y] += weight;
            }
        }
    }
}

/*
 * Analyse one ordinal summand.  Returns its balance constant as num/den and
 * writes the strict-majority edges over its incomparable pairs into
 * majority[], in the summand's own labels.
 */
static void analyze_block(const uint16_t *up, int n, uint64_t *num,
                          uint64_t *den, uint16_t *majority)
{
    uint16_t down[POSET_MAXN];
    poset_downsets(up, n, down);
    const int nid =
        poset_ideals(up, down, n, census_ideals_, census_maxmask_);
    const uint64_t e =
        poset_extensions(n, census_ideals_, census_maxmask_, nid,
                         census_prefix_);
    dp_unordered_pairs(n, up, down, census_ideals_, nid, census_prefix_,
                       census_suffix_);

    for (int x = 0; x < n; x++)
        majority[x] = 0;

    uint64_t best = 0;
    for (int x = 0; x < n; x++)
        for (int y = x + 1; y < n; y++) {
            if (((up[x] >> y) & 1u) || ((up[y] >> x) & 1u))
                continue;
            const uint64_t xy = census_pairs_[x][y];
            const uint64_t yx = e - xy;
            const uint64_t balanced = xy < yx ? xy : yx;
            if (balanced > best)
                best = balanced;
            if (2 * xy > e)
                majority[x] |= (uint16_t)(1u << y);
            if (2 * yx > e)
                majority[y] |= (uint16_t)(1u << x);
        }
    *num = best;
    *den = e;
}

/* -------------------------------------------------------------- per-poset run */

struct census_result {
    uint64_t num, den;
    uint16_t cycles_full, cycles_inc;
    int chain;
    int connected;
};

static struct census_result analyze_poset(const uint16_t *up, int n)
{
    struct census_result result = {0, 1, 0, 0, 0, 0};
    uint16_t down[POSET_MAXN], components[POSET_MAXN];

    census_dfs_budget_ = CENSUS_DFS_BUDGET;
    census_dfs_overflow_ = 0;

    poset_downsets(up, n, down);
    const int component_count =
        incomparability_components(up, down, n, components);
    result.connected = component_count == 1;
    if (component_count == n) {
        result.chain = 1;
        return result;
    }

    uint16_t majority_inc[POSET_MAXN];
    uint16_t majority_full[POSET_MAXN];
    for (int x = 0; x < n; x++) {
        majority_inc[x] = 0;
        /* Every comparable pair x < y has Pr[x<y] = 1 > 1/2. */
        majority_full[x] = up[x];
    }

    const int blocks = CENSUS_DECOMPOSE ? component_count : 1;
    for (int k = 0; k < blocks; k++) {
        const uint16_t vertices = CENSUS_DECOMPOSE
            ? components[k]
            : (uint16_t)((1u << n) - 1);
        if (__builtin_popcount((unsigned)vertices) < 2)
            continue;

        uint16_t sub_up[POSET_MAXN], sub_majority[POSET_MAXN];
        int labels[POSET_MAXN], sub_n;
        uint64_t sub_num, sub_den;

        induced_poset(up, vertices, sub_up, labels, &sub_n);
        analyze_block(sub_up, sub_n, &sub_num, &sub_den, sub_majority);

        for (int x = 0; x < sub_n; x++) {
            uint16_t t = sub_majority[x];
            while (t) {
                const int y = __builtin_ctz(t);
                t &= (uint16_t)(t - 1);
                majority_inc[labels[x]] |= (uint16_t)(1u << labels[y]);
            }
        }
        if (frac_greater(sub_num, sub_den, result.num, result.den)) {
            result.num = sub_num;
            result.den = sub_den;
        }
    }

    for (int x = 0; x < n; x++)
        majority_full[x] |= majority_inc[x];

    result.cycles_full = cycle_spectrum(majority_full, n, &census_max_scc_);
    result.cycles_inc = cycle_spectrum(majority_inc, n, &census_max_scc_);
    return result;
}

static void record_analysis(const struct census_result *result, uint64_t mult,
                            const uint16_t *up, int n)
{
    if (result->chain) {
        census_chain_ += mult;
        return;
    }
    if (result->connected)
        census_connected_ += mult;

    uint64_t num = result->num, den = result->den;
    if (num == 0)
        census_fatal("non-chain poset with a zero balance numerator");
    const uint64_t divisor = gcd64(num, den);
    num /= divisor;
    den /= divisor;

    const unsigned __int128 three = (unsigned __int128)3 * num;
    if (three == den) {
        census_third_ += mult;
        equality_record(mult, result->connected, up, n);
    } else if (three > den) {
        census_above_ += mult;
        extremum_update(&census_min_above_, num, den, up, n);
        if (result->connected)
            extremum_update(&census_min_connected_, num, den, up, n);
        if (frac_leq(num, den, CENSUS_TAIL_NUM, CENSUS_TAIL_DEN))
            tail_record(num, den, mult, result->connected, up, n);
    } else {
        census_viol_ += mult;
        extremum_update(&census_min_viol_, num, den, up, n);
    }

    if (result->cycles_full)
        census_cyclic_ += mult;
    if (result->cycles_inc)
        census_cyclic_inc_ += mult;
    for (int length = 3; length <= POSET_MAXN; length++) {
        if ((result->cycles_full >> length) & 1u) {
            census_cycle_[length] += mult;
            witness_keep_least(&census_cycle_witness_[length], up, n);
        }
        if ((result->cycles_inc >> length) & 1u) {
            census_cycle_inc_[length] += mult;
            witness_keep_least(&census_cycle_inc_witness_[length], up, n);
        }
    }

    if (census_dfs_overflow_) {
        census_overflow_ += mult;
        witness_keep_least(&census_overflow_witness_, up, n);
    }
}

/* Strict transitive closure of a Hasse diagram, in genposetg's labels. */
static void census_upsets(const graph *hasse, int n, uint16_t *up)
{
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
}

static void census_classify(const graph *hasse, int n)
{
    uint16_t up[POSET_MAXN];
    census_upsets(hasse, n, up);

    census_total_++;

    uint64_t mult = 1;
    uint16_t down[POSET_MAXN];
    poset_downsets(up, n, down);
    const int invariant = dual_invariant_cmp(up, down, n);
    if (invariant < 0) {
        census_skipdual_++;
        return;
    }
    if (invariant > 0) {
        census_dualpair_++;
        mult = 2;
    } else {
        census_dualtie_++;
    }

    const struct census_result result = analyze_poset(up, n);
    record_analysis(&result, mult, up, n);
}

/* --------------------------------------------------------------- output */

static int tail_order(const void *lhs, const void *rhs)
{
    const struct census_tail_entry *a = lhs, *b = rhs;
    if (frac_less(a->num, a->den, b->num, b->den))
        return -1;
    if (frac_greater(a->num, a->den, b->num, b->den))
        return 1;
    if (a->num != b->num)
        return a->num < b->num ? -1 : 1;
    if (a->den != b->den)
        return a->den < b->den ? -1 : 1;
    return 0;
}

static int equality_order(const void *lhs, const void *rhs)
{
    const struct census_equality_entry *a = lhs, *b = rhs;
    return witness_cmp(&a->witness, &b->witness);
}

static void census_print_extremum(FILE *f, const char *kind,
                                  const struct census_extremum *m)
{
    if (!m->witness.present)
        return;
    fprintf(f, "CENSUS-MIN kind=%s num=%llu den=%llu witness=", kind,
            (unsigned long long)m->num, (unsigned long long)m->den);
    witness_print(f, &m->witness);
    fputc('\n', f);
}

static void census_print(FILE *f, int order)
{
    fprintf(f,
            "CENSUS-PARAM version=%d n=%d maxn=%d tail_num=%d tail_den=%d"
            " tail_capacity=%d equality_capacity=%d dfs_budget=%lld"
            " decompose=%d\n",
            CENSUS_VERSION, order, POSET_MAXN, CENSUS_TAIL_NUM,
            CENSUS_TAIL_DEN, CENSUS_TAIL_CAPACITY, CENSUS_EQUALITY_CAPACITY,
            (long long)CENSUS_DFS_BUDGET, CENSUS_DECOMPOSE);

    fprintf(f,
            "CENSUS-FINAL total=%llu chain=%llu third=%llu above=%llu"
            " viol=%llu connected=%llu cyclic=%llu cyclic_inc=%llu"
            " skipdual=%llu dualpair=%llu dualtie=%llu"
            " tail_values=%d equality_classes=%d maxscc=%d overflow=%llu",
            (unsigned long long)census_total_,
            (unsigned long long)census_chain_,
            (unsigned long long)census_third_,
            (unsigned long long)census_above_,
            (unsigned long long)census_viol_,
            (unsigned long long)census_connected_,
            (unsigned long long)census_cyclic_,
            (unsigned long long)census_cyclic_inc_,
            (unsigned long long)census_skipdual_,
            (unsigned long long)census_dualpair_,
            (unsigned long long)census_dualtie_,
            census_tail_count_, census_equality_count_, census_max_scc_,
            (unsigned long long)census_overflow_);
    for (int length = 3; length <= POSET_MAXN; length++)
        fprintf(f, " c%d=%llu", length,
                (unsigned long long)census_cycle_[length]);
    for (int length = 3; length <= POSET_MAXN; length++)
        fprintf(f, " i%d=%llu", length,
                (unsigned long long)census_cycle_inc_[length]);
    fputc('\n', f);

    census_print_extremum(f, "above", &census_min_above_);
    census_print_extremum(f, "above_connected", &census_min_connected_);
    census_print_extremum(f, "violation", &census_min_viol_);

    qsort(census_tail_, (size_t)census_tail_count_,
          sizeof(census_tail_[0]), tail_order);
    for (int k = 0; k < census_tail_count_; k++) {
        const struct census_tail_entry *entry = &census_tail_[k];
        fprintf(f, "CENSUS-TAIL num=%llu den=%llu count=%llu connected=%llu"
                   " witness=",
                (unsigned long long)entry->num,
                (unsigned long long)entry->den,
                (unsigned long long)entry->count,
                (unsigned long long)entry->connected_count);
        witness_print(f, &entry->witness);
        fputc('\n', f);
    }

    qsort(census_equality_, (size_t)census_equality_count_,
          sizeof(census_equality_[0]), equality_order);
    for (int k = 0; k < census_equality_count_; k++) {
        const struct census_equality_entry *entry = &census_equality_[k];
        fprintf(f, "CENSUS-EQUALITY count=%llu connected=%d witness=",
                (unsigned long long)entry->count, entry->connected);
        witness_print(f, &entry->witness);
        fputc('\n', f);
    }

    for (int length = 3; length <= POSET_MAXN; length++) {
        if (census_cycle_[length]) {
            fprintf(f, "CENSUS-CYCLE relation=full length=%d count=%llu"
                       " witness=",
                    length, (unsigned long long)census_cycle_[length]);
            witness_print(f, &census_cycle_witness_[length]);
            fputc('\n', f);
        }
        if (census_cycle_inc_[length]) {
            fprintf(f, "CENSUS-CYCLE relation=inc length=%d count=%llu"
                       " witness=",
                    length, (unsigned long long)census_cycle_inc_[length]);
            witness_print(f, &census_cycle_inc_witness_[length]);
            fputc('\n', f);
        }
    }

    if (census_overflow_) {
        fprintf(f, "CENSUS-OVERFLOW count=%llu witness=",
                (unsigned long long)census_overflow_);
        witness_print(f, &census_overflow_witness_);
        fputc('\n', f);
    }
}

static int census_order_;

static void census_summary(void)
{
    census_print(stdout, census_order_);
    fflush(stdout);
    if (census_viol_)
        exit(1);
    if (census_overflow_)
        exit(1);
}

#define POSET_PRUNE0(pos, n) \
    do { census_order_ = (n); census_classify((pos), (n)); return; } while (0)
#define POSET_SUMMARY census_summary()
