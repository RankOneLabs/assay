from __future__ import annotations

from fnmatch import fnmatchcase

from oakridge_history.config import Ok, load_components, load_scope
from oakridge_history.guards import (
    check_containment,
    check_pairwise_overlap,
    check_rooting,
    check_union_coverage,
    patterns,
)
from oakridge_history.model import ComponentSpec


def _inputs() -> tuple[tuple[ComponentSpec, ...], object]:
    components = load_components()
    scope = load_scope()
    assert isinstance(components, Ok)
    assert isinstance(scope, Ok)
    return components.value, scope.value


def test_static_rooting_and_unprefixed_regression() -> None:
    components, scope = _inputs()
    assert not check_rooting(components, scope)
    bad = (*components, ComponentSpec("mistake", ("core/orchestrator/**",)))
    failures = check_rooting(bad, scope)
    assert failures and failures[0].pattern == "core/orchestrator/**"


def test_resolved_away_root_must_be_unmatched() -> None:
    components, scope = _inputs()
    missing = "oakridge-dbos/src/decision/**"
    failures = check_containment(components, scope, ("kbbl/core",), ())
    assert any(f.pattern == missing and "oakridge-dbos/src/" in f.detail for f in failures)


def test_union_coverage_exempts_only_post_rewrite_roots() -> None:
    components, scope = _inputs()
    all_patterns = patterns(components)
    post = {p for p in all_patterns if p.startswith("workflow-core/crates/")}
    assert not check_union_coverage(components, scope, (post,) * 6)
    missing = post | {"kbbl/core/orchestrator/**"}
    assert any(f.pattern == "kbbl/core/orchestrator/**"
               for f in check_union_coverage(components, scope, (missing,) * 6))


def test_committed_patterns_do_not_overlap_on_glob_witnesses() -> None:
    components, _ = _inputs()
    # A witness for each committed pattern, plus runtime files that demonstrate
    # fnmatchcase's non-path-aware '*' behavior.
    witnesses = [pattern.replace("**", "sample.py").replace("*", "sample")
                 for pattern in patterns(components)]
    witnesses += ["kbbl/core/runtime.ts", "kbbl/core/runtime-interface.ts",
                  "kbbl/core/runtime.conformance.ts"]
    assert not check_pairwise_overlap(components, witnesses)
    for path in witnesses:
        claims = [c.name for c in components if any(fnmatchcase(path, p) for p in c.patterns)]
        assert len(claims) <= 1
