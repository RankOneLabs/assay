# Let a launch set one worker's provider deadline and start budget

Every effect instruction gives the provider the same budgets today: 10 minutes of wall
clock for each provider call, and 3 start attempts. Some agent workers need more, and
some should give up sooner. Let a run's launch configuration set both budgets for one
agent worker.

A launch's `config.sessions[stage][worker]` currently holds `{ harness, model, effort }`.
Add two optional fields to it:

| Field | Type | Required |
| --- | --- | --- |
| `deadline_ms` | positive integer, in milliseconds | no |
| `max_start_attempts` | positive integer | no |

When a worker's launch settings include `deadline_ms`, the effect instruction built for
that agent worker must carry it as its `deadline_ms`, instead of the default. The same
holds for `max_start_attempts`. Each field is independent: one that is not set keeps its
default (`DEFAULT_PROVIDER_DEADLINE_MS` or `DEFAULT_MAX_START_ATTEMPTS`). A budget belongs
to the one worker it is set on, not to the rest of its stage.

`harness` and `model` stay required. A `deadline_ms` or `max_start_attempts` that is not
a positive integer makes the configuration malformed, and a launch with it is refused.
When a field is not set, parsed configurations and the instruction's worker settings must
not gain a new key: omit it rather than setting it to `null`. Existing launch and
instruction behavior must otherwise stay the same.

The public checks are `bun test ./tests/visible` and
`tsc --noEmit -p tsconfig.json`. The evaluator also runs private feature and
regression checks. Keep the implementation within the existing source tree. You
may add tests of your own under `tests/agent/`; they are not graded.
