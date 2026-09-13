from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import FrozenInstanceError, is_dataclass

import pytest

from assay.canonical import CanonicalizationError
from assay.review import model
from assay.review.model import (
    EvaluatorView,
    ReadIssue,
    VerdictSummary,
    canonical_view_json,
    to_json_value,
)

VIEW_MODEL_NAMES = (
    "StoreSummary",
    "RunSummary",
    "RunDetail",
    "CellSummary",
    "VerdictSummary",
    "CellDetail",
    "EvaluationView",
    "PairView",
    "ReportSummary",
    "ReportDetail",
    "CostView",
    "PlannedCostView",
    "ReadIssue",
    "SubjectView",
    "ArmView",
    "EvaluatorView",
    "ExclusionView",
    "ObjectPreview",
    "InputView",
    "DiffView",
    "ComparisonView",
    "RecomputeResult",
    "VerificationResult",
    "VerificationFailure",
    "ExportData",
    "EmbeddedObject",
)


def test_verdict_numbers_preserve_integer_and_float_forms() -> None:
    integer = VerdictSummary("score", (3,), ("succeeded",), (), True, None)
    floating = VerdictSummary("score", (3.0,), ("succeeded",), (), True, None)

    integer_data = canonical_view_json(integer)
    floating_data = canonical_view_json(floating)

    assert integer_data == b'{"agreed":true,"categories":null,"evaluator_id":"score",' \
        b'"failures":[],"repeat_statuses":["succeeded"],"values":[3]}'
    assert floating_data.endswith(b'"values":[3.0]}')
    assert type(json.loads(integer_data)["values"][0]) is int
    assert type(json.loads(floating_data)["values"][0]) is float


def test_view_models_are_frozen_and_slotted() -> None:
    verdict = VerdictSummary("score", (3,), ("succeeded",), (), True, None)

    with pytest.raises(FrozenInstanceError):
        verdict.agreed = False  # type: ignore[misc]
    assert not hasattr(verdict, "__dict__")


@pytest.mark.parametrize("name", VIEW_MODEL_NAMES)
def test_every_named_view_model_is_a_frozen_slotted_dataclass(name: str) -> None:
    view_type = getattr(model, name)

    assert is_dataclass(view_type)
    assert view_type.__dataclass_params__.frozen
    assert "__slots__" in vars(view_type)


def test_nested_dataclasses_and_collections_become_json_values() -> None:
    view = EvaluatorView(
        id="structure",
        identity={"zeta": "last", "alpha": "first"},
        repeats=2,
        categories=("duplicated", "mixed", "reused"),
    )

    projected = to_json_value(view)
    encoded = canonical_view_json(view)

    assert projected == {
        "id": "structure",
        "identity": {"zeta": "last", "alpha": "first"},
        "repeats": 2,
        "categories": ["duplicated", "mixed", "reused"],
    }
    assert encoded == (
        b'{"categories":["duplicated","mixed","reused"],"id":"structure",'
        b'"identity":{"alpha":"first","zeta":"last"},"repeats":2}'
    )
    assert encoded == canonical_view_json(view)


def test_non_finite_view_number_is_rejected() -> None:
    view = VerdictSummary("score", (float("nan"),), ("succeeded",), (), True, None)

    with pytest.raises(CanonicalizationError, match=r"non-finite number"):
        canonical_view_json(view)


def test_unicode_and_nested_issue_are_preserved() -> None:
    issue = ReadIssue("unsafe", "<&>\u2028\u2029", None, None)

    encoded = canonical_view_json(issue)

    assert encoded == (
        '{"code":"unsafe","coordinate_id":null,"message":"<&>\u2028\u2029",'
        '"ref":null}'
    ).encode()


@pytest.mark.parametrize("value", [object(), {1: "invalid key"}])
def test_projection_errors_use_the_canonical_error_type(value: object) -> None:
    with pytest.raises(CanonicalizationError):
        to_json_value({"nested": [value]})
    with pytest.raises(CanonicalizationError):
        canonical_view_json({"nested": [value]})


def test_model_imports_without_fastapi() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            'import sys; sys.modules["fastapi"] = None; import assay.review.model',
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
