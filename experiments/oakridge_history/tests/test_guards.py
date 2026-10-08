from __future__ import annotations

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


def test_committed_patterns_have_no_cross_component_overlap() -> None:
    components, _ = _inputs()
    assert not check_pairwise_overlap(components)


def test_broad_future_pattern_is_rejected_without_a_witness_path() -> None:
    components = (
        ComponentSpec("review", ("kbbl/core/review/**",)),
        ComponentSpec("future", ("kbbl/core/**",)),
    )
    failures = check_pairwise_overlap(components)
    assert len(failures) == 1
    assert failures[0].pattern == "kbbl/core/review/**"
    assert "kbbl/core/**" in failures[0].detail


def test_star_can_cross_slash_and_partial_overlap_is_detected() -> None:
    components = (
        ComponentSpec("runtime", ("kbbl/core/runtime*.ts",)),
        ComponentSpec("other", ("kbbl/core/runtime/**",)),
    )
    assert check_pairwise_overlap(components)
    assert not check_pairwise_overlap((
        ComponentSpec("runtime", ("kbbl/core/runtime*.ts",)),
        ComponentSpec("review", ("kbbl/core/review/**",)),
    ))


def test_unhandled_glob_operator_fails_closed() -> None:
    failures = check_pairwise_overlap((ComponentSpec("future", ("kbbl/core/[ab]/**",)),))
    assert failures and "unsupported" in failures[0].detail
