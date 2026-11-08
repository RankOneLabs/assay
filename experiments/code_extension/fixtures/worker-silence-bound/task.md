# Let a launch set one worker's silence bound

Long builds can go quiet for more than 30 minutes. The agent provider then treats the
worker's kbbl session as silent and refuses its observation as
`executor_silent_timeout`. Let a run's launch configuration raise or lower that bound for
one agent worker.

A launch's `config.sessions[stage][worker]` currently holds `{ harness, model, effort }`.
Add an optional field to it:

| Field | Type | Required |
| --- | --- | --- |
| `max_silent_ms` | positive integer, in milliseconds | no |

When a worker's launch settings include `max_silent_ms`, the agent provider must use it,
instead of its own configured bound, to decide whether that worker's session has gone
silent. A worker without it keeps the provider's bound: the provider config's
`max_silent_ms`, or the 30-minute default. The bound belongs to the one worker it is set
on, not to the rest of its stage.

`harness` and `model` stay required. A `max_silent_ms` that is not a positive integer
makes the configuration malformed, and a launch with it is refused. When the field is not
set, parsed configurations and effect instructions must not gain a new key: omit it
rather than setting it to `null`. Existing launch, instruction and provider behavior must
otherwise stay the same.

The public checks are `bun test ./tests/visible` and
`tsc --noEmit -p tsconfig.json`. The evaluator also runs private feature and
regression checks. Keep the implementation within the existing source tree. You
may add tests of your own under `tests/agent/`; they are not graded.
