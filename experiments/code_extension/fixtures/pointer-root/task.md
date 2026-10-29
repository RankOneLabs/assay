# Accept the root fragment in the JSON pointer reader

`readJsonPointer` already accepts the empty string as a pointer to the complete
input JSON value. Accept the single character `#` as another spelling for the
complete value, including arrays, primitives, and null. All other pointer
strings retain their current behavior; in particular, `#/key` is not a valid
pointer in this request.

The public checks are `bun test ./tests/visible` and
`tsc --noEmit -p tsconfig.json`. The evaluator also runs private feature and
regression checks.
