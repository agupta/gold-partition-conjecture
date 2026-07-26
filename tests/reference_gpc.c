/*
 * Independent implementation of the Gold Partition certificates.
 *
 * It uses a plain dynamic program on all subsets and recomputes every
 * constrained extension count separately.  It shares no counting code with
 * src/gpc.c.  Input and output follow tests/gpc_classifier_driver.c.
 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#define NMAX 10

static int order;
static uint16_t above[NMAX];
static uint16_t below[NMAX];
static uint64_t extensions[1 << NMAX];

static uint64_t count_extensions(int first_a, int first_b,
                                 int second_a, int second_b)
{
    const unsigned full = (1u << order) - 1u;
    extensions[0] = 1;
    for (unsigned set = 1; set <= full; set++) {
        uint64_t count = 0;
        for (int x = 0; x < order; x++) {
            if (((set >> x) & 1u) == 0)
                continue;
            const unsigned previous = set & ~(1u << x);
            if (below[x] & ~previous)
                continue;
            if (x == first_b && first_a >= 0 &&
                ((previous >> first_a) & 1u) == 0)
                continue;
            if (x == second_b && second_a >= 0 &&
                ((previous >> second_a) & 1u) == 0)
                continue;
            count += extensions[previous];
        }
        extensions[set] = count;
    }
    return extensions[full];
}

static int slave_count(int x, int y)
{
    const uint16_t full = (uint16_t)((1u << order) - 1u);
    const uint16_t incomparable_x =
        (uint16_t)(full & ~(above[x] | below[x] | (1u << x)));
    const uint16_t incomparable_y =
        (uint16_t)(full & ~(above[y] | below[y] | (1u << y)));
    return __builtin_popcount((unsigned)(above[x] & incomparable_y)) +
           __builtin_popcount((unsigned)(below[y] & incomparable_x));
}

static int read_digraph6(const char *line)
{
    if (line[0] != '&')
        return 0;
    const unsigned char *input = (const unsigned char *)line + 1;
    order = (int)*input++ - 63;
    if (order < 1 || order > NMAX) {
        fprintf(stderr, "unsupported digraph6 order\n");
        exit(2);
    }
    for (int x = 0; x < order; x++)
        above[x] = 0;

    int value = 0;
    int remaining = 0;
    for (int position = 0; position < order * order; position++) {
        if (remaining == 0) {
            if (*input < 63 || *input > 126) {
                fprintf(stderr, "truncated digraph6 record\n");
                exit(2);
            }
            value = (int)*input++ - 63;
            remaining = 6;
        }
        remaining--;
        if ((value >> remaining) & 1) {
            const int x = position / order;
            const int y = position % order;
            above[x] |= (uint16_t)(1u << y);
        }
    }

    for (int pass = 0; pass < order; pass++)
        for (int x = 0; x < order; x++)
            for (int y = 0; y < order; y++)
                if ((above[x] >> y) & 1u)
                    above[x] |= above[y];
    for (int x = 0; x < order; x++)
        below[x] = 0;
    for (int x = 0; x < order; x++)
        for (int y = 0; y < order; y++)
            if ((above[x] >> y) & 1u)
                below[y] |= (uint16_t)(1u << x);
    return 1;
}

static char classify(void)
{
    int incomparable = 0;
    for (int x = 0; x < order; x++)
        for (int y = x + 1; y < order; y++)
            if (((above[x] >> y) & 1u) == 0 &&
                ((above[y] >> x) & 1u) == 0)
                incomparable = 1;
    if (!incomparable)
        return 'C';

    const uint64_t total = count_extensions(-1, -1, -1, -1);
    uint64_t pair[NMAX][NMAX] = {{0}};
    for (int x = 0; x < order; x++)
        for (int y = 0; y < order; y++) {
            if (x == y)
                continue;
            if ((above[x] >> y) & 1u)
                pair[x][y] = total;
            else if ((above[y] >> x) & 1u)
                pair[x][y] = 0;
            else if (x < y)
                pair[x][y] = count_extensions(x, y, -1, -1);
            else
                pair[x][y] = total - pair[y][x];
        }

    for (int x = 0; x < order; x++)
        for (int y = 0; y < order; y++) {
            if (x == y || ((above[x] >> y) & 1u) ||
                ((above[y] >> x) & 1u))
                continue;
            if (2 * pair[x][y] == total ||
                (2 * pair[x][y] >= total && slave_count(x, y) <= 1))
                return 'P';
        }

    for (int x = 0; x < order; x++)
        for (int y = 0; y < order; y++) {
            if (x == y || 2 * pair[y][x] > total)
                continue;
            for (int z = 0; z < order; z++) {
                if (z == x || z == y || 2 * pair[z][y] > total)
                    continue;
                const uint64_t bound =
                    pair[y][x] > pair[z][y] ? pair[y][x] : pair[z][y];
                if (count_extensions(x, y, y, z) <= bound)
                    return 'T';
            }
        }
    return 'O';
}

int main(void)
{
    char line[4096];
    while (fgets(line, sizeof(line), stdin))
        if (read_digraph6(line))
            puts((char[2]){classify(), '\0'});
    return 0;
}
