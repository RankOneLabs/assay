# Give restricted evidence its own export allowance

The development artifact classification declares two body fields `restricted`:
`brief.files_in_scope` and `assessment.test_evidence`. Evidence collapses them to
`internal`, so export withholds them as `unclassified_content`, and an export target has no
way to opt in to them. Add restricted evidence as its own kind with its own export
allowance. On export, treat it the way the `repository_content` evidence kind is treated:
off by default, and allowed only with the raw export credential.

- **Evidence kind `restricted`.** Captured evidence selected from a body field declared
  `restricted` has kind `restricted`, not `internal`, and can be packaged like other
  captured evidence. Other declared kinds keep their current evidence kind.
- **Grade context.** Restricted evidence can be submitted in the `context` of
  `POST /v1/evaluations`, `POST /v1/evaluation-jobs` or `POST /v1/grades`, and it reaches
  export with its kind.
- **Redaction reason `restricted_content`.** On export, the content of an evidence
  reference of kind `restricted` is withheld, and its omission is recorded with reason
  `restricted_content`.
- **Policy flag `allow_restricted_content`.** A boolean on the export redaction policy,
  `false` by default. When it is `true`, restricted content is exported. It releases only
  restricted content, and no other allowance releases restricted content. The flag is
  optional on the redaction policy type: a policy built without it, as existing callers
  build one, must still compile and must withhold restricted content.
- **Export request.** `POST /v1/exports/assay` accepts
  `target.redaction_policy.allow_restricted_content`, defaulting to `false`. As with the
  other raw allowances, requesting it with anything other than the raw export credential
  is refused with 403, error code `forbidden` and message `raw export credential required`.

Existing classification, intake, redaction and export behavior must otherwise stay the
same.

The public checks are `bun test ./tests/visible` and
`tsc --noEmit -p tsconfig.json`. The evaluator also runs private feature and
regression checks. Keep the implementation within the existing source tree. You
may add tests of your own under `tests/agent/`; they are not graded.
