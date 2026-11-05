# Compile a status report stage

The workflow compiler already handles delegated sessions and repository
provisioning. Add a built-in `status_report` stage type to the existing dispatch
architecture, so a workflow definition can use it without passing a custom
compiler registry.

Its configuration is a JSON object with exactly these fields:

| Field | Type | Required | Default |
| --- | --- | --- | --- |
| `channel` | non-empty string | yes | none |
| `severity` | `"info"`, `"warning"` or `"error"` | no | `"info"` |
| `max_items` | positive integer | no | `20` |

Reject any other configuration, including unknown fields, with a stage-scoped
compile error. The stage materializes as one scalar unit and releases every
declared output immediately. The compiled executor contract's
`definition_config` is the normalized configuration: all three fields, with
defaults filled in. Existing stage types, custom injected compiler registries,
and attention validation must keep their current behavior.

The public checks are `bun test ./tests/visible` and
`tsc --noEmit -p tsconfig.json`. The evaluator also runs private feature and
regression checks. Keep the implementation within the existing source tree. You
may add tests of your own under `tests/agent/`; they are not graded.
