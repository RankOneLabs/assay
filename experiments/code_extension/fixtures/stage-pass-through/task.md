# Compile a pass-through stage

The workflow compiler already handles delegated sessions and repository
provisioning. Add a built-in `pass_through` stage type to the existing dispatch
architecture. Its configuration is exactly an empty JSON object; reject any
other configuration with a stage-scoped compile error. It materializes as one
scalar unit, releases every declared output immediately, and preserves the
empty configuration in the compiled executor contract. Existing stage types,
custom injected compiler registries, and attention validation must keep their
current behavior.

The public checks are `bun test ./tests/visible` and
`tsc --noEmit -p tsconfig.json`. The evaluator also runs private feature and
regression checks. Keep the implementation within the existing source tree.
