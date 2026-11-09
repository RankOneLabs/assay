# Let each kbbl agent declare a default model and effort

Operators launch most sessions on the same model for a given agent, and today every request
to start a session has to name it; one that does not gets whatever the agent itself starts
on. Let an agent's entry in kbbl's config declare the model and effort a new session
requests when its request names none, and report them on `/config` so the launch form can
preselect them.

Add two optional fields to each `config.acp.agents.<id>` entry:

| Field | Type | Required |
| --- | --- | --- |
| `default_model` | non-empty string, a model id the agent advertises | no |
| `default_effort` | non-empty string, an effort id the agent advertises | no |

`null` or an absent field means no default. An empty string, or any value that is not a
string, makes the config invalid.

When a new session is started for an agent that declares a default, and its request names
no model, the session requests the agent's `default_model`, exactly as if the request had
named it. The same holds separately for effort and `default_effort`. This applies to every
way kbbl starts a new session. The default becomes the session's requested model or effort: it is recorded as
`requested_model` / `requested_effort` on the session, so it shows in the session snapshot
and is applied again whenever the agent process is respawned.

A model or effort the request names always wins over the default. So does one a resumed
session inherits from its parent (`resume_from`): the inherited value counts as named. A
default belongs to the agent that declares it; a session for another agent gets none.

The defaults do not enter `start_spec_hash`. That hash covers the request as received, the
same way the agent chosen through `acp.default_agent` and the profile's `session_mode` are
not part of it, while a model the request names explicitly is. So repeating the same keyed
request after the operator changes a default attaches to the existing session instead of
conflicting with it, and the session keeps the model it was started on.

`GET /config` reports an agent's defaults on its entry in `runtimes`, as `defaultModel` and
`defaultEffort` (strings). Omit each key when the agent declares no such default, rather
than reporting `null`; the other keys of the entry stay as they are. Code that builds an
agent profile without these fields, such as the test harness, must still compile. Existing
session, ensure and config behavior must otherwise stay the same.

The public checks are `bun test ./tests/visible` and
`tsc --noEmit -p tsconfig.json`. The evaluator also runs private feature and
regression checks. Keep the implementation within the existing source tree. You
may add tests of your own under `tests/agent/`; they are not graded.
