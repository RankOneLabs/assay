"""Per-fact qualification controls with pure verdicts and fresh Docker replays.

Retained evidence contains actual group statuses, parsed fact titles and replayed
typecheck diagnostics. Missing output never counts as a proven omission.
"""

from dataclasses import dataclass
from typing import cast

from code_extension.fact_shapes.attempts import Fact, Group
from code_extension.fact_shapes.budget import Err, Ok, Result
from code_extension.fact_shapes.cells import Cell, FactId, Shape
from code_extension.fact_shapes.outcome import (
    Held,
    Missed,
    Scored,
    diagnostics,
    fact_titles,
    parse_titles,
    preflight_status,
)
from code_extension.fixtures import ScenarioFixture


@dataclass(frozen=True)
class Run:
    groups: dict[str, Group]
    preflight_cause: str | None = None
    typecheck_output: str = ""


@dataclass(frozen=True)
class Verdict:
    arm: str
    patch: str
    fact: FactId | None
    passed: bool
    reason: str


def verdict(
    arm: str,
    patch: str,
    facts: tuple[Fact, ...],
    runs: tuple[Run, ...],
    dropped: FactId | None = None,
    *,
    allow_preflight: bool = True,
) -> Result[Verdict, Verdict]:
    """Accept exactly the declared omission twice, including holder-only preflight."""

    def refuse(reason: str, fact: FactId | None = dropped) -> Err[Verdict]:
        return Err(Verdict(arm, patch, fact, False, reason))

    if len(runs) != 2:
        return refuse("exactly two fresh sandbox runs are required")
    if not facts or len({fact.id for fact in facts}) != len(facts):
        return refuse("facts must be nonempty and unique")
    if dropped is not None and dropped not in {fact.id for fact in facts}:
        return refuse("unknown dropped fact")
    signatures: list[tuple[tuple[str, str], ...]] = []
    for run in runs:
        if run.preflight_cause is not None:
            if not allow_preflight:
                return refuse("this control requires fact title outcomes, not preflight")
            control = next(
                (f for f in facts if f.id == dropped and f.shape == "type_enforced"), None
            )
            errors = diagnostics(run.typecheck_output)
            if (
                control is None
                or not errors
                or any(e.file.removeprefix("./") not in control.holder.paths for e in errors)
            ):
                return refuse(
                    "preflight diagnostics must be confined to the dropped control holder"
                )
            status = preflight_status(run.preflight_cause, errors, facts)
            if not isinstance(status, Scored) or not isinstance(
                status.facts.get(control.id), Missed
            ):
                return refuse("preflight classifier did not identify the control miss")
            signatures.append(((str(control.id), "preflight_missed"),))
            continue
        for name in ("visible_regression", "hidden_regression"):
            group = run.groups.get(name)
            if group is None or group.status != "passed":
                return refuse(f"{name} did not pass")
        behavior = run.groups.get("new_behavior")
        if behavior is None or behavior.status not in {"passed", "failed"}:
            return refuse("new_behavior did not run")
        observed = parse_titles(behavior.stdout, behavior.stderr)
        for fact in facts:
            expected_status = "fail" if fact.id == dropped else "pass"
            for title in fact.titles:
                statuses = {status for status, name in observed if name == title}
                if statuses != {expected_status}:
                    return refuse("missing or conflicting fact title outcome", fact.id)
        outcomes = fact_titles(facts, behavior.stdout, behavior.stderr, ran=True)
        for fact in facts:
            expected = Missed if fact.id == dropped else Held
            if not isinstance(outcomes[fact.id], expected):
                return refuse("unexpected fact outcome", fact.id)
        if dropped is not None and behavior.status != "failed":
            return refuse("new_behavior group status disagrees with expected omission")
        signatures.append(tuple(sorted((str(key), value.kind) for key, value in outcomes.items())))
    if signatures[0] != signatures[1]:
        return refuse("fresh sandbox runs disagree")
    return Ok(Verdict(arm, patch, dropped, True, "both replays satisfy the expected fact outcomes"))


