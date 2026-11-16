"""Duplicate seeds live only in temporary copies, never in the shipped base."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from code_extension.fact_shapes.audit import audit, load_inventory

DIRECTORY = Path(__file__).resolve().parents[1] / "fact_shapes"
BASE = DIRECTORY / "base"
INVENTORY = DIRECTORY / "audit_inventory.json"


def test_clean_base() -> None:
    assert audit(BASE, load_inventory(INVENTORY)) == ()


@pytest.mark.parametrize(
    "seed",
    [
        'export type Copy = "queued" | "active" | "complete";',
        'export const copy = ["queued", "active", "complete"];',
        'export const values = ["queued", "active", "complete"] as const;',
    ],
)
def test_concept_duplicates(tmp_path: Path, seed: str) -> None:
    target = tmp_path / "copy"
    shutil.copytree(BASE, target)
    (target / "duplicate.ts").write_text(seed)
    findings = audit(target, load_inventory(INVENTORY))
    assert any(finding.name == "stage" and finding.path == "duplicate.ts" for finding in findings)


@pytest.mark.parametrize(
    "seed",
    [
        "class Mirror { buildRunning = new Set<string>(); }",
        "class Mirror { runningSessions = new Set<string>(); }",
        "CREATE TABLE mirror (id TEXT PRIMARY KEY, build_running BOOLEAN);",
    ],
)
def test_state_duplicates(tmp_path: Path, seed: str) -> None:
    target = tmp_path / "copy"
    shutil.copytree(BASE, target)
    suffix = ".sql" if seed.startswith("CREATE") else ".ts"
    (target / f"duplicate{suffix}").write_text(seed)
    assert any(
        finding.name == "session_build" for finding in audit(target, load_inventory(INVENTORY))
    )


@pytest.mark.parametrize("missing_file", [False, True])
def test_removed_declaration(tmp_path: Path, missing_file: bool) -> None:
    target = tmp_path / "copy"
    shutil.copytree(BASE, target)
    source = target / "stage/types.ts"
    if missing_file:
        source.unlink()
    else:
        source.write_text("// declaration intentionally removed\n")
    assert any(finding.name == "stage" for finding in audit(target, load_inventory(INVENTORY)))


def test_cli_and_arbitrary_root(tmp_path: Path) -> None:
    target = tmp_path / "independent"
    shutil.copytree(BASE, target)
    command = [sys.executable, str(DIRECTORY / "audit.py"), str(target), str(INVENTORY)]
    assert subprocess.run(command, capture_output=True, check=False).returncode == 0
    (target / "duplicate.ts").write_text('type Copy = "queued" | "active" | "complete";')
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert result.returncode == 1
    assert "stage" in result.stdout


@pytest.mark.parametrize(
    ("name", "table"),
    [("job_records", "jobs"), ("evidence_records", "evidence"), ("attempt_history", "attempts")],
)
def test_duplicate_state_tables(tmp_path: Path, name: str, table: str) -> None:
    target = tmp_path / "copy"
    shutil.copytree(BASE, target)
    (target / "mirror.sql").write_text(f"CREATE TABLE {table} (id TEXT PRIMARY KEY);")
    findings = audit(target, load_inventory(INVENTORY))
    assert any(finding.name == name and finding.path == "mirror.sql" for finding in findings)


@pytest.mark.parametrize("concept_name", ["stage", "evidence_kind", "route_permission"])
@pytest.mark.parametrize("quote", ['"', "'"])
def test_unauthorized_switch_copy(tmp_path: Path, concept_name: str, quote: str) -> None:
    target = tmp_path / "copy"
    shutil.copytree(BASE, target)
    inventory = load_inventory(INVENTORY)
    concept = next(item for item in inventory.concepts if item.name == concept_name)
    labels = "\n/* fall through */\n".join(
        f"case {quote}{member}{quote}:" for member in sorted(concept.members)
    )
    (target / "duplicate.ts").write_text(
        f"function copy(value: string) {{ switch (value) {{\n{labels}\n"
        "return true; default: return false; } }\n"
    )
    findings = audit(target, inventory)
    assert any(
        finding.name == concept_name and finding.path == "duplicate.ts" for finding in findings
    )


@pytest.mark.parametrize("concept_name", ["stage", "evidence_kind", "route_permission"])
@pytest.mark.parametrize("form", ["switch", "array"])
def test_candidate_switch_copies_are_rejected(tmp_path: Path, concept_name: str, form: str) -> None:
    target = tmp_path / "copy"
    shutil.copytree(BASE, target)
    inventory = load_inventory(INVENTORY)
    concept = next(item for item in inventory.concepts if item.name == concept_name)
    path = concept.candidate_holders[3]
    source = target / path
    members = sorted(concept.members)
    if form == "switch":
        labels = " ".join(f'case "{member}":' for member in members)
        seed = f"function extra(v: string) {{ switch (v) {{ {labels} return true; }} }}"
    else:
        literals = ", ".join(f'"{member}"' for member in members)
        seed = f"const extra = [{literals}];"
    source.write_text(source.read_text() + "\n" + seed)
    assert any(
        finding.name == concept_name and finding.path == path
        for finding in audit(target, inventory)
    )


def test_derived_sibling_has_no_second_declaration(tmp_path: Path) -> None:
    target = tmp_path / "copy"
    shutil.copytree(BASE, target)
    source = target / "stage/sibling.ts"
    assert "vocabularyStore.values" in source.read_text()
    assert 'case "queued"' not in source.read_text()
    assert audit(target, load_inventory(INVENTORY)) == ()


@pytest.mark.parametrize("concept_name", ["stage", "evidence_kind", "route_permission"])
@pytest.mark.parametrize("nested", [False, True])
def test_separate_return_switch_copy(tmp_path: Path, concept_name: str, nested: bool) -> None:
    target = tmp_path / "copy"
    shutil.copytree(BASE, target)
    inventory = load_inventory(INVENTORY)
    concept = next(item for item in inventory.concepts if item.name == concept_name)
    labels = "\n".join(
        f'case "{member}": {{ return "case fake: {{ }}"; }}'
        for member in sorted(concept.members)
    )
    seed = f"switch ((value)) {{ {labels} default: return false; }}"
    if nested:
        seed = f'switch (other) {{ case "outer": {{ {seed} }} }}'
    (target / "duplicate.ts").write_text(f"function copy(value: string) {{ {seed} }}")
    assert any(
        finding.name == concept_name and finding.path == "duplicate.ts"
        for finding in audit(target, inventory)
    )


def test_separate_switches_do_not_combine_members(tmp_path: Path) -> None:
    target = tmp_path / "copy"
    shutil.copytree(BASE, target)
    (target / "independent.ts").write_text(
        'switch (a) { case "queued": return 1; } '
        'switch (b) { case "active": return 2; case "complete": return 3; }'
    )
    assert audit(target, load_inventory(INVENTORY)) == ()


def test_alias_in_canonical_state_file(tmp_path: Path) -> None:
    target = tmp_path / "copy"
    shutil.copytree(BASE, target)
    source = target / "stage/state.ts"
    source.write_text(
        source.read_text() + "\nclass Mirror { runningSessions = new Set<string>(); }"
    )
    assert any(
        finding.name == "session_build" and finding.path == "stage/state.ts"
        for finding in audit(target, load_inventory(INVENTORY))
    )


@pytest.mark.parametrize("concept_name", ["stage", "evidence_kind", "route_permission"])
def test_canonical_symbol_must_own_values(tmp_path: Path, concept_name: str) -> None:
    target = tmp_path / "copy"
    shutil.copytree(BASE, target)
    inventory = load_inventory(INVENTORY)
    concept = next(item for item in inventory.concepts if item.name == concept_name)
    literals = ", ".join(f'"{member}"' for member in sorted(concept.members))
    (target / concept.declaring_file).write_text(
        f"export const {concept.symbol} = [] as const; const copy = [{literals}];"
    )
    assert any(
        finding.name == concept_name and finding.message == "missing declaration"
        for finding in audit(target, inventory)
    )


@pytest.mark.parametrize('form', ['object', 'array', 'switch', 'sql'])
def test_candidate_is_not_a_duplicate_exemption(tmp_path: Path, form: str) -> None:
    target = tmp_path / 'copy'
    shutil.copytree(BASE, target)
    seeds = {
        'object': 'const copy = { queued: 1, active: 2, complete: 3 };',
        'array': 'const copy = ["queued", "active", "complete"];',
        'switch': 'switch (v) { case "queued": case "active": case "complete": break; }',
        'sql': "CREATE TABLE copy (value TEXT CHECK (value IN ('queued', 'active', 'complete')));",
    }
    path = 'stage/001_constraint.sql' if form == 'sql' else 'stage/sibling.ts'
    source = target / path
    source.write_text(source.read_text() + '\n' + seeds[form])
    assert any(finding.path == path and 'duplicate' in finding.message
               for finding in audit(target, load_inventory(INVENTORY)))
