# Code extension experiment

This package fixes the Spec 3 domain shape before any study runs. The fixture
manifest version `assay-fixture-manifest/0.3.0` declares one factor in `arm_set`
and one or more scenarios. Each scenario pins its checkpoint slice, bounded
feature request, visible requirements and named visible and hidden test groups.
Each arm records its tree, task prompt, private reference patch and negative
controls by digest, plus three retained qualification outcomes.

`arms.py` fixes the factor tags and the first run's single `baseline` arm.
Member arm ids for other factors are declared by the manifest. Before planning,
call `manifest.require_qualified()`; before dispatch, call
`shape.validate_worker_grid` with the manifest's `arm_set` as `arm_ids`.
The grid validator requires every declared subject, arm and worker repeat
exactly once and refuses qualification-smoke subjects.

This package belongs to the existing `experiments` uv project. No runtime
image, scenario, worker dispatch or evaluator is provided here.