def alternative_control(
    cell: Cell,
    before: dict[str, str],
    complete: dict[str, str],
) -> tuple[str, str]:
    """Construct an independent type drop, follow-up migration or stale state copy.

    ``complete`` is the type-enforced omission tree for that shape, and the
    reference tree otherwise.
    """
    import difflib

    from code_extension.fact_shapes.switches import LABEL_MAPS, label_type

    after = dict(complete)
    if cell.shape == "type_enforced":
        # Start from the ordinary omission, whose label map lacks the new key, and
        # cast that unchanged literal so the repository type-checks. The hidden
        # fact test must then detect the missing label at run time.
        path: str = cell.holders[0]
        labels, type_name = LABEL_MAPS[cell.feature], label_type(cell.feature)
        declaration = f"export const {labels}: Record<{type_name}, string> = {{"
        if after[path].count(declaration) != 1 or after[path].count(" };\n") != 1:
            raise ValueError(f"{path}: label map literal not found")
        after[path] = after[path].replace(declaration, f"export const {labels} = {{").replace(
            " };\n", f" }} as unknown as Record<{type_name}, string>;\n"
        )
        label = "type-without-required-feature.patch"
    elif cell.shape == "outside_code":
        import re

        path = cell.holders[0]
        after[path] = before[path]
        # The constrained table: the feature's lookup table, or a stage-coded settings table.
        table = f"{cell.feature}_values"
        if f"CREATE TABLE {table} (" not in before[path]:
            found = re.search(r"CREATE TABLE (?:IF NOT EXISTS )?(\w+) \(", before[path])
            if found is None:
                raise ValueError(f"{path}: no table in the migration holder")
            table = found.group(1)
        header = re.search(rf"CREATE TABLE (?:IF NOT EXISTS )?{table} \(", complete[path])
        if header is None:
            raise ValueError(f"{path}: {table} missing from the reference migration")
        directory = path.rsplit("/", 1)[0]
        count = sum(1 for name in before if name.startswith(directory + "/"))
        # Only this table, from the reference's (possibly shared) migration.
        statement = complete[path][header.end():].split("\n);\n", 1)[0]
        column = "value" if table.endswith("_values") else "days"
        after[f"{directory}/{count + 1:03d}_allow_{table}.sql"] = (
            f"ALTER TABLE {table} RENAME TO previous_values;\n"
            + f"CREATE TABLE {table} ({statement}\n);\n"
            + f"INSERT INTO {table} SELECT * FROM previous_values;\n"
            + "DROP TABLE previous_values;\n"
        )
        after[f"{directory}/{count + 2:03d}_index_{table}.sql"] = (
            f"CREATE INDEX {table}_{column}_index ON {table}({column});\n"
        )
        label = "follow-up-migration.patch"
    else:
        if cell.feature == "stage":
            # The reference's reader follows the stored row; keep a copy for the new stage.
            path = str(cell.holders[0])
            if after[path].count("  read(job: Job): Job {\n") != 1:
                raise ValueError(f"{path}: export reader not found")
            source = after[path].replace(
                "  read(job: Job): Job {\n",
                "  private readonly featureCopies = new Map<string, Job>();\n"
                "  read(job: Job): Job {\n"
                '    if (job.stage === "triaged") {\n'
                "      const copy = this.featureCopies.get(job.id) ?? job;\n"
                "      this.featureCopies.set(job.id, copy);\n"
                "      return copy;\n"
                "    }\n",
            )
        else:
            path = str(cell.holders[0])
            name, value = (
                ("StoredEvidenceKind", "attestation")
                if cell.feature == "evidence_kind"
                else ("StoredRoutePermission", "case_inspect")
            )
            type_name = label_type(cell.feature)
            declaration = f"export class {name} extends SavedDefaults<{type_name}> {{\n"
            if after[path].count(declaration) != 1:
                raise ValueError(f"{path}: {name} not found")
            source = after[path].replace(
                declaration,
                declaration
                + f"  private readonly featureCopy = new Map<string, {type_name}>();\n"
                f"  override set(key: string, value: {type_name}): void {{\n"
                "    super.set(key, value);\n"
                f'    if (value === "{value}") this.featureCopy.set(key, value);\n'
                "  }\n"
                f"  override get(key: string): {type_name} | undefined {{\n"
                "    return this.featureCopy.get(key) ?? super.get(key);\n"
                "  }\n",
            )
        after[path] = source
        label = "duplicate-state.patch"
    result = ""
    for file_path in sorted(before.keys() | after.keys()):
        path = file_path
        if before.get(path) != after.get(path):
            result += f"diff --git a/{path} b/{path}\n"
            if path not in before:
                result += "new file mode 100644\n"
            result += "".join(
                difflib.unified_diff(
                    before.get(path, "").splitlines(True),
                    after.get(path, "").splitlines(True),
                    fromfile=f"a/{path}" if path in before else "/dev/null",
                    tofile=f"b/{path}",
                )
            )
    return label, result


async def run_control(fixture: "ScenarioFixture", image: str, patch: str) -> Run:
    """Run a control in a fresh Docker sandbox, replaying typecheck if necessary."""
    import tempfile
    from pathlib import Path

    from code_extension.diagnose import TYPECHECK, _run
    from code_extension.fixture import materialize
    from code_extension.qualify import _patched_digest, make_runner

    result = await make_runner(image).run(
        baseline=fixture.repository,
        baseline_tree_digest=fixture.tree_digest,
        expected_tree_digest=_patched_digest(fixture, patch),
        patch=patch,
        groups=fixture.groups,
    )
    cause = None
    output = ""
    if result.preflight is None or result.preflight.status != "passed":
        cause = (
            result.preflight.cause if result.preflight else (result.cause or "missing_preflight")
        )
        cause = cause or "unavailable_preflight"
        if cause.startswith("typecheck_"):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                materialize(root, fixture.repository, patch)
                output = _run(image, root, TYPECHECK)
    return Run(
        {
            group.name: Group(status=group.status, stdout=group.stdout, stderr=group.stderr)
            for group in result.groups
        },
        cause,
        output,
    )


