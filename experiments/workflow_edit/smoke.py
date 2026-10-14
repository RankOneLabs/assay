"""Rebuild the pinned smoke slice and refuse unsupported measurement publication.

The smoke fixture is intentionally separate from the Part 2 study population.
Only an inspected Docker container or a multi-request model trial can supply a
number to a completed SMOKE report.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import math
import statistics
import subprocess
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from assay.investigations.workflow_correctness import workflow_tree_digest
from assay.repository import validate_repository
from workflow_edit.settings import SMOKE_SUBJECT_ID

CHECKPOINT = "f3b3ffca43e43672ff2f58ab797d65c7532aaed8"
SUBJECT_ID = SMOKE_SUBJECT_ID
SOURCE_PATH = "src/domain/artifact-types.ts"
MAX_REPOSITORY_FILES = 200
MAX_REPOSITORY_BYTES = 1_000_000
SMOKE_CHECKS = (
    ("install", "node /usr/local/lib/node_modules/npm/bin/npm-cli.js ci --offline "
     "--ignore-scripts --no-audit --no-fund --no-bin-links"),
    ("typecheck", "node node_modules/typescript/bin/tsc --noEmit --strict "
     "--target es2022 --module commonjs src/domain/artifact-types.ts"),
    ("compile", "node node_modules/typescript/bin/tsc --target es2022 "
     "--module commonjs --outDir dist src/domain/artifact-types.ts"),
    ("test", "node --test tests/artifact-types.test.cjs"),
)


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()

PACKAGE_JSON = json.dumps(
    {
        "name": "assay-wf12-smoke",
        "private": True,
        "version": "0.0.0",
        "scripts": {
            "typecheck": (
                "node node_modules/typescript/bin/tsc --noEmit --strict --target es2022 "
                "--module commonjs src/domain/artifact-types.ts"
            ),
            "test": "node --test tests/artifact-types.test.cjs",
        },
        "dependencies": {"typescript": "file:/opt/workflow_edit/node_modules/typescript"},
    },
    indent=2,
) + "\n"

TEST_SOURCE = """const { test } = require('node:test');
const assert = require('node:assert/strict');
const { DEV_FLOW_ARTIFACT_TYPES, findArtifactType } = require('../dist/artifact-types.js');
test('the pinned artifact registry resolves the plan and rejects unknown types', () => {
  assert.equal(findArtifactType('dev.plan').review.layout, 'dag');
  assert.equal(findArtifactType('missing'), null);
  assert.equal(DEV_FLOW_ARTIFACT_TYPES.length, 7);
});
"""

LOCK_SOURCE = '''{
  "name": "assay-wf12-smoke",
  "version": "0.0.0",
  "lockfileVersion": 3,
  "requires": true,
  "packages": {
    "": {
      "name": "assay-wf12-smoke",
      "version": "0.0.0",
      "dependencies": {
        "typescript": "file:/opt/workflow_edit/node_modules/typescript"
      }
    },
    "../opt/workflow_edit/node_modules/typescript": {
      "version": "5.9.2",
      "license": "Apache-2.0",
      "bin": {
        "tsc": "bin/tsc",
        "tsserver": "bin/tsserver"
      },
      "devDependencies": {
        "@dprint/formatter": "^0.4.1",
        "@dprint/typescript": "0.93.4",
        "@esfx/canceltoken": "^1.0.0",
        "@eslint/js": "^9.20.0",
        "@octokit/rest": "^21.1.1",
        "@types/chai": "^4.3.20",
        "@types/diff": "^7.0.1",
        "@types/minimist": "^1.2.5",
        "@types/mocha": "^10.0.10",
        "@types/ms": "^0.7.34",
        "@types/node": "latest",
        "@types/source-map-support": "^0.5.10",
        "@types/which": "^3.0.4",
        "@typescript-eslint/rule-tester": "^8.24.1",
        "@typescript-eslint/type-utils": "^8.24.1",
        "@typescript-eslint/utils": "^8.24.1",
        "azure-devops-node-api": "^14.1.0",
        "c8": "^10.1.3",
        "chai": "^4.5.0",
        "chokidar": "^4.0.3",
        "diff": "^7.0.0",
        "dprint": "^0.49.0",
        "esbuild": "^0.25.0",
        "eslint": "^9.20.1",
        "eslint-formatter-autolinkable-stylish": "^1.4.0",
        "eslint-plugin-regexp": "^2.7.0",
        "fast-xml-parser": "^4.5.2",
        "glob": "^10.4.5",
        "globals": "^15.15.0",
        "hereby": "^1.10.0",
        "jsonc-parser": "^3.3.1",
        "knip": "^5.44.4",
        "minimist": "^1.2.8",
        "mocha": "^10.8.2",
        "mocha-fivemat-progress-reporter": "^0.1.0",
        "monocart-coverage-reports": "^2.12.1",
        "ms": "^2.1.3",
        "picocolors": "^1.1.1",
        "playwright": "^1.50.1",
        "source-map-support": "^0.5.21",
        "tslib": "^2.8.1",
        "typescript": "^5.7.3",
        "typescript-eslint": "^8.24.1",
        "which": "^3.0.1"
      },
      "engines": {
        "node": ">=14.17"
      }
    },
    "node_modules/typescript": {
      "resolved": "../opt/workflow_edit/node_modules/typescript",
      "link": true
    }
  }
}
'''


def source_at_checkpoint(oakridge_root: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(oakridge_root), "show", f"{CHECKPOINT}:oakridge-dbos/{SOURCE_PATH}"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def fixture_files(oakridge_root: Path) -> dict[str, str]:
    """Return the exact model-visible snapshot, checked against package limits."""
    return validate_repository(
        {
            SOURCE_PATH: source_at_checkpoint(oakridge_root),
            "tests/artifact-types.test.cjs": TEST_SOURCE,
            "package.json": PACKAGE_JSON,
            "package-lock.json": LOCK_SOURCE,
        },
        max_files=MAX_REPOSITORY_FILES,
        max_total_bytes=MAX_REPOSITORY_BYTES,
    )


def write_fixture(oakridge_root: Path, destination: Path) -> None:
    for name, content in fixture_files(oakridge_root).items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def build_image(*, image_tag: str) -> str:
    """Add offline npm to the locked Pier runtime and return its inspected ID."""
    dockerfile = (
        "FROM assay-pier-bridge:qualify-local\n"
        "COPY --from=node:lts-slim /usr/local/lib/node_modules/npm "
        "/usr/local/lib/node_modules/npm\n"
    )
    with tempfile.TemporaryDirectory(prefix="assay-wf12-image-") as directory:
        path = Path(directory) / "Dockerfile"
        path.write_text(dockerfile, encoding="utf-8")
        subprocess.run(
            ["docker", "build", "--network", "none", "-f", str(path), "-t", image_tag,
             directory], check=True,
        )
    result = subprocess.run(
        ["docker", "image", "inspect", "--format", "{{.Id}}", image_tag],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def run_container_trial(
    *, fixture_dir: Path, image_tag: str, container_name: str
) -> dict[str, Any]:
    """Run the install/typecheck/test gate with no network and inspect it."""
    command = (
        "node /usr/local/lib/node_modules/npm/bin/npm-cli.js ci --offline "
        "--ignore-scripts --no-audit --no-fund && "
        "node node_modules/typescript/bin/tsc --noEmit --strict --target es2022 "
        "--module commonjs src/domain/artifact-types.ts && "
        "node node_modules/typescript/bin/tsc --target es2022 --module commonjs "
        "--outDir dist src/domain/artifact-types.ts && "
        "node --test tests/artifact-types.test.cjs"
    )
    subprocess.run(
        ["docker", "run", "--name", container_name, "--network", "none", "--memory",
         "1024m", "--pids-limit", "64", "--user", "0:0", "--mount",
         f"type=bind,src={fixture_dir.resolve()},dst=/work", "-w", "/work",
         "--entrypoint", "/bin/sh", image_tag, "-lc", command],
        check=True,
    )
    result = subprocess.run(
        ["docker", "inspect", "--size", container_name],
        capture_output=True, text=True, check=True,
    )
    inspected: dict[str, Any] = json.loads(result.stdout)[0]
    if inspected["HostConfig"]["NetworkMode"] != "none" or inspected["State"]["ExitCode"] != 0:
        raise ValueError("the offline container gate did not pass")
    return inspected


def _require_inspect(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, dict) or value.get("client") != "docker inspect":
        raise ValueError("container measurements require docker inspect evidence")
    raw = value.get("raw")
    if not isinstance(raw, dict):
        raise ValueError("docker inspect raw object is required")
    state = raw.get("State")
    host = raw.get("HostConfig")
    if not isinstance(state, dict) or not isinstance(host, dict):
        raise ValueError("invalid docker inspect object")
    if state.get("ExitCode") != 0 or host.get("NetworkMode") != "none":
        raise ValueError("offline container trial must exit successfully")
    for field in ("SizeRw", "Image"):
        if field not in raw:
            raise ValueError(f"docker inspect omitted {field}")
    return raw


def _verified_binding(
    value: Any, inspected: Mapping[str, Any], snapshot: Mapping[str, str],
    fixture_manifest: Mapping[str, Any],
) -> dict[str, str]:
    if not isinstance(value, dict) or value.get("client") != "qualify_local.py + docker inspect":
        raise ValueError("harness-sealed binding evidence is required")
    if value.get("container_id") != inspected.get("Id"):
        raise ValueError("binding container differs from inspected trial")
    mount = [
        item for item in inspected.get("Mounts", [])
        if item.get("Destination") == "/work" and item.get("Type") == "bind"
    ]
    if len(mount) != 1 or mount[0].get("Source") != value.get("mount_source"):
        raise ValueError("binding fixture mount differs from inspected trial")
    encoded = value.get("artifacts_base64")
    if not isinstance(encoded, dict) or not all(
        isinstance(name, str) and isinstance(data, str) for name, data in encoded.items()
    ):
        raise ValueError("binding artifacts are missing")
    try:
        artifacts = {
            name: base64.b64decode(data, validate=True) for name, data in encoded.items()
        }
        if value.get("artifact_count") != len(artifacts) - 1:
            raise ValueError("binding artifact count differs")
        manifest_bytes = artifacts["manifest.json"]
        sealed = json.loads(manifest_bytes)
        if not isinstance(sealed, dict):
            raise ValueError("binding manifest must be an object")
        entries = sealed["entries"]
        if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
            raise ValueError("binding entries must be objects")
        declared = {entry["path"]: entry for entry in entries}
    except (ValueError, KeyError, TypeError, binascii.Error) as error:
        raise ValueError("binding artifacts are invalid") from error
    if (sealed.get("schema_version") != "assay-pier-artifact-manifest/0.2.0"
            or set(declared) != set(artifacts) - {"manifest.json"}
            or len(declared) != len(entries)):
        raise ValueError("binding manifest does not describe sealed artifacts")
    if any(
        entry.get("size_bytes") != len(artifacts[name])
        or entry.get("checksum") != _digest(artifacts[name])
        for name, entry in declared.items()
    ) or sealed.get("aggregate_bytes") != sum(
        len(data) for name, data in artifacts.items() if name != "manifest.json"
    ):
        raise ValueError("binding artifact checksums differ")
    if _digest(manifest_bytes) != value.get("manifest_digest"):
        raise ValueError("binding manifest digest differs")
    try:
        configuration = json.loads(artifacts["configuration.json"])
        result = json.loads(artifacts["result.json"])
        index = json.loads(artifacts["candidate-index.json"])
        sealed_files = {
            name.removeprefix("candidate_files/"): data
            for name, data in artifacts.items() if name.startswith("candidate_files/")
        }
    except (KeyError, ValueError) as error:
        raise ValueError("binding required artifacts are missing") from error
    if configuration != {
        "network": "none", "image": inspected["Image"], "container_id": inspected["Id"],
    } or result != {"exit_code": inspected["State"]["ExitCode"]}:
        raise ValueError("binding trial identity differs from docker inspect")
    if index != sorted(snapshot, key=lambda path: path.encode("utf-8")) or sealed_files != {
        name: content.encode("utf-8") for name, content in snapshot.items()
    }:
        raise ValueError("binding candidate files differ from the package snapshot")
    tree = workflow_tree_digest(snapshot)
    exchange = sealed.get("exchange")
    runtime_binding = exchange.get("binding") if isinstance(exchange, dict) else None
    if (artifacts.get("tree-digest.txt") != tree.encode("ascii")
            or value.get("tree_digest") != tree
            or not isinstance(runtime_binding, dict)
            or runtime_binding.get("image_digest") != inspected["Image"]
            or tree != fixture_manifest["per_arm_tree_digests"]["mess-00"]):
        raise ValueError("binding tree or runtime image differs from fixture manifest")
    return {"manifest_digest": _digest(manifest_bytes), "tree_digest": tree}


def _publication_metrics(evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Derive every report number from inspected Docker and raw trial records."""
    inspected = _require_inspect(evidence.get("container"))
    if not isinstance(inspected["SizeRw"], int) or inspected["SizeRw"] < 0:
        raise ValueError("invalid inspected writable-layer size")
    host = inspected["HostConfig"]
    if not isinstance(host.get("Memory"), int) or not isinstance(host.get("PidsLimit"), int):
        raise ValueError("docker inspect omitted memory or PID limits")
    manifest_path = Path(__file__).parent / "fixtures/smoke/MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if inspected["Image"] != manifest["observed_runtime_image_digest"]:
        raise ValueError("observed image differs from the smoke manifest")
    model = evidence.get("model_trial")
    if not isinstance(model, dict) or model.get("client") != "smithers+pier-model-loop":
        raise ValueError("model measurements require a Smithers and Pier model trial")
    if set(model) != {
        "client", "route", "paid_route_reachable", "records", "package_snapshot",
        "drop_response", "admission",
    }:
        raise ValueError("unsupported supplied measurement fields")
    if model.get("route") != {
        "endpoint": "http://willie:8900", "model": "qwen-coder-32b", "provider": "smithers-local"
    } or model.get("paid_route_reachable") is not False:
        raise ValueError("paid route must be proved unreachable")
    records = model.get("records")
    if not isinstance(records, list) or len(records) != 20:
        raise ValueError("qualification requires 20 dispatches")
    if len({record.get("cell_id") for record in records if isinstance(record, dict)}) != 20:
        raise ValueError("qualification requires 20 distinct cell ids")
    requests: list[dict[str, Any]] = []
    peaks: list[dict[str, Any]] = []
    request_peaks: list[dict[str, Any]] = []
    failed_tool_calls = 0
    for record in records:
        if not isinstance(record, dict) or record.get("status") != "complete":
            raise ValueError("all 20 qualification dispatches must complete")
        if record.get("cost_usd") is not None:
            raise ValueError("zero-paid local billing must remain uncertain")
        events = record.get("events")
        messages = record.get("messages")
        if not isinstance(events, list) or not isinstance(messages, list):
            raise ValueError("model trial requires raw events and tool messages")
        model_events = [item for item in events if item.get("kind") == "model_request"]
        peak_events = [item for item in events if item.get("kind") == "cgroup_peaks"]
        if (len(model_events) < 2 or len(model_events) != record.get("requests")
                or len(peak_events) != 1):
            raise ValueError("each cell requires a multi-model-request trace and cgroup peaks")
        if [item.get("turn") for item in model_events] != list(range(1, len(model_events) + 1)):
            raise ValueError("model request turns are inconsistent")
        if not any(item.get("kind") == "submitted" and item.get("turn", 0) >= 2
                   for item in events):
            raise ValueError("model loop did not submit a completion")
        checks = [item for item in events if item.get("kind") == "harness_check"]
        if [(item.get("step"), item.get("command")) for item in checks] != list(SMOKE_CHECKS):
            raise ValueError("harness-controlled smoke checks are missing")
        if max(events.index(item) for item in checks) >= events.index(model_events[0]):
            raise ValueError("harness checks must precede model dispatch")
        if any(item.get("exit_code") != 0 or not isinstance(item.get("output"), str)
               or not item["output"].startswith("exit=0\n") for item in checks):
            raise ValueError("harness-controlled smoke check failed")
        if "# pass 1" not in checks[-1]["output"]:
            raise ValueError("harness-controlled smoke test did not pass")
        tools = [item for item in messages if item.get("role") == "tool"]
        if not tools or not all(isinstance(item.get("content"), str) for item in tools):
            raise ValueError("qualification tool output is missing")
        assistant_positions = [index for index, item in enumerate(messages)
                               if item.get("role") == "assistant"]
        first_calls = (
            messages[assistant_positions[0]].get("tool_calls", [])
            if assistant_positions else []
        )
        first_ids = {call.get("id") for call in first_calls if isinstance(call, dict)}
        if (len(assistant_positions) != len(model_events)
                or any(call.get("function", {}).get("name") == "submit_output"
                       for call in first_calls)
                or not any(
                    messages[index].get("role") == "tool"
                    and messages[index].get("tool_call_id") in first_ids
                    for index in range(assistant_positions[0] + 1, assistant_positions[1])
                )):
            raise ValueError("each cell requires a model/tool/model round trip")
        failed_tool_calls += sum(
            not item["content"].startswith("exit=0\n") for item in tools
        )
        for item in model_events:
            if item.get("billing") != "uncertain" or not isinstance(
                item.get("smithers_job_id"), str
            ):
                raise ValueError("model request has no local Smithers identity")
            for name in ("prompt_tokens", "completion_tokens"):
                if type(item.get(name)) is not int or item[name] < 0:
                    raise ValueError("model tokens require worker-observed counts")
            for name in ("queue_latency_seconds", "wall_seconds"):
                value = item.get(name)
                if not isinstance(value, int | float) or not math.isfinite(value) or value < 0:
                    raise ValueError("model timing requires Smithers timestamps")
        peak = peak_events[0]
        if any(type(peak.get(name)) is not int or peak[name] < 1
               for name in ("memory_peak_bytes", "pids_peak")):
            raise ValueError("peak footprint requires cgroup observations")
        if peak["memory_peak_bytes"] > host["Memory"] or peak["pids_peak"] > host["PidsLimit"]:
            raise ValueError("peak footprint exceeds inspected container limits")
        requests.extend(model_events)
        peaks.append(peak)
        request_peaks.extend([peak] * len(model_events))
    if len(requests) < 2:
        raise ValueError("single-model-request trials cannot be published")
    if len({item["smithers_job_id"] for item in requests}) != len(requests):
        raise ValueError("model requests must have distinct Smithers job ids")
    admission = model.get("admission")
    if not isinstance(admission, dict) or {
        admission.get("budget_halt"), admission.get("capacity_halt")
    } != {"budget_exhausted", "ceiling_exhausted"}:
        raise ValueError("both ceiling kinds must halt")
    drop = model.get("drop_response")
    if not isinstance(drop, dict) or drop.get("forced_drop") is not True or (
        drop.get("first_committed_job_id") != drop.get("redispatch_job_id")
    ):
        raise ValueError("dropped response must yield one job id")
    if drop.get("completions") != 1 or drop.get("listed_jobs_with_id") != 1:
        raise ValueError("dropped response must yield one completion")
    if admission.get("missing_billing_coverage") != "uncertain" or (
        admission.get("missing_billing_amount") is not None
    ):
        raise ValueError("missing billing must be uncertain")
    snapshot = model.get("package_snapshot")
    if not isinstance(snapshot, dict) or not all(
        isinstance(name, str) and isinstance(content, str) for name, content in snapshot.items()
    ):
        raise ValueError("model trial requires its package snapshot")
    package = validate_repository(
        snapshot, max_files=MAX_REPOSITORY_FILES, max_total_bytes=MAX_REPOSITORY_BYTES
    )
    if sorted(package) != manifest["included_paths"]:
        raise ValueError("package paths differ from the pinned smoke manifest")
    if workflow_tree_digest(package) != manifest["per_arm_tree_digests"]["mess-00"]:
        raise ValueError("package snapshot differs from the pinned tree digest")
    for name, expected in manifest["dependency_lock_digests"].items():
        if name not in package or _digest(package[name].encode("utf-8")) != expected:
            raise ValueError("package dependency lock digest differs")
    binding = _verified_binding(evidence.get("binding"), inspected, package, manifest)
    return {
        "binding": binding,
        "requests": requests, "peaks": peaks, "request_peaks": request_peaks,
        "package_files": len(package),
        "package_bytes": sum(len(content.encode()) for content in package.values()),
        "memory_peak": max(item["memory_peak_bytes"] for item in peaks),
        "pids_peak": max(item["pids_peak"] for item in peaks),
        "prompt_total": sum(item["prompt_tokens"] for item in requests),
        "completion_total": sum(item["completion_tokens"] for item in requests),
        "wall_mean": statistics.mean(item["wall_seconds"] for item in requests),
        "queue_mean": statistics.mean(item["queue_latency_seconds"] for item in requests),
        "failure_rate": 0.0,
        "failed_tool_calls": failed_tool_calls,
    }


