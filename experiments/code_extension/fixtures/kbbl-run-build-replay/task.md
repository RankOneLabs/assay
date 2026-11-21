Address the review comments below on your pull request. Each was left on the current state of this repository and names the file and lines it refers to.

---

Review comment (CodeRabbit) on `kbbl/prompts/planner1.md`, line 35 (also applies to line 47):

`35-35`: _⚠️ Potential issue_ | _🟡 Minor_ | _⚡ Quick win_

**Add fence languages for the HTTP examples (MD040).**

The code fences at lines 35 and 47 still lack explicit language specifiers, causing markdownlint warnings. Use `http` to satisfy the linter and improve readability.



<details>
<summary>Proposed fix</summary>

```diff
-   ```
+   ```http
    POST {{KBBL_URL}}/cohorts
    Content-Type: application/json
...
-   ```
+   ```http
    POST {{KBBL_URL}}/cohort-dependencies
    Content-Type: application/json
```
</details>


Also applies to: 47-47

<details>
<summary>🤖 Prompt for AI Agents</summary>

````
Verify each finding against current code. Fix only still-valid issues, skip the
rest with a brief reason, keep changes minimal, and validate.

In `@kbbl/prompts/planner1.md` at line 35, The markdown code fences that show the
HTTP examples (the blocks beginning with "POST {{KBBL_URL}}/cohorts" and "POST
{{KBBL_URL}}/cohort-dependencies") are missing language specifiers; update each
opening fence from ``` to ```http so the linter (MD040) is satisfied and the
examples are rendered with HTTP highlighting.
````

</details>

---

Review comment (Copilot) on `kbbl/prompts/build.md`, lines 26-34:

The build agent is only instructed to PATCH the brief debrief, but that route does not transition the parent cohort out of `building` or emit `cohort.done`; downstream cohorts only advance when `PATCH /cohorts/:id/status` sets the cohort to `done`. Add a completion step here (and include the cohort id in the prompt slots), or make the debrief route perform the completion transition, so successful builds do not leave the workflow stuck in `building`.

---

Review comment (Copilot) on `kbbl/core/pwa/review/brief/BriefReviewView.tsx`, lines 53-56:

This button is a second trigger for builds even though approving a brief already emits `brief.approved`, which `wireDispatchHooks` handles by dispatching `build`. Immediately after approval, the async hook may not have persisted `current_session_ref` yet, so clicking this can race past the route guard and spawn a duplicate session. Either make build start exclusively manual, or have this UI display/refresh the existing automatic build session and only enable rerun after it has settled or completed.

---

Review comment (Copilot) on `kbbl/core/orchestrator/dispatch-hooks.ts`, lines 27-44:

This advances the cohort to `briefing` before the planner2 dispatch has actually succeeded. If prompt loading or session creation fails, the catch below only logs the error and the cohort is left in `briefing` with no `current_session_ref`; there is no other planner2 dispatch path to retry from that state. Emit `cohort.briefing_started` only after `dispatcher.dispatch("planner2", ...)` returns a session ref, or add a real retry path that can recover failed dispatches without corrupting the state machine.

---

Review comment (Copilot) on `kbbl/core/server/handlers/builds.ts`, lines 27-42:

The double-dispatch guard is check-then-act: two concurrent POSTs can both read a null or ended `current_session_ref` here and then both call `dispatcher.dispatch`, spawning duplicate build sessions for the same cohort. Claim the cohort atomically before dispatching (for example, an `UPDATE ... WHERE current_session_ref IS NULL`/claim token followed by rollback on dispatch failure) so the endpoint enforces the single-build invariant under concurrent requests.
