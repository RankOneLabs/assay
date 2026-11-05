# Artifact collection stage compiler

Subject `oakridge-dbos-stage-collect-artifacts` asks for a built-in
`collect_artifacts` stage using the existing `artifact_collection` contract, with
a validated collection binding and identifier path. It releases outputs
immediately and keeps its configuration in the executor contract. The four arms
expose the same `task.md`, the same visible tests, and byte-identical hidden
groups.

## Provenance and included paths

The source is oakridge-dbos at immutable monorepo commit
`f3b3ffca43e43672ff2f58ab797d65c7532aaed8`. Each `repository/<arm>/` tree is the
matching `stage-pass-through` arm with only its package identity changed, so the
included paths, excluded paths and arm adaptations are the ones recorded in
`../stage-pass-through/README.md`. The hidden regression group is copied from
that fixture unchanged. No solution to another task is in these trees.

## Excluded paths

Everything that fixture excludes stays excluded: database, HTTP, DBOS runtime,
operator and integration code, and the tests that depend on them.

## Adaptations and arm complexity

The feature task, private feature check and solution are authored for this
fixture; none of them exist at the upstream pin. `code_extension/authoring.py`
derives each arm's patches and sidecar from one solution, so the arms differ only
in where the stage is registered:

| Arm | Registration edit in the reference patch |
| --- | --- |
| `modular` | One registry entry beside the compiler. |
| `central` | One case in the central switch. |
| `cross_module` | A parameter and entry in `stage-registration.ts`, and the argument at its call site. |
| `plugin` | An entry in the available compilers, and the stage name in `stage-plugin-config.json`. |

Only `modular` keeps the architecture at the pin. The other three shapes reuse
the pass-through adaptations, including the one authored plugin mechanism, so a
result here cannot separate configuration-driven enablement in general from this
one file being easy to miss. Edit count and navigation distance also differ
between arms, so architecture is not the only possible explanation of a result.

Measured from the committed start trees and reference patches:

| Arm | Start files | Start bytes | Files in reference | Added lines | Registration location |
| --- | ---: | ---: | ---: | ---: | --- |
| `modular` | 62 | 348975 | 2 | 24 | registry beside the compiler |
| `central` | 62 | 349236 | 2 | 24 | central switch |
| `cross_module` | 63 | 349469 | 3 | 26 | `stage-registration.ts` and its call site |
| `plugin` | 64 | 349587 | 3 | 25 | available compilers and JSON configuration |

## Scope and agent tests

The writable scope on all four arms is `src/` and `tests/agent/`. The solution
adds a validation module, and a reasonable one could touch `src/domain/`, so a
compiler-only scope would reject normal work. `tests/agent/` is the agent's own
namespace: the evaluator removes it before preflight, so it cannot affect a grade.
Visible tests and the root dependency and TypeScript files stay protected.

## Reachability and semantics

Each `new_behavior` test name starts with `reachability:` or `semantics:`, and
each assertion id in the sidecar carries the same prefix. The reachability test
fails only when the stage is not registered, so a compiler that is registered but
wrong passes it. Every semantics test needs a reachable stage, so a semantics
result only means something when reachability passed.

Each arm has two incomplete patches. `<arm>.negative.patch` misses the integration:
the compiler exists but normal dispatch cannot reach it, and on `plugin` it is
offered to the loader but never enabled. `<arm>.wrong-semantics.patch` is reachable
and behaves wrongly: it materializes one scalar unit instead of a collection.

## Operator qualification

`qualification/manifest.json` binds each arm's tree, task, patches and frozen
groups to its retained checks. `qualification/arms/<arm>/` holds the sidecar and
five full-path gate records: no-op, twice-reproduced controls, a scripted reference
submission through the production bridge, access probes, and a leak scan. These
records contain no model observations.

From `experiments/`, replay all arms with:

```sh
uv run python -m code_extension.qualify --scenario stage-collect-artifacts --image sha256:d0da319d2e141415c1c41ccea44983e8986944e5ae45b53652a9c104c462c4ee --verify-committed
```

To rebuild after changing the task or solution, run `code_extension.authoring` and
then the same command without `--verify-committed`. Delete nothing by hand: the
authoring step clears the generated directories.
