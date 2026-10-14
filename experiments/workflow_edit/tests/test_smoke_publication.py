from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from workflow_edit.smoke import publish, validate_publication


def _evidence() -> dict[str, object]:
    return {
        "container": {
            "client": "docker inspect",
            "raw": {
                "State": {"ExitCode": 0},
                "HostConfig": {"NetworkMode": "none", "Memory": 1073741824, "PidsLimit": 64},
                "SizeRw": 2732032,
                "Image": "sha256:" + "a" * 64,
            },
        },
        "model_trial": {
            "client": "smithers+pier-model-loop",
            "model_requests": 2,
            "dispatches": 20,
            "paid_cells": 0,
            "paid_route_reachable": False,
            "halts": ["budget_exhausted", "ceiling_exhausted"],
            "dropped_response_job_ids": ["same-id", "same-id"],
            "dropped_response_completions": 1,
            "missing_billing_coverage": "uncertain",
            "measurements": {
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "wall_seconds": 1,
                "queue_latency_seconds": 1,
                "failure_rate": 0,
            },
        },
    }


def test_rejects_host_driver_and_single_model_request() -> None:
    evidence = _evidence()
    evidence["container"]["client"] = "host_driver"  # type: ignore[index]
    with pytest.raises(ValueError, match="docker inspect"):
        validate_publication(evidence)

    evidence = _evidence()
    evidence["model_trial"]["model_requests"] = 1  # type: ignore[index]
    with pytest.raises(ValueError, match="single-model-request"):
        validate_publication(evidence)


def test_accepts_complete_provenance() -> None:
    validate_publication(_evidence())


def test_publication_refuses_host_echo_and_single_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = tmp_path / "SMOKE.md"
    evidence_path = tmp_path / "evidence.json"
    evidence = _evidence()
    evidence["container"]["client"] = "host_driver"  # type: ignore[index]
    evidence_path.write_text(json.dumps(evidence))
    with pytest.raises(ValueError, match="docker inspect"):
        publish(evidence_path, report)
    assert not report.exists()

    evidence = _evidence()
    evidence["container"]["container_id"] = "observed"  # type: ignore[index]
    evidence["model_trial"]["model_requests"] = 1  # type: ignore[index]
    evidence_path.write_text(json.dumps(evidence))

    def inspect(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=[], returncode=0,
                                           stdout=json.dumps([evidence["container"]["raw"]]))  # type: ignore[index]

    monkeypatch.setattr("workflow_edit.smoke.subprocess.run", inspect)
    with pytest.raises(ValueError, match="single-model-request"):
        publish(evidence_path, report)
    assert not report.exists()
