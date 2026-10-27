"""The fixture and PR-size restatement has a separate evidence path."""

from __future__ import annotations

from verification_pilot.self_trust import sizes


def test_size_and_framing_rows() -> None:
    rows = {r["row"]: r for r in sizes.recount()}
    assert rows["move_lines"] == {"row": "move_lines", "plain_diff": 420, "git_numstat": 420}
    cohort = rows["pr_cohort"]
    assert (cohort["cohort_prs"], cohort["all_prs"]) == (212, 634)
    assert (cohort["full_rewrite_all_percentile"],
            cohort["full_rewrite_cohort_percentile"]) == (89.4, 91.0)
    assert (cohort["move_420_all_percentile"],
            cohort["move_420_cohort_percentile"]) == (46.4, 35.8)
    assert (cohort["published_436_all_percentile"],
            cohort["published_436_cohort_percentile"]) == (47.6, 36.3)
    assert (rows["reconciler_pair"]["forge_move_lines"],
            rows["reconciler_pair"]["forge_rewrite_lines"]) == (938, 1004)
    assert rows["argon_framing"] == {"row": "argon_framing", "earlier": 6,
                                    "published": 4, "total": 10}
