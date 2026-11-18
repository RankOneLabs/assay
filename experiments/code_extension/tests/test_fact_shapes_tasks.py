from pathlib import Path

from code_extension.fact_shapes.alignment import (
    ALLOWLIST,
    check_alignment,
    fact_titles,
    forbidden_tokens,
    lint,
)

ROOT = Path(__file__).resolve().parents[1]


def test_tokens_and_boundaries() -> None:
    for token, source in (
        ("stage/types.ts", "path"),
        ("queued", "key literal"),
        ("acceptValue", "export"),
        ("SessionService", "class"),
    ):
        findings = lint(f"Please change {token}.", {token: (source,)})
        assert len(findings) == 1
        assert (findings[0].token, findings[0].source) == (token, source)
        assert not lint(f"prefix{token}suffix", {token: (source,)})
    assert all(ALLOWLIST.values())
    assert not lint("stage", {"stage": ("key literal",)})


def test_committed_tasks_are_intent_only() -> None:
    forbidden = forbidden_tokens(ROOT / "fact_shapes/holders.json", ROOT / "fact_shapes/base")
    tasks = sorted((ROOT / "fixtures").glob("fact-shapes-*/task.md"))
    assert len(tasks) == 6
    for task in tasks:
        assert not lint(task.read_text(), forbidden), task


def test_alignment_requires_verbatim_sentence() -> None:
    (title,) = fact_titles('test("fact:a: accepts", () => {});')
    table = f"| scenario | {title} | Accept the new value. |"
    assert not check_alignment("scenario", "Accept the new value.", (title,), table)
    assert check_alignment("scenario", "Accept the new value.", (title,), "") == (title,)
    assert check_alignment("scenario", "Other text.", (title,), table) == (title,)


def test_collector_preserves_provenance(tmp_path: Path) -> None:
    holders = tmp_path / "holders.json"
    holders.write_text(
        '[{"manipulated":{"holder_paths":["feature/holder.ts"],'
        '"fact_lines":{"feature/holder.ts":["const registry = { secret_key: true };"]}},'
        '"anchor":{"holder_paths":["feature/anchor.ts"],'
        '"fact_lines":{"feature/anchor.ts":["const anchor = true;"]}}}]'
    )
    base = tmp_path / "base"
    base.mkdir()
    (base / "service.ts").write_text(
        "export class ExampleService {}\nexport function publicEntry() {}\n"
    )
    forbidden = forbidden_tokens(holders, base)
    assert forbidden["feature/holder.ts"] == ("holders.json:path",)
    assert forbidden["holder.ts"] == ("holders.json:basename",)
    assert forbidden["secret_key"] == ("holders.json:identifier",)
    assert forbidden["ExampleService"] == ("base export:service.ts",)
    assert forbidden["publicEntry"] == ("base export:service.ts",)


def test_shared_hidden_inventory_and_patch_scope() -> None:
    from code_extension.fact_shapes.cells import CELLS
    from code_extension.fact_shapes.generate import scenario_name
    from code_extension.fixtures import load_scenario

    for scenario in dict.fromkeys(scenario_name(cell) for cell in CELLS):
        cells = [cell for cell in CELLS if scenario_name(cell) == scenario]
        root = ROOT / "fixtures" / scenario
        files = root / "hidden/new_behavior/tests/hidden/new-behavior"
        expected = {str(cell.fact_id) for cell in cells} | {str(cells[0].anchor_fact_id)}
        assert {p.name.removesuffix(".test.ts") for p in files.glob("*.test.ts")} == expected
        markdown = (ROOT / "studies/fact-shapes-2026-11/alignment.md").read_text()
        for file in files.glob("*.test.ts"):
            titles = fact_titles(file.read_text())
            assert titles and all(
                title.startswith(f"fact:{file.name.removesuffix('.test.ts')}: ") for title in titles
            )
            assert not check_alignment(scenario, (root / "task.md").read_text(), titles, markdown)
        fixtures = [load_scenario(scenario, arm_id=cell.shape) for cell in cells]
        assert len({fixture.task for fixture in fixtures}) == 1
        assert (
            len(
                {tuple(group.model_dump_json() for group in fixture.groups) for fixture in fixtures}
            )
            == 1
        )
        assert len({fixture.sidecar.writable_implementation_scope for fixture in fixtures}) == 1
        for cell, fixture in zip(cells, fixtures, strict=True):
            patches = {path.name for path in (root / "patches").glob(f"{cell.shape}.*.patch")}
            assert patches == {
                f"{cell.shape}.reference.patch",
                f"{cell.shape}.drop-{cell.fact_id}.patch",
                f"{cell.shape}.drop-{cell.anchor_fact_id}.patch",
            }
            for holder in (path for sibling in cells for path in sibling.holders):
                assert holder not in fixture.sidecar.tool_instructions
                assert all(
                    holder not in prefix for prefix in fixture.sidecar.writable_implementation_scope
                )


def test_qualified_manifests_cover_all_shapes() -> None:
    from code_extension.fact_shapes.cells import CELLS
    from code_extension.fact_shapes.generate import scenario_name

    from assay.fixture_manifest import FixtureManifestV3

    for scenario in dict.fromkeys(scenario_name(cell) for cell in CELLS):
        manifest = FixtureManifestV3.model_validate_json(
            (ROOT / "fixtures" / scenario / "qualification/manifest.json").read_bytes()
        )
        manifest.require_qualified()
        assert manifest.arm_set.factor == "code_shape"
        assert set(manifest.arm_set.arm_ids) == {
            cell.shape for cell in CELLS if scenario_name(cell) == scenario
        }


def test_real_inventory_reports_each_named_token_once() -> None:
    forbidden = forbidden_tokens(ROOT / "fact_shapes/holders.json", ROOT / "fact_shapes/base")
    for token, source in (
        ("stage/types.ts", "cells.py:path"),
        ("queued", "holders.json:key literal"),
        ("validateKey", "base export:"),
        ("SessionService", "base export:"),
    ):
        findings = lint(token, forbidden)
        assert len(findings) == 1
        assert findings[0].token == token
        assert source in findings[0].source
