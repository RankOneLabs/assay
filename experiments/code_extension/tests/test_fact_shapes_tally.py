import re
import subprocess
import sys
from dataclasses import replace

from code_extension.fact_shapes.cells import CELLS
from code_extension.fact_shapes.outcome import Held, Missed, Scored, Stopped, Unavailable, Unscored
from code_extension.fact_shapes.tally import (
    INTERVAL_LABEL,
    Count,
    Row,
    count,
    exclusions,
    h5_counts,
    import_distance_counts,
    miss_counts,
    planned_comparisons,
    render_report,
    stop_table,
    unscored_table,
)
from verification_pilot.self_trust.wilson import wilson

CELL = CELLS[0]


DEFAULT_OUTCOME = Held()


def row(outcome=DEFAULT_OUTCOME, cell=CELL, model="sol", **kwargs):
    return Row(model, cell, Scored({cell.fact_id: outcome, cell.anchor_fact_id: Held()}), **kwargs)


def test_count_and_pool():
    rows = tuple(row(o) for o in [Missed()] * 2 + [Held()] * 3 + [Unavailable()])
    rows += (Row("sol", CELL, Stopped("request_limit")),)
    assert count(rows) == Count(2, 5)
    assert str(count(rows)) == f"2 of 5 ({wilson(2, 5)})"
    assert str(count(())) == "0 of 0 (unavailable)"
    counts = miss_counts(rows)
    assert counts["sol", "type_enforced", "additive", "pooled"] == Count(2, 5)
    for attr in ("missed", "scored"):
        assert getattr(counts["sol", "type_enforced", "additive", "pooled"], attr) == sum(
            getattr(counts["sol", "type_enforced", "additive", f], attr)
            for f in ("stage", "evidence_kind", "route_permission")
        )


def test_stops_apart():
    base = (row(),)
    rows = base + (Row("sol", CELL, Unscored("broken")), Row("sol", CELL, Stopped("wall_time")))
    assert miss_counts(base) == miss_counts(rows)
    assert unscored_table(rows)["sol", "broken"] == 1
    assert stop_table(rows)["sol", "wall_time"] == 1


def test_exact_exclusion():
    for misses, excluded in ((3, False), (4, True)):
        rows = tuple(row(Missed() if i < misses else Held()) for i in range(15))
        assert exclusions(rows)[0].excluded == excluded
    for misses, excluded in ((20, False), (21, True)):
        rows = tuple(
            replace(
                row(),
                status=Scored(
                    {CELL.fact_id: Held(), CELL.anchor_fact_id: Missed() if i < misses else Held()}
                ),
            )
            for i in range(100)
        )
        assert exclusions(rows)[0].excluded == excluded
    assert not exclusions((Row("sol", CELL, Unscored("none")),))[0].excluded
    assert "not evaluable" in render_report((Row("sol", CELL, Unscored("none")),))


def test_planned_and_report():
    rows = (row(), row(Missed(), model="excluded"))
    planned = planned_comparisons(rows)
    assert re.findall(r"### (\d)\.", planned) == ["1", "2", "3", "4"]
    assert "excluded" not in planned
    first = planned.split("### 2.")[0]
    for shape in ("reference", "name_only", "sibling_only", "outside_code", "existing_state"):
        assert shape in first
    report = render_report(rows)
    assert INTERVAL_LABEL in report
    assert not re.search(r"p-value|p =|p<|significan", report, re.I)
    assert report.index("## Exploratory") > report.index("## H5")
    assert "Completion claims" not in planned
    assert "| excluded |" in report.split("## Excluded models")[1]


def test_seen_among_misses():
    rows = (row(Missed(), holder_seen=True), row(Missed()), row(Held(), holder_seen=True))
    assert count(rows, seen=True) == Count(1, 2)


def test_distance_and_h5():
    rows = tuple(row(cell=c, mirrored_state_count=2) for c in CELLS)
    distances = import_distance_counts(rows)
    assert all(key[-1] == 1 for key in distances)
    assert count(r for r in rows if r.cell.import_hops is not None).scored == 12
    assert h5_counts(rows)["sol"] == (6, 3)
    renamed = tuple(
        replace(r, mirrored_state_count=99) if r.cell.task_type == "rename" else r for r in rows
    )
    assert h5_counts(renamed) == h5_counts(rows)
    assert "reader-update" in render_report(rows)


def test_help():
    result = subprocess.run(
        [sys.executable, "-m", "code_extension.fact_shapes.tally", "--help"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "--store" in result.stdout and "--cohort" in result.stdout


def test_entry_reads_typed_variants(tmp_path, monkeypatch, capsys):
    import json
    from dataclasses import asdict
    from decimal import Decimal

    from code_extension.fact_shapes import tally
    from code_extension.fact_shapes.attempts import Fact, HolderSpec, Ok, Variant, VariantId
    from code_extension.tests.test_fact_shapes_outcome import sample

    variant = Variant(
        VariantId("variant"),
        (
            Fact(
                CELL.fact_id,
                ("fact:test: accepts",),
                CELL.shape,
                HolderSpec(CELL.holders, ("holder line",)),
            ),
        ),
    )
    attempt = replace(sample(), variant=variant)
    path = tmp_path / "cohort.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "assay-extension-cohort/0.1.0",
                "cohort": "synthetic",
                "combined_cap_usd": str(Decimal(1)),
                "plans": [
                    {
                        "name": "sol",
                        "model": "sol",
                        "plan_digest": "plan",
                        "config_digest": "config",
                        "attempts": 1,
                        "cap_usd": "1",
                        "variants": {"cell": asdict(variant)},
                        "state_fields": ["stage"],
                    }
                ],
            }
        )
    )

    def read(store, plan, variants):
        assert variants["cell"] == variant
        return Ok((attempt,))

    monkeypatch.setattr(tally, "read_attempts", read)
    monkeypatch.setattr(sys, "argv", ["tally", "--store", str(tmp_path), "--cohort", str(path)])
    tally.main()
    assert INTERVAL_LABEL in capsys.readouterr().out


def test_exclusion_denominator_is_scored_attempts():
    rows = (row(Missed()),) + tuple(row(Unavailable()) for _ in range(4))
    assert count(rows) == Count(1, 1)
    assert exclusions(rows)[0].control == Count(1, 5)
    assert not exclusions(rows)[0].excluded
