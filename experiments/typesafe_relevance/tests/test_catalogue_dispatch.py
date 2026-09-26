"""Malformed YAML must remain verifiable but must not reach a new dispatch."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest
import yaml
from typesafe_relevance import run_packet, run_primary, run_round4, variants
from typesafe_relevance.catalogue import (
    MalformedCatalogueError,
    check_dispatchable,
    load_catalogue,
)


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


@pytest.mark.parametrize("name", ["band-form", "label-form"])
def test_synthetic_catalogues_are_dispatchable(name: str) -> None:
    path = Path(__file__).parent / "fixtures" / f"{name}.yaml"
    check_dispatchable(load_catalogue(path).questions)


@pytest.mark.parametrize("runner", [run_primary, run_round4, variants])
def test_runners_reject_before_reading_cases(runner, malformed_catalogue: Path) -> None:
    # No case paths or credentials are supplied: validation must happen first.
    with pytest.raises(MalformedCatalogueError):
        runner.run(argparse.Namespace(catalogue=malformed_catalogue))


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
