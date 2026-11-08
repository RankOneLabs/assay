# Add a separate export credential

`POST /v1/exports/assay` accepts any read credential, so every token that may read items
may also export them. Give export its own credential.

- **Configuration.** `credentialsFromEnv` reads a new variable,
  `OBSERVATION_EXPORT_CREDENTIALS`, in the same JSON format as the other credential
  variables: an array of `{ token, producer, namespace }`. It becomes the credentials'
  `export` list, beside `export_raw`. The list is empty when the variable is unset. A
  malformed value is refused the same way as for the other variables.
- **Uniqueness.** Each token maps to one capability, so an export token must not repeat
  any other configured token, including another export token or a raw export token.
  Startup refuses duplicates with the existing uniqueness error.
- **Export gate.** `POST /v1/exports/assay` accepts an export credential, or a raw export
  credential as it does today, and uses that credential's tenant. A read credential is no
  longer enough: it is refused with 403, error code `forbidden` and message
  `export credential required`.
- **Raw allowances.** An export credential does not grant raw allowances. Requesting
  `allow_raw_build_output`, `allow_raw_test_output` or `allow_repository_content` still
  needs the raw export credential, and is otherwise refused with 403, error code
  `forbidden` and message `raw export credential required`.

The `export` field is optional on the in-process credentials type, as `grade` and
`export_raw` are, so code that builds credentials without it keeps compiling. Other
routes and credential behavior must stay the same.

The public checks are `bun test ./tests/visible` and
`tsc --noEmit -p tsconfig.json`. The evaluator also runs private feature and
regression checks. Keep the implementation within the existing source tree. You
may add tests of your own under `tests/agent/`; they are not graded.
