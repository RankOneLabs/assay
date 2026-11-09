# Offer gated-review shortcuts only to sessions that have the server

The skills rail (`GET /sessions/:sid/skills`) lists the gated-review MCP shortcuts
(`mcp:gated-review:*`) for every live session. But a session's agent is only given the
gated-review MCP server when `OAKRIDGE_GATED_REVIEW_URL` is set in kbbl's environment and
the session's workflow identity carries a gated-review grant. A hand-started session, or a
workflow session without a grant, is offered shortcuts its agent cannot use.

Offer the gated-review shortcuts only to a session that is given the server, and decide
that with the same rule kbbl already uses to attach the server to the agent, rather than a
new copy of it:

- A session is given the server when `OAKRIDGE_GATED_REVIEW_URL` is set and the session's
  workflow identity carries a grant.
- Any other session has no gated-review shortcuts. `GET /sessions/:sid/skills` lists none of
  them, and stays `200` with the remaining list. For that session, a gated-review shortcut
  behaves as an unknown or hidden skill does.
- A session that is given the server keeps every shortcut, with its confirm gate, and they
  work as before.
- The decision depends only on whether a grant is present. Every grant kind and role gets
  the same shortcuts.
- Fixture mode (`config.skills.fixtures`) is unchanged: it lists and invokes the fixture
  skills for every session, as it does now.

kbbl reads `OAKRIDGE_GATED_REVIEW_URL` from its process environment, as it does when it
attaches the server; keep reading it there. Keep `mountSkillsRoutes(app, { acp, config })`
callable as it is. Other skills, listing and invocation behavior must stay the same.

The public checks are `bun test ./tests/visible` and
`tsc --noEmit -p tsconfig.json`. The evaluator also runs private feature and
regression checks. Keep the implementation within the existing source tree. You
may add tests of your own under `tests/agent/`; they are not graded.
