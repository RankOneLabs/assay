from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from workflow_edit.smoke import publish, validate_publication


def _evidence() -> dict[str, object]:
    manifest = json.loads(
        (Path(__file__).resolve().parents[1] / "fixtures/smoke/MANIFEST.json").read_text()
    )
    command = (
        "npm ci --offline --no-bin-links && tsc --noEmit --strict && node --test"
    )
    records = [
        {
            "cell_id": f"smoke:mess-00:w{index}", "status": "complete",
            "requests": 1, "cost_usd": None,
            "events": [
                {
                    "kind": "model_request", "billing": "uncertain",
                    "smithers_job_id": f"job-{index}", "prompt_tokens": 10,
                    "completion_tokens": 5, "queue_latency_seconds": 0.1,
                    "wall_seconds": 1.0,
                },
                {"kind": "cgroup_peaks", "memory_peak_bytes": 1024, "pids_peak": 2},
                {"kind": "submitted", "turn": 1},
            ],
            "messages": [
                {"role": "assistant", "tool_calls": [{"id": f"call-{index}", "function": {
                    "name": "run_command", "arguments": json.dumps({"command": command}),
                }}]},
                {"role": "tool", "tool_call_id": f"call-{index}",
                 "content": "exit=0\n# pass 1\n"},
            ],
        }
        for index in range(20)
    ]
    return {
        "container": {
            "client": "docker inspect",
            "raw": {
                "State": {"ExitCode": 0},
                "HostConfig": {"NetworkMode": "none", "Memory": 1073741824, "PidsLimit": 64},
                "SizeRw": 2732032,
                "Image": manifest["observed_runtime_image_digest"],
            },
        },
        "model_trial": {
            "client": "smithers+pier-model-loop",
            "route": {
                "endpoint": "http://willie:8900", "model": "qwen-coder-32b",
                "provider": "smithers-local",
            },
            "records": records,
            "paid_route_reachable": False,
            "admission": {
                "budget_halt": "budget_exhausted", "capacity_halt": "ceiling_exhausted",
                "missing_billing_coverage": "uncertain", "missing_billing_amount": None,
            },
            "drop_response": {
                "forced_drop": True, "first_committed_job_id": "same-id",
                "redispatch_job_id": "same-id", "completions": 1,
                "listed_jobs_with_id": 1,
            },
            "package_snapshot": {path: "x" for path in manifest["included_paths"]},
        },
    }


def test_rejects_host_driver_and_single_model_request() -> None:
    evidence = _evidence()
    evidence["container"]["client"] = "host_driver"  # type: ignore[index]
    with pytest.raises(ValueError, match="docker inspect"):
        validate_publication(evidence)

    evidence = _evidence()
    records = evidence["model_trial"]["records"]  # type: ignore[index]
    for record in records[1:]:
        record["requests"] = 0
    with pytest.raises(ValueError, match="single-model-request"):
        validate_publication(evidence)


def test_accepts_complete_provenance() -> None:
    validate_publication(_evidence())


def test_rejects_operator_supplied_measurement_number() -> None:
    evidence = _evidence()
    evidence["model_trial"]["measurements"] = {"failure_rate": 0}  # type: ignore[index]
    with pytest.raises(ValueError, match="unsupported supplied measurement"):
        validate_publication(evidence)


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
    records = evidence["model_trial"]["records"]  # type: ignore[index]
    for record in records[1:]:
        record["requests"] = 0
    evidence_path.write_text(json.dumps(evidence))

    def inspect(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=[], returncode=0,
                                           stdout=json.dumps([evidence["container"]["raw"]]))  # type: ignore[index]

    monkeypatch.setattr("workflow_edit.smoke.subprocess.run", inspect)
    with pytest.raises(ValueError, match="single-model-request"):
        publish(evidence_path, report)
    assert not report.exists()
