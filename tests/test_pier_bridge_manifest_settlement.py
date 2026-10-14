"""The bridge's sealed bytes satisfy the Assay-side success contract."""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path
from typing import cast

from assay.adapters.pier import BridgeTrialResult, PierAdapter, PierBridgeClient
from assay.canonical import digest_bytes
from assay.execution import WorkerSuccess
from assay.models import CellCoordinate
from assay.pier_protocol import CandidateSubmission, RuntimeBinding, bind_exchange
from assay.store import ObjectStore

BRIDGE_SRC = Path(__file__).resolve().parents[1] / "integrations" / "pier" / "src"
sys.path.insert(0, str(BRIDGE_SRC))

from assay_pier_bridge.evidence import seal_artifacts  # noqa: E402
from assay_pier_bridge.paths import tree_digest  # noqa: E402
from assay_pier_bridge.protocol import PierExchange as BridgePierExchange  # noqa: E402


def test_bridge_manifest_and_empty_patch_settle_a_success(tmp_path: Path) -> None:
    binding = RuntimeBinding(
        runtime_version="test-lock",
        image_digest="sha256:" + "1" * 64,
        configuration_ref="sha256:" + "2" * 64,
        package_digest="sha256:" + "3" * 64,
    )
    coordinate = CellCoordinate(
        subject_id="s1",
        arm_id="a1",
        worker_repeat=0,
        realization_ref="sha256:" + "0" * 64,
    )
    exchange = bind_exchange(coordinate=coordinate, binding=binding)
    artifacts = seal_artifacts(
        BridgePierExchange.model_validate(exchange.model_dump(mode="json")),
        {
            "trajectory.json": b'{"messages":[]}',
            "candidate.patch": b"",
            "result.json": b'{"exit_status":"Submitted"}',
            "configuration.json": b'{"model_route":{}}',
        },
    )
    result = BridgeTrialResult(
        exchange=exchange,
        outcome=CandidateSubmission(
            patch_ref=digest_bytes(b""),
            tree_digest=tree_digest({}),
            baseline_tree_digest=tree_digest({}),
        ),
        usage={"cost_usd": None, "prompt_tokens": 3, "completion_tokens": 1},
        artifacts=artifacts,
    )
    adapter = PierAdapter(
        store=ObjectStore(tmp_path / ".assay"),
        bridge=cast(PierBridgeClient, object()),
        binding=binding,
        model_route={},
        trial_limits={},
    )
    settled = adapter._settle(exchange, result, cleanup_incomplete=False)
    assert isinstance(settled, WorkerSuccess)
    envelope = json.loads(adapter.store.read_bytes(settled.output["candidate_ref"]))
    assert base64.b64decode(envelope["content_base64"]) == b""
    assert settled.accounting.coverage == "unavailable"
