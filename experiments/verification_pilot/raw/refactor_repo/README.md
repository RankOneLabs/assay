# Self-trust refactor slice

The 17 TypeScript files here are cut from Oakridge commit
`e4dc1efe4cd76a3340ba26234fac0a213907e608`, the parent of `7491ad08` (#523, "v15 decision layer: writer
ownership, adapter registry, core/dev-flow boundary"). They are the import
closure of `oakridge-dbos/src/decision/derive.ts` plus its two test files,
with the `oakridge-dbos/` prefix removed. `package.json`,
`package-lock.json` and `tsconfig.json` are the verification pilot
slice's, which typecheck and test in the sandbox image without a database.

This is the tree before the self-trust refactor. At this commit
`derive.ts` still holds unit minting: id parsing, dependency validation,
duplicate checks and both fan-out paths. #523 deleted that code, and #529
(`b00acfdf`) rebuilt it as `adapters/cohort-roster.ts` without several of
those checks. Later fixes restored them (`efe72f8c`, `4e6bb868`,
`c5119a50`, `eb07990a`).

These files are inert input data, not a runnable fixture on their own.
`self_trust/refactor.py` generates subject workspaces from them.