async def gate_scenario(name: str, image: str, *, verify: bool = False) -> None:
    """Retain both actual replays for every reference, omission and alternative control."""
    import json
    from dataclasses import asdict
    from pathlib import Path

    from assay.canonical import canonical_json, digest_bytes
    from code_extension.fact_shapes.alignment import fact_titles as source_titles
    from code_extension.fact_shapes.attempts import HolderSpec
    from code_extension.fact_shapes.cells import CELLS, RepositoryPath
    from code_extension.fact_shapes.generate import scenario_name
    from code_extension.fixture import PILOT, materialize, read_tree
    from code_extension.fixtures import load_scenario
    from code_extension.qualify import observed_image_digest

    cells = tuple(cell for cell in CELLS if scenario_name(cell) == name)
    if not cells:
        raise ValueError(f"unknown fact-shapes scenario: {name}")
    image = observed_image_digest(image)
    root = PILOT.parent / name
    import asyncio

    semaphore = asyncio.Semaphore(1)

    async def gate_cell(cell: Cell) -> None:
        async with semaphore:
            fixture = load_scenario(name, arm_id=cell.shape)
            facts = tuple(
                Fact(
                    fact_id,
                    source_titles(
                        (
                            root
                            / "hidden/new_behavior/tests/hidden/new-behavior"
                            / f"{fact_id}.test.ts"
                        ).read_text()
                    ),
                    cast(Shape, shape),
                    HolderSpec(tuple(RepositoryPath(p) for p in paths), ()),
                )
                for fact_id, shape, paths in (
                    (cell.fact_id, cell.shape, cell.holders),
                    (cell.anchor_fact_id, "reference", (f"{cell.feature}/anchor.ts",)),
                )
            )
            controls: list[tuple[str, str, FactId | None]] = [
                (f"{cell.shape}.reference.patch", fixture.arms[0].reference_patch, None)
            ]
            controls.extend(
                (
                    f"{cell.shape}.drop-{fact}.patch",
                    (root / "patches" / f"{cell.shape}.drop-{fact}.patch").read_text(),
                    fact,
                )
                for fact in (cell.fact_id, cell.anchor_fact_id)
            )
            if cell.shape in {"outside_code", "type_enforced"} or (
                cell.shape == "existing_state" and cell.task_type == "additive"
            ):
                import tempfile

                with tempfile.TemporaryDirectory() as directory:
                    target = Path(directory)
                    source_patch = (
                        controls[1][1]
                        if cell.shape == "type_enforced"
                        else fixture.arms[0].reference_patch
                    )
                    materialize(target, fixture.repository, source_patch)
                    complete = read_tree(target)
                label, alternative = alternative_control(cell, fixture.repository, complete)
                controls.append(
                    (label, alternative, cell.fact_id if cell.shape != "outside_code" else None)
                )
            for label, patch, dropped in controls:
                runs = (
                    await run_control(fixture, image, patch),
                    await run_control(fixture, image, patch),
                )
                title_only = label == "type-without-required-feature.patch"
                result = verdict(
                    cell.shape, label, facts, runs, dropped, allow_preflight=not title_only
                )
                record = result.error if isinstance(result, Err) else result.value
                path = root / "qualification/mutants" / cell.shape / f"{label}.json"
                value = {
                    "image_digest": image,
                    "patch_digest": digest_bytes(patch.encode()),
                    "scored_facts": [str(fact.id) for fact in facts],
                    "result": asdict(record),
                    "runs": [
                        {
                            "groups": {
                                key: {"status": value.status} for key, value in run.groups.items()
                            },
                            "preflight_cause": run.preflight_cause,
                            "typecheck_output": run.typecheck_output,
                            "passing_titles": [
                                title
                                for group in run.groups.values()
                                for status, title in parse_titles(group.stdout, group.stderr)
                                if status == "pass" and title.startswith("fact:")
                            ],
                            "failing_titles": [
                                title
                                for group in run.groups.values()
                                for status, title in parse_titles(group.stdout, group.stderr)
                                if status == "fail" and title.startswith("fact:")
                            ],
                        }
                        for run in runs
                    ],
                }
                if title_only or label == "follow-up-migration.patch":
                    value["control_patch"] = patch
                data = canonical_json(value) + b"\n"
                if verify:
                    if json.loads(path.read_bytes()) != json.loads(data):
                        raise ValueError(f"{cell.shape}/{label}: retained mutant evidence differs")
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(data)
                if isinstance(result, Err):
                    raise ValueError(f"{record.arm}/{record.patch}/{record.fact}: {record.reason}")
                print(f"passed {name}/{cell.shape}/{label}", flush=True)

    await asyncio.gather(*(gate_cell(cell) for cell in cells))


if __name__ == "__main__":
    import argparse
    import asyncio

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--verify-committed", action="store_true")
    args = parser.parse_args()
    asyncio.run(gate_scenario(args.scenario, args.image, verify=args.verify_committed))
