/*
 * Line-by-line test driver for the balance/majority census.
 *
 * The input is digraph6, one Hasse diagram per line, as produced by
 * `genposetg N o q`.  Each output line reports, for one poset:
 *
 *   n chain connected num den cycles_full cycles_inc
 *
 * where num/den is the reduced balance constant (0/1 for a chain) and the
 * two cycle fields are hexadecimal masks whose bit L is set exactly when the
 * majority digraph has a simple cycle on L vertices.  `cycles_full` uses the
 * full relation over all ordered pairs and `cycles_inc` the restriction to
 * incomparable pairs.
 *
 * tests/reference_census.py emits the same lines from an independent
 * brute-force implementation.
 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

typedef uint16_t graph;
static graph bit[16];

#include "../src/balance_census.c"

static int read_digraph6(const char *line, graph *hasse)
{
    if (line[0] != '&')
        return 0;
    const unsigned char *input = (const unsigned char *)line + 1;
    const int n = (int)*input++ - 63;
    if (n < 1 || n > 15) {
        fprintf(stderr, "unsupported digraph6 order\n");
        exit(2);
    }
    for (int x = 0; x < n; x++)
        hasse[x] = 0;

    int value = 0;
    int remaining = 0;
    for (int x = 0; x < n; x++)
        for (int y = 0; y < n; y++) {
            if (remaining == 0) {
                if (*input < 63 || *input > 126) {
                    fprintf(stderr, "truncated digraph6 record\n");
                    exit(2);
                }
                value = (int)*input++ - 63;
                remaining = 6;
            }
            remaining--;
            if ((value >> remaining) & 1)
                hasse[x] |= bit[y];
        }
    return n;
}

int main(void)
{
    for (int x = 0; x < 16; x++)
        bit[x] = (graph)(1u << x);

    char line[4096];
    graph hasse[16];
    uint16_t up[POSET_MAXN];

    while (fgets(line, sizeof(line), stdin)) {
        const int n = read_digraph6(line, hasse);
        if (n == 0)
            continue;

        census_upsets(hasse, n, up);
        const struct census_result result = analyze_poset(up, n);

        uint64_t num = result.num, den = result.den;
        if (result.chain) {
            num = 0;
            den = 1;
        } else {
            const uint64_t divisor = gcd64(num, den);
            num /= divisor;
            den /= divisor;
        }
        if (census_dfs_overflow_) {
            fprintf(stderr, "cycle search budget exhausted\n");
            exit(3);
        }
        printf("%d %d %d %llu %llu %04x %04x\n", n, result.chain,
               result.connected, (unsigned long long)num,
               (unsigned long long)den, (unsigned)result.cycles_full,
               (unsigned)result.cycles_inc);
    }
    return 0;
}
