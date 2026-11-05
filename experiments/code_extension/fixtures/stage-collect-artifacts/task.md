# Compile an artifact collection stage

The workflow compiler already handles delegated sessions and repository
provisioning. Add a built-in `collect_artifacts` stage type to the existing
dispatch architecture, so a workflow definition can use it without passing a
custom compiler registry.

Its configuration is a JSON object with exactly these fields:

| Field | Type | Required |
| --- | --- | --- |
| `over` | slot binding that can resolve to a collection | yes |
| `id_path` | absolute JSON pointer to each item's identifier | yes |

`over` must be a valid slot binding. A `literal` or `item` binding cannot supply
a collection when the stage materializes, so reject both. `id_path` must start
with `/` and name at least one field. Reject any other configuration, including
unknown fields, with a stage-scoped compile error.

The stage uses the existing `artifact_collection` materialization with the
configured `over` and `id_path`, and releases every declared output immediately.
The compiled executor contract's `definition_config` keeps the configuration.
Existing stage types, custom injected compiler registries, and attention
validation must keep their current behavior.

The public checks are `bun test ./tests/visible` and
`tsc --noEmit -p tsconfig.json`. The evaluator also runs private feature and
regression checks. Keep the implementation within the existing source tree. You
may add tests of your own under `tests/agent/`; they are not graded.
