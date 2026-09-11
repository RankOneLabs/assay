# Object-reference traversal

Content addressing proves byte integrity, not that every hash-looking string is
a dependency. Assay follows explicit paths according to the referring artifact's
role. An input/output artifact that happens to contain `schema_version`, `$ref`,
or fields named `output_ref` is still data, not another governed record.

| Artifact | Followed fields |
| --- | --- |
| Study snapshot | Task and three schema refs, pricing catalog, subject digest/payload refs, realization digest/artifact refs, evaluator basis/payload-schema refs |
| Execution plan | Snapshot, declaration hashes, execution conditions, cell realization refs |
| Run manifest | Plan and execution/evaluation/operating record maps |
| Execution outcome | Plan, input, output, trace, coordinate realization |
| Evaluation failure | Plan and trace |
| PAA evidence | Sources, boundary input/output, worker configuration, payload plan/base-subject/detail refs |
| PAA operating record | Sources and worker configuration |
| Report configuration | Manifests and evaluation records |
| Report | Configuration, manifests, evaluation/operating records, comparison common-subject objects |

Referenced objects retain their field-assigned role. The same bytes may be
visited in multiple roles; traversal caches distinguish them. Cycles are bounded
by visited `(content address, role)` pairs. Ordinary data strings are not visited.

## Extension data

Any JSON object in extension data may contain `assay_object_refs`, an array of
valid content addresses. This is a reserved key, not a suffix-based heuristic:

```json
{
  "description": "sha256: is ordinary text here",
  "assay_object_refs": [
    "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
  ]
}
```

These dependencies must exist, are hash-checked, and are included in export. Their
JSON dependencies use the same convention; non-JSON content is a leaf. Parseable
JSON bytes must match Assay's canonical encoding before their references
are traversed or cached. Duplicate keys, nonfinite numbers, and noncanonical
encodings are rejected, not treated as opaque leaves. This applies even to JSON
objects with no references. Opaque non-JSON artifacts remain valid leaves.

A custom field named `artifact_ref` alone is not a dependency declaration.
Producers must include that address in `assay_object_refs` as well. This replaces the previous
implicit traversal of arbitrary `sha256:` strings; re-export existing runs if
their extension data did not depend on implicit edges, otherwise rematerialize
the affected study with explicit dependencies and a new authorized plan.

## Schemas and record validation

Pinned schemas have their own traversal role. Content-addressed `$ref`,
`$dynamicRef`, and `$recursiveRef` values in schema locations are dependencies
(fragments address locations within that object). Schema applicators are visited;
instance-valued `default`, `examples`, `const`, and `enum` are not. URL schema refs
are resolved only through the pinned local registry, never fetched remotely.
Schema validation and resource resolution both default to draft-07 when `$schema`
is absent; explicit supported dialects are honored.

Traversal is separate from semantic validation. The verifier additionally checks
canonical JSON for known execution artifacts and evaluator details, valid source
addresses, required authoritative evidence lineage, and exact plan coordinates.
The closure does not prove that an evaluator scored those bytes or attest producer
identity; it verifies consistency of the supplied records and plan.
