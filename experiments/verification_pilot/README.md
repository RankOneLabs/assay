# Verification pilot Tier 1 fixture

The pilot pins the wf-13 oakridge-dbos slice and declares four symbol
migrations over it. `fixture.load_fixture()` validates file and byte limits,
recomputes the tree digest, and checks every declared use site. The rename
generator produces a complete renamed tree; `ground_truth.py` then injects
three deliberate remnants and three decoys for verification experiments.

The Part 2 path-overlap test is deferred pending the frozen 2b anchor list.
