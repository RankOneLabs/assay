"""Malformed YAML must remain verifiable but must not reach a new dispatch."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest
import yaml
from typesafe_relevance import run_arms, run_packet, run_primary, run_round4, variants
from typesafe_relevance.catalogue import (
    MalformedCatalogueError,
    check_dispatchable,
    load_catalogue,
)
from typesafe_relevance.packet import rubric_card


@pytest.fixture
def malformed_catalogue(tmp_path: Path) -> Path:
    path = tmp_path / "malformed.yaml"
    path.write_text(
        "id: test\ndecide: test\ndescription: test\nstate: {}\n"
        "questions:\n  q:\n    criteria:\n"
        "      a: {what: A product, vendor, or company.}\n"
    )
    return path


def test_malformed_catalogue_still_loads_for_verification(malformed_catalogue: Path) -> None:
    catalogue = load_catalogue(malformed_catalogue)
    assert catalogue.version == load_catalogue(malformed_catalogue).version
    with pytest.raises(MalformedCatalogueError, match="q.criteria.a.vendor"):
        check_dispatchable(catalogue.questions)


def test_quoted_commas_are_dispatchable() -> None:
    check_dispatchable(yaml.safe_load(
        'q:\n  criteria:\n    a: {what: "A product, vendor, or company."}\n'
    ))


def test_optional_null_fields_remain_dispatchable() -> None:
    questions = yaml.safe_load(
        'q:\n  metadata: null\n  criteria:\n'
        '    a: {what: "A product, vendor, or company.", not_for: null, examples: null}\n'
    )
    check_dispatchable(questions)
    assert questions["q"]["criteria"]["a"]["not_for"] is None


def test_null_required_description_is_rejected() -> None:
    with pytest.raises(MalformedCatalogueError, match="q.criteria.a.what"):
        check_dispatchable({"q": {"criteria": {"a": {"what": None}}}})


@pytest.mark.parametrize("name", ["band-form", "label-form"])
def test_synthetic_catalogues_are_dispatchable(name: str) -> None:
    path = Path(__file__).parent / "fixtures" / f"{name}.yaml"
    check_dispatchable(load_catalogue(path).questions)


def test_null_criteria_is_rejected() -> None:
    with pytest.raises(MalformedCatalogueError, match="q.criteria"):
        check_dispatchable({"q": {"criteria": None}})


def test_packet_accepts_null_examples() -> None:
    questions = load_catalogue(
        Path(__file__).parent / "fixtures" / "band-form.yaml"
    ).questions
    questions["exclusion"]["criteria"]["hype"]["examples"] = None
    check_dispatchable(questions)
    card = rubric_card(questions)
    option = next(item for item in card["exclusion"]["options"] if item["name"] == "hype")
    assert option["examples"] == []
    assert questions["exclusion"]["criteria"]["hype"]["examples"] is None


@pytest.mark.parametrize("completed", [False, True])
def test_primary_validates_only_new_requests(
    completed: bool, malformed_catalogue: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = [
        {"evaluation_id": index, "human_label": True, "production_score": 1,
         "production_decision": True}
        for index in range(79)
    ]
    monkeypatch.setattr(
        run_primary, "_read_jsonl",
        lambda path, project: records if project == "agent-ops" else [],
    )
    monkeypatch.setitem(run_primary.DECIDE_REGISTRY, "test", lambda answers: {})
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)

    def unexpected_client(*args, **kwargs):
        pytest.fail("reuse or malformed pending work must not create a provider client")

    monkeypatch.setattr(run_primary, "TypeSafeClient", unexpected_client)
    cases = [
        {**record, "repeats": [
            {"repeat_index": repeat, "decision": {"eligible": True}}
            for repeat in range(1, 4)
        ]}
        for record in records
    ]
    if not completed:
        cases[-1]["repeats"].pop()
    output = malformed_catalogue.parent / "primary.json"
    output.write_text(json.dumps({"cases": cases}))
    before = output.read_bytes()
    args = argparse.Namespace(
        catalogue=malformed_catalogue, output=output, agent_ops=None, agent_evals=None,
        population=malformed_catalogue,
    )
    if completed:
        run_primary.run(args)
        result = json.loads(output.read_text())
        assert result["metrics"]["typesafe"]["accuracy"] == 1
        assert [case["repeats"] for case in result["cases"]] == [
            case["repeats"] for case in cases
        ]
    else:
        with pytest.raises(MalformedCatalogueError):
            run_primary.run(args)
        assert output.read_bytes() == before


@pytest.mark.parametrize("runner", [run_round4, variants])
@pytest.mark.parametrize("completed", [False, True])
def test_cell_runners_validate_only_pending_work(
    runner, completed: bool, malformed_catalogue: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = [{"evaluation_id": 1}, {"evaluation_id": 2}]
    monkeypatch.setattr(run_round4, "read_cases", lambda *_: records)
    monkeypatch.setattr(variants, "scored_cases", lambda *_: records)

    def unexpected_backend_check(self):
        pytest.fail("reuse or malformed pending work must not reach backend preflight")

    monkeypatch.setattr(variants.TypesafeBackend, "check_ready", unexpected_backend_check)
    arm = next(iter(run_round4.ARMS))
    monkeypatch.setattr(
        type(run_round4.ARMS[arm]), "check_ready", unexpected_backend_check,
    )
    cells = {
        (f"{arm}:{index}" if runner is run_round4 else str(index)):
        {"arm": arm, "evaluation_id": index, "answers": {}}
        for index in (1, 2)
    }
    if not completed:
        cells.pop(f"{arm}:2" if runner is run_round4 else "2")
    output = malformed_catalogue.parent / "cells.json"
    output.write_text(json.dumps({
        "catalogue": {"version": load_catalogue(malformed_catalogue).version},
        "cells": cells,
    }))
    before = output.read_bytes()
    args = argparse.Namespace(
        catalogue=malformed_catalogue, output=output, key=None, agent_ops=None,
        agent_evals=None, round=None, arms=[arm], dry_run=False,
    )
    if completed:
        runner.run(args)
        assert json.loads(output.read_text())["cells"] == cells
    else:
        with pytest.raises(MalformedCatalogueError):
            runner.run(args)
        assert output.read_bytes() == before


@pytest.mark.parametrize("command", ["fresh", "regrade", "build", "census", "substance"])
def test_packets_reject_before_reading_input(
    command: str, malformed_catalogue: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        argparse.ArgumentParser,
        "parse_args",
        lambda self: argparse.Namespace(command=command, catalogue=malformed_catalogue),
    )
    with pytest.raises(MalformedCatalogueError):
        run_packet.main()


@pytest.mark.parametrize("arm,reuse", [("gemini:v1", False), ("gemini:v1", True),
                                      ("jev:v1", True)])
def test_arms_validate_only_new_dispatches(
    arm: str, reuse: bool, malformed_catalogue: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(run_arms, "read_population", lambda *_: [{"evaluation_id": 1}])
    prior = {f"{arm}:1:{repeat}": {} for repeat in range(1, run_arms.REPEATS + 1)}
    monkeypatch.setattr(run_arms, "load_prior_cells", lambda *_: prior if reuse else {})

    def unexpected_backend_check(self) -> None:
        pytest.fail("malformed or reused catalogue must not reach backend preflight")

    monkeypatch.setattr(run_arms.OpenRouterBackend, "check_ready", unexpected_backend_check)
    args = argparse.Namespace(
        catalogue_v1=malformed_catalogue, catalogue_v2=malformed_catalogue,
        arms=[arm], agent_ops=None, agent_evals=None, limit_cases=None,
        output=malformed_catalogue.parent / "output.json", reuse=[], max_calls=3, dry_run=True,
    )
    if reuse:
        run_arms.run(args)
    else:
        with pytest.raises(MalformedCatalogueError):
            run_arms.run(args)
