# The Gold Partition Conjecture Holds through Fourteen Elements

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.21576030.svg)](https://doi.org/10.5281/zenodo.21576030)

This repository accompanies an exhaustive verification of Peczarski's Gold
Partition Conjecture for posets with at most 14 elements. It extends the
previous computational frontier of 11 elements, established in 2006.

At order 14, the verifier processed all
1,338,193,159,771 unlabeled posets. After setting aside the unique chain,
every class received one of Peczarski's certificates. Consequently, the
1/3–2/3 Conjecture holds through order 14. This is not a full census of
order-14 pair probabilities.

The repository contains:

- the [manuscript](paper/main.pdf);
- the exact C source used for the order-14 calculation;
- portable build, sharding, and aggregation tools;
- an independent small-order verifier;
- compact result and build records.

## Result

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

The build requires Bash, GNU Make, GNU coreutils, GNU time, Python 3.10 or
later, and GCC 13 or later:

```sh
curl -LO https://pallini.di.uniroma1.it/nauty2_9_1.tar.gz
printf '%s  %s\n' \
  488fa906d10a372c72d2364c5dee48e0f7307004fbe52c2bce50c52de8cd873e \
  nauty2_9_1.tar.gz | sha256sum -c -
tar xf nauty2_9_1.tar.gz
cd nauty2_9_1
./configure
make nautyS1.a
cd ..
GENPOSETG_C="$PWD/nauty2_9_1/genposetg.c" \
NAUTY_INCLUDE="$PWD/nauty2_9_1" \
NAUTY_LIB="$PWD/nauty2_9_1/nautyS1.a" \
make programs
```

The default build is portable. Set `NATIVE=1` to enable
`-march=native -funroll-loops`; the order-14 binary was built that way on
AMD EPYC 7B13 processors with GCC 13.3.0.

## Verification

Run the complete release checks with:

```sh
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
- tests the aggregator on malformed and inconsistent inputs;
- runs an end-to-end, multi-residue calculation.

The production source hashes are recorded in
[`data/gpc-n14.txt`](data/gpc-n14.txt).
The controlled timing ablation of the bilateral screen is recorded in
[`data/gpc-ablation.txt`](data/gpc-ablation.txt).
The published majority-cycle cross-check is recorded in
[`data/majority-regression.txt`](data/majority-regression.txt).

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

`src/majority_census.c` is a companion full-pair implementation used for
cross-checks and for a subsequent majority-cycle census. It is not needed for
the theorem in this release.

## Citation and license

The versioned source and data archive is available from
[Zenodo](https://doi.org/10.5281/zenodo.21576030). Citation metadata are
provided in [`CITATION.cff`](CITATION.cff). The local source is released under
the MIT License; nauty and `genposetg` remain under their upstream terms.