def validate_publication(evidence: Mapping[str, Any]) -> None:
    _publication_metrics(evidence)


def publish(evidence_path: Path, output_path: Path) -> None:
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    container = evidence.get("container")
    if not isinstance(container, dict) or container.get("client") != "docker inspect":
        raise ValueError("publication requires a docker inspect client")
    container_id = container.get("container_id")
    if not isinstance(container_id, str) or not container_id:
        raise ValueError("publication requires an inspectable container id")
    observed = subprocess.run(
        ["docker", "inspect", "--size", container_id],
        capture_output=True, text=True, check=True,
    )
    actual = json.loads(observed.stdout)[0]
    if container.get("raw") != actual:
        raise ValueError("container evidence differs from live docker inspect")
    metrics = _publication_metrics(evidence)
    artifacts = evidence["binding"]["artifacts_base64"]
    observed_log = subprocess.run(
        ["docker", "logs", container_id], capture_output=True, text=True, check=True,
    )
    if json.loads(base64.b64decode(artifacts["trajectory.json"])) != {
        "docker_log": observed_log.stdout
    }:
        raise ValueError("sealed Docker log differs from inspected trial")
    inspected = evidence["container"]["raw"]
    lines = [
        "# Workflow edit smoke qualification", "",
        "The completed qualification used the pinned, network-disabled smoke image and the "
        "local Smithers route. The fixture remains excluded from Part 2 populations.",
        "The measured cells were dispatched directly through the Pier repository-agent "
        "client and local Smithers; they were not an Assay `execute_plan` study run. "
        "The ceiling probes below exercised Assay's production `AdmissionLedger` separately.",
        "",
        "## Artifact binding", "",
        "`qualify_local.py` authored the artifact manifest over the observed offline "
        "container files. Its verified manifest digest is "
        f"`{metrics['binding']['manifest_digest']}`; "
        f"the observed tree digest is `{metrics['binding']['tree_digest']}` "
        "(client: `qualify_local.py` and `docker inspect`).",
        "",
        "## Container and package footprint", "",
        f"- Docker writable layer: {inspected['SizeRw']} bytes (`docker inspect`).",
        (
            f"- Docker memory limit: {inspected['HostConfig']['Memory']} bytes "
            "(`docker inspect`)."
        ),
        f"- Docker PID limit: {inspected['HostConfig']['PidsLimit']} (`docker inspect`).",
        f"- Peak memory: {metrics['memory_peak']} bytes (Docker cgroup `memory.peak`, "
        "read by the Pier container client).",
        f"- Peak PIDs: {metrics['pids_peak']} (Docker cgroup `pids.peak`, "
        "read by the Pier container client).",
        f"- Package: {metrics['package_files']} files and {metrics['package_bytes']} UTF-8 "
        "bytes (Pier model trial package snapshot). Pier defaults are "
        f"{MAX_REPOSITORY_FILES} files and {MAX_REPOSITORY_BYTES} bytes, leaving "
        f"{MAX_REPOSITORY_FILES - metrics['package_files']} files and "
        f"{MAX_REPOSITORY_BYTES - metrics['package_bytes']} bytes of headroom "
        "(Pier package validator); "
        "the wf-06 arm-specific limits are not configured in this checkout.",
        "",
        "The manifest's hidden-test, patch, and rubric references remain smoke-only "
        "placeholders; the fixture cannot enter a study population.",
        "",
        "## Model and dispatch measurements", "",
        f"- Completed dispatches: 20 of 20; failure rate {metrics['failure_rate']:.0%} "
        "(Pier trial records and harness-controlled install/typecheck/test results).",
        f"- Nonfatal failed tool calls: {metrics['failed_tool_calls']} "
        "(Pier container tool output); these were attempts to invoke "
        "`submit_output` as a shell command before the model used the proper tool.",
        f"- Model requests: {len(metrics['requests'])}; prompt tokens "
        f"{metrics['prompt_total']}, completion tokens {metrics['completion_total']} "
        "(Smithers worker task usage).",
        f"- Mean wall time from model acceptance: {metrics['wall_mean']:.3f} seconds; "
        f"mean queue latency: {metrics['queue_mean']:.3f} seconds "
        "(Smithers dispatch timestamps).",
        "- Paid route reachable: false; paid cells: 0 (Pier route assertion: "
        "`smithers-local`, no OpenRouter key).",
        "- Admission halts: `budget_exhausted` and `ceiling_exhausted` "
        "(Assay `AdmissionLedger` qualification probes).",
        "- Forced dropped-response re-dispatch: one Smithers job ID "
        f"`{evidence['model_trial']['drop_response']['redispatch_job_id']}` and one "
        "completion (Smithers dispatch API idempotency probe).",
        "- Missing billing: `uncertain`, amount absent "
        "(Assay workflow-edit bridge accounting over Smithers worker usage).",
        "- An earlier preflight command failed under the read-only runtime when npm "
        "tried to chmod a linked tool. The measured run used `npm ci --offline "
        "--no-bin-links`; every install/typecheck/test command exited successfully "
        "(Pier harness check events).",
        "",
        "| Smithers job ID | Prompt tokens (Smithers worker) | Completion tokens "
        "(Smithers worker) | Wall s from acceptance (Smithers dispatch) | Queue s "
        "(Smithers dispatch) | Cell peak memory bytes (Docker cgroup) | Cell peak PIDs "
        "(Docker cgroup) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for request, peak in zip(metrics["requests"], metrics["request_peaks"], strict=True):
        lines.append(
            f"| `{request['smithers_job_id']}` | {request['prompt_tokens']} | "
            f"{request['completion_tokens']} | {request['wall_seconds']:.3f} | "
            f"{request['queue_latency_seconds']:.3f} | {peak['memory_peak_bytes']} | "
            f"{peak['pids_peak']} |"
        )
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare or publish the workflow smoke fixture")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare", help="materialize the pinned source slice")
    prepare.add_argument("oakridge_root", type=Path)
    prepare.add_argument("destination", type=Path)
    build = sub.add_parser("build-image", help="build the offline smoke runtime")
    build.add_argument("--image-tag", default="assay-wf12-smoke:local")
    trial = sub.add_parser("trial", help="run the offline container gate")
    trial.add_argument("fixture_dir", type=Path)
    trial.add_argument("--image-tag", default="assay-wf12-smoke:local")
    trial.add_argument("--container-name", default="assay-wf12-smoke-observed")
    trial.add_argument("--inspect-output", type=Path, required=True)
    publication = sub.add_parser("publish", help="publish a fully evidenced report")
    publication.add_argument("evidence", type=Path)
    publication.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.command == "prepare":
        write_fixture(args.oakridge_root, args.destination)
    elif args.command == "build-image":
        print(build_image(image_tag=args.image_tag))
    elif args.command == "trial":
        inspected = run_container_trial(
            fixture_dir=args.fixture_dir, image_tag=args.image_tag,
            container_name=args.container_name,
        )
        args.inspect_output.write_text(json.dumps(inspected, indent=2) + "\n")
    else:
        publish(args.evidence, args.output)


if __name__ == "__main__":
    main()
