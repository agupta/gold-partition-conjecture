/*
 * Line-by-line test driver for the released classifier.
 *
 * The input is digraph6.  Each output line is C (chain), P (pair
 * certificate), T (balanced-triple certificate), or O (open).
 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

typedef uint16_t graph;
static graph bit[16];

#include "../src/gpc.c"

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
    while (fgets(line, sizeof(line), stdin)) {
        const int n = read_digraph6(line, hasse);
        if (n == 0)
            continue;

        total_count = 0;
        chain_count = 0;
        low_slave_count = 0;
        half_pair_count = 0;
        triple_count = 0;
        open_count = 0;
        classify_hasse_diagram(hasse, n);

        char outcome = 'O';
        if (chain_count)
            outcome = 'C';
        else if (low_slave_count || half_pair_count)
            outcome = 'P';
        else if (triple_count)
            outcome = 'T';
        puts((char[2]){outcome, '\0'});
    }
    return 0;
}
