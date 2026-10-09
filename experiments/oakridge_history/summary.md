# Oakridge history summary

Deltas are descriptive; code presence and parser coverage can change between snapshots.

Rust files whose outgoing graph edges come only from inline `#[cfg(test)]` modules, measured by removing those modules from a temporary source copy and rebuilding the Rust graph: s1 `0`, s2 `0`, s3 `0`, s4 `0`; s5 and pre-rewrite contain no Rust files.

## s1-v2-introduced → s2-pre-dbos

- Interpretation: TypeScript test files are excluded by glob, while Rust inline `#[cfg(test)]` modules remain in the graph. Role-based Rust/TypeScript component edge and cohesion counts therefore have asymmetric test coverage; compare each role’s per-component values and raw graph with that bound in mind.

- Before: implementations: kbbl, oakridge-core; languages: rust, typescript
- After: implementations: kbbl, oakridge-core; languages: rust, typescript
- Modules: +131 / -0; edges: +386 / -10.
- Components: +2 / -0; cycles: +3 / -2.
- Cross-component edges: +92 / -5.
- New code: lines , duplicated lines , maximum nesting depth .

| Metric | Before | After | Delta |
| --- | ---: | ---: | ---: |
| radon.sloc |  |  |  |
| radon.lloc |  |  |  |
| radon.cc |  |  |  |
| radon.halstead_volume |  |  |  |
| radon.mi |  |  |  |
| complexipy.cognitive |  |  |  |
| grimp.imports |  |  |  |
| ruff.violations |  |  |  |
| ruff.magic_values |  |  |  |
| mypy.errors |  |  |  |
| jscpd.clones |  |  |  |
| jscpd.duplicated_lines |  |  |  |

## s2-pre-dbos → s3-dbos-repaired

- Interpretation: TypeScript test files are excluded by glob, while Rust inline `#[cfg(test)]` modules remain in the graph. Role-based Rust/TypeScript component edge and cohesion counts therefore have asymmetric test coverage; compare each role’s per-component values and raw graph with that bound in mind.

- Island caveat: an implementation is added or removed in this pair. System propagation cost averages over all graph islands; changing the module count `N` by adding or removing a disconnected implementation can move that scalar without a corresponding change in coupling. Inspect the per-component propagation values and raw graph in the committed reports.

- Before: implementations: kbbl, oakridge-core; languages: rust, typescript
- After: implementations: kbbl, oakridge-core, oakridge-dbos; languages: rust, typescript
- Modules: +92 / -0; edges: +333 / -0.
- Components: +1 / -0; cycles: +1 / -1.
- Cross-component edges: +119 / -0.
- New code: lines , duplicated lines , maximum nesting depth .

| Metric | Before | After | Delta |
| --- | ---: | ---: | ---: |
| radon.sloc |  |  |  |
| radon.lloc |  |  |  |
| radon.cc |  |  |  |
| radon.halstead_volume |  |  |  |
| radon.mi |  |  |  |
| complexipy.cognitive |  |  |  |
| grimp.imports |  |  |  |
| ruff.violations |  |  |  |
| ruff.magic_values |  |  |  |
| mypy.errors |  |  |  |
| jscpd.clones |  |  |  |
| jscpd.duplicated_lines |  |  |  |

## s3-dbos-repaired → s4-decision-rewrite

- Interpretation: TypeScript test files are excluded by glob, while Rust inline `#[cfg(test)]` modules remain in the graph. Role-based Rust/TypeScript component edge and cohesion counts therefore have asymmetric test coverage; compare each role’s per-component values and raw graph with that bound in mind.

- Before: implementations: kbbl, oakridge-core, oakridge-dbos; languages: rust, typescript
- After: implementations: kbbl, oakridge-core, oakridge-dbos; languages: rust, typescript
- Modules: +46 / -31; edges: +227 / -171.
- Components: +0 / -0; cycles: +0 / -0.
- Cross-component edges: +105 / -85.
- New code: lines , duplicated lines , maximum nesting depth .

| Metric | Before | After | Delta |
| --- | ---: | ---: | ---: |
| radon.sloc |  |  |  |
| radon.lloc |  |  |  |
| radon.cc |  |  |  |
| radon.halstead_volume |  |  |  |
| radon.mi |  |  |  |
| complexipy.cognitive |  |  |  |
| grimp.imports |  |  |  |
| ruff.violations |  |  |  |
| ruff.magic_values |  |  |  |
| mypy.errors |  |  |  |
| jscpd.clones |  |  |  |
| jscpd.duplicated_lines |  |  |  |

## s4-decision-rewrite → s5-single-engine

- Interpretation: TypeScript test files are excluded by glob, while Rust inline `#[cfg(test)]` modules remain in the graph. Role-based Rust/TypeScript component edge and cohesion counts therefore have asymmetric test coverage; compare each role’s per-component values and raw graph with that bound in mind.

- Island caveat: an implementation is added or removed in this pair. System propagation cost averages over all graph islands; changing the module count `N` by adding or removing a disconnected implementation can move that scalar without a corresponding change in coupling. Inspect the per-component propagation values and raw graph in the committed reports.

- Before: implementations: kbbl, oakridge-core, oakridge-dbos; languages: rust, typescript
- After: implementations: kbbl, oakridge-dbos; languages: typescript
- Modules: +31 / -174; edges: +104 / -558.
- Components: +2 / -3; cycles: +0 / -3.
- Cross-component edges: +29 / -195.
- New code: lines , duplicated lines , maximum nesting depth .

| Metric | Before | After | Delta |
| --- | ---: | ---: | ---: |
| radon.sloc |  |  |  |
| radon.lloc |  |  |  |
| radon.cc |  |  |  |
| radon.halstead_volume |  |  |  |
| radon.mi |  |  |  |
| complexipy.cognitive |  |  |  |
| grimp.imports |  |  |  |
| ruff.violations |  |  |  |
| ruff.magic_values |  |  |  |
| mypy.errors |  |  |  |
| jscpd.clones |  |  |  |
| jscpd.duplicated_lines |  |  |  |

## s5-single-engine → pre-rewrite

- Interpretation: TypeScript test files are excluded by glob, while Rust inline `#[cfg(test)]` modules remain in the graph. Role-based Rust/TypeScript component edge and cohesion counts therefore have asymmetric test coverage; compare each role’s per-component values and raw graph with that bound in mind.

- Before: implementations: kbbl, oakridge-dbos; languages: typescript
- After: implementations: kbbl, oakridge-dbos; languages: typescript
- Modules: +83 / -23; edges: +385 / -70.
- Components: +0 / -0; cycles: +2 / -1.
- Cross-component edges: +12 / -0.
- New code: lines , duplicated lines , maximum nesting depth .

| Metric | Before | After | Delta |
| --- | ---: | ---: | ---: |
| radon.sloc |  |  |  |
| radon.lloc |  |  |  |
| radon.cc |  |  |  |
| radon.halstead_volume |  |  |  |
| radon.mi |  |  |  |
| complexipy.cognitive |  |  |  |
| grimp.imports |  |  |  |
| ruff.violations |  |  |  |
| ruff.magic_values |  |  |  |
| mypy.errors |  |  |  |
| jscpd.clones |  |  |  |
| jscpd.duplicated_lines |  |  |  |
