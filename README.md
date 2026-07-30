# Balance Constants, Majority Cycles, and the Gold Partition Conjecture through Fourteen Elements

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.21576029.svg)](https://doi.org/10.5281/zenodo.21576029)

Two exhaustive computations over all 1,338,193,159,771 unlabeled posets on
fourteen elements. The first is a census of exact balance constants and
linear-extension-majority cycles, extending by one order the complete census
of De Loof, De Baets, and De Meyer. The second verifies Peczarski's Gold
Partition Conjecture, extending his order-11 frontier from 2006.

All arithmetic is exact: no floating-point value is computed, compared, or
stored in any decision path. Every extremal witness is recomputed from the
witness string alone by a program that shares no algorithm with the census.

The repository contains:

- the [manuscript](paper/main.pdf);
- the exact GPC source and the production-equivalent released census source;
- portable build, sharding, and aggregation tools;
- independent small-order verifiers and a certificate classifier;
- compact result and build records.

## Results

Balance constants at order 14:

| quantity | value |
|---|---|
| least balance constant above 1/3 | 37/106 |
| least over posets that are not ordinal sums | 254/725, the ladder L₁₄,₁,₉ |
| classes with balance exactly 1/3 | 128 |
| classes with balance below 1/3 | 0 |
| distinct values in (1/3, 9/25] | 42, over 469 classes |
| values inside Peczarski's conjectured gap | 0 |

Majority cycles, with orders 9–13 reproducing De Loof et al.:

| order | any cycle | 3 | 4 | 5 | 6 | 7 | 8 |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 13 | 9,348,400 | 9,318,881 | 102,127 | 471 | 363 | 1 | 0 |
| 14 | 478,632,938 | 477,954,774 | 5,419,981 | 33,473 | 10,423 | 61 | 30 |

No order-14 class carries a cycle of length 9 or more.

Gold Partition certificates:

| order | unlabeled posets | pair certificate | triple certificate | open |
|---:|---:|---:|---:|---:|
| 12 | 1,104,891,746 | 1,066,006,204 | 38,885,541 | 0 |
| 13 | 33,823,827,452 | 32,418,324,910 | 1,405,502,541 | 0 |
| 14 | 1,338,193,159,771 | 1,272,077,147,789 | 66,116,011,981 | 0 |

At each order, exactly one class is a chain. “Pair certificate” is the
invariant union of the low-slave and half-balanced searches; their internal
split depends on search order.

## Build

The classifiers use the plugin interface of Brinkmann and McKay's
`genposetg`, distributed with
[nauty and Traces](https://pallini.di.uniroma1.it/). The dependency is not
vendored here. The calculation used `genposetg` 1.1 from nauty 2.9.1.
The release archive and its SHA-256 digest are:

```text
https://pallini.di.uniroma1.it/nauty2_9_1.tar.gz
488fa906d10a372c72d2364c5dee48e0f7307004fbe52c2bce50c52de8cd873e
```

The program build requires Bash, GNU Make, GNU coreutils, GNU time,
Python 3.10 or later, and GCC 13 or later.  The default `make` target also
builds the paper and therefore requires pdfLaTeX with TikZ:

```sh
curl -LO https://pallini.di.uniroma1.it/nauty2_9_1.tar.gz
printf '%s  %s\n' \
  488fa906d10a372c72d2364c5dee48e0f7307004fbe52c2bce50c52de8cd873e \
  nauty2_9_1.tar.gz | sha256sum -c -
tar xf nauty2_9_1.tar.gz
cd nauty2_9_1
./configure --enable-generic --disable-popcnt
make nautyS1.a
cd ..
export GENPOSETG_C="$PWD/nauty2_9_1/genposetg.c"
export NAUTY_INCLUDE="$PWD/nauty2_9_1"
export NAUTY_LIB="$PWD/nauty2_9_1/nautyS1.a"
make programs
```

The recipe above also keeps nauty generic.  For a machine-specific nauty
build, run its plain `./configure` instead.  This repository's default build
is portable; set `NATIVE=1` to enable
`-march=native -funroll-loops`; the order-14 binary was built that way on
AMD EPYC 7B13 processors with GCC 13.3.0. The recorded production binary
SHA-256 applies to that native environment. Portable builds reproduce the
results, but are not expected to reproduce the production binary byte for
byte.

## Verification

Run the complete release checks with:

```sh
# Uses the three nauty variables exported by the build block above.
make check
```

This command:

- generates all unlabeled posets through order 7 independently of
  `genposetg`, enumerates their linear extensions, and checks Peczarski's
  certificate conditions directly;
- compares the C classifier and a separate exact implementation on every
  poset of orders 8 and 9, using non-topological labels;
- runs the compiled GPC classifier through order 9;
- tests the full-pair classifier at order 8;
- compares the balance census against a brute-force reference that enumerates
  linear extensions directly, on every class at orders 5 through 7;
- checks the certificate classifier's pair/triple boundary against that
  reference on every poset through order 8, and against Peczarski's published
  Table I;
- tests both aggregators on malformed and inconsistent inputs;
- runs an end-to-end, multi-residue calculation.

The slower census differential extends the direct comparison through orders
8 and 9:

```sh
bash tests/check_census.sh --slow
```

The production source hashes are recorded in
[`data/gpc-n14.txt`](data/gpc-n14.txt).
The controlled timing ablation of the bilateral screen is recorded in
[`data/gpc-ablation.txt`](data/gpc-ablation.txt).
The published majority-cycle cross-check is recorded in
[`data/majority-regression.txt`](data/majority-regression.txt).
The complete order-14 census aggregate, including every extremal witness, the
full low-balance tail, and the equality representatives, is recorded in
[`data/census-n14.txt`](data/census-n14.txt).

First validate the complete shard inventory, completion metadata, payload
seals, aggregate counters, and every retained witness:

```sh
python3 scripts/aggregate_census.py 14 16384 \
  /path/to/census-n14-shards --verify all > census-n14-check.txt
```

Then recompute the complete retained-witness statistics in Sections 4 and 6
of the paper:

```sh
python3 scripts/analyze_witness_archive.py \
  /path/to/census-n14-shards --jobs 8 --check-paper
```

This checks all 44,013 distinct cycle witnesses, the 180 retained low-tail
witnesses, and the 68 equality representatives.  It reports the exact
retention rules separately; none of its witness proportions is a population
estimate over poset classes.

Regenerate the three committed figure sources from their witnesses and the
aggregate tail table with:

```sh
python3 scripts/make_census_figures.py paper/figures \
  --tail data/census-n14.txt --tail-order 14
```

## Sharded calculations

A shard is one residue of a deterministic modulus partition:

```sh
scripts/run_shard.sh gpc 11 0 16 results/gpc-n11
```

Run residues `0,...,15`, then aggregate:

```sh
scripts/aggregate.py gpc 11 16 results/gpc-n11
```

The runner records the exact binary and shard coordinates, synchronizes the
output and metadata, and publishes the completion marker last. The aggregator
requires every residue, rejects mixed binaries and incomplete runs, checks the
known number of unlabeled posets and the certificate partition, and requires
`open=0`.

`src/balance_census.c` is the census program. It computes, for every class,
the exact balance constant, the low-tail membership, and the majority-cycle
spectrum in both the full and the incomparable-pairs-only relation:

```sh
scripts/run_census_shard.sh 12 0 64 results/census-n12
scripts/aggregate_census.py 12 64 results/census-n12
```

`src/majority_census.c` is an earlier full-pair implementation retained for
cross-checks.

## Citation and license

The source and data archive is available from
[Zenodo](https://doi.org/10.5281/zenodo.21576029). That is the concept DOI and
always resolves to the latest version; each release also has its own version
DOI, recorded in the corresponding data file. Citation metadata are
provided in [`CITATION.cff`](CITATION.cff). The local source is released under
the MIT License; nauty and `genposetg` remain under their upstream terms.
