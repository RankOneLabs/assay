# paired-v2 reproducibility contract

Reports identify this algorithm with `statistical_profile.name = "paired-v2"`.
The former NumPy-dependent `paired-v1` is unsupported: verification rejects it
instead of interpreting an old artifact using a different sampler. Rebuild a
report under a new explicit report configuration to adopt v2; do not relabel
an existing report. Worker evidence and run manifests are unchanged.

## Sampling

The ordered population is candidate-minus-reference binary64 deltas, ordered
by the common subjects' content references. For each of the independent ASCII
domains `observed` and `null`, construct this byte prefix:

```
b"assay/paired-v2\0" + ASCII(decimal seed) + b"\0" + domain + b"\0"
```

Append a 16-byte unsigned big-endian counter starting at zero, hash with SHA-256,
and increment the counter for each block. Consume each digest as four unsigned
64-bit big-endian integers, in byte order. For population size `n`, reject words
at least `2**64 - (2**64 % n)`; otherwise the sample index is `word % n`.
Each bootstrap replicate consumes exactly `n` accepted indices. Both domains
generate `bootstrap_samples` replicates. This definition is independent of
NumPy, host byte order, vectorization, and batching.

## Arithmetic

Convert each finite binary64 delta to its exact integer ratio. Their denominators
are powers of two; use the largest denominator `D` and scale numerators to a
common integer population `x`. All replicate sums use arbitrary-precision
integers, with no intermediate floating-point summation or centering.

Let `T = sum(x)`. The reported paired effect is the rational `T / (n * D)`,
converted once to binary64. Sort the observed replicate sums. The percentile
endpoints use linear interpolation at exact ranks `(B - 1) / 40` and
`39 * (B - 1) / 40`, then divide by `n * D` and convert once to binary64.
For each null replicate sum `S`, count `abs(S - T) >= abs(T)`. The two-sided
p-value is `(1 + count) / (B + 1)`, converted once to binary64. Fraction-to-float
conversion uses Python's correctly rounded rational conversion.

This specifies the bootstrap and paired-effect arithmetic. Existing report
rules still aggregate evaluator repeats before worker repeats, use the declared
mean/median rules, require ten common subjects for inference, and apply Holm
once to the complete candidate family. Reporting uses only the paired-effect
and bootstrap primitives, not a second per-candidate aggregation pipeline.

Memory is O(n + B), without an n-by-B matrix; null replicate sums are counted
and discarded. This trades NumPy vectorization for an explicitly reproducible
algorithm. Exact sampler and hexadecimal float vectors are enforced in tests
on both supported CI Python versions.
