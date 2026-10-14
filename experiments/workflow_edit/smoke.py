"""Rebuild the pinned smoke slice and refuse unsupported measurement publication.

The smoke fixture is intentionally separate from the Part 2 study population.
Only an inspected Docker container or a multi-request model trial can supply a
number to a completed SMOKE report.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from assay.repository import validate_repository
from workflow_edit.settings import SMOKE_SUBJECT_ID

CHECKPOINT = "f3b3ffca43e43672ff2f58ab797d65c7532aaed8"
SUBJECT_ID = SMOKE_SUBJECT_ID
SOURCE_PATH = "src/domain/artifact-types.ts"
MAX_REPOSITORY_FILES = 200
MAX_REPOSITORY_BYTES = 1_000_000

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


def validate_publication(evidence: Mapping[str, Any]) -> None:
    """Reject a report whose numbers come from an echo or one model request."""
    inspected = _require_inspect(evidence.get("container"))
    model = evidence.get("model_trial")
    if not isinstance(model, dict) or model.get("client") != "smithers+pier-model-loop":
        raise ValueError("model measurements require a Smithers and Pier model trial")
    requests = model.get("model_requests")
    if not isinstance(requests, int) or isinstance(requests, bool) or requests < 2:
        raise ValueError("single-model-request trials cannot be published")
    if model.get("dispatches") != 20 or model.get("paid_cells") != 0:
        raise ValueError("qualification requires 20 dispatches and zero paid cells")
    if model.get("paid_route_reachable") is not False:
        raise ValueError("paid route must be proved unreachable")
    if set(model.get("halts", [])) != {"budget_exhausted", "ceiling_exhausted"}:
        raise ValueError("both ceiling kinds must halt")
    if model.get("dropped_response_job_ids") is None or len(
        set(model["dropped_response_job_ids"])
    ) != 1:
        raise ValueError("dropped response must yield one job id")
    if model.get("dropped_response_completions") != 1:
        raise ValueError("dropped response must yield one completion")
    if model.get("missing_billing_coverage") != "uncertain":
        raise ValueError("missing billing must be uncertain")
    measurements = model.get("measurements")
    required = {
        "prompt_tokens", "completion_tokens", "wall_seconds", "queue_latency_seconds",
        "failure_rate",
    }
    if not isinstance(measurements, dict) or set(measurements) != required:
        raise ValueError("model trial is missing section 6 measurements")
    if any(not isinstance(value, int | float) or isinstance(value, bool) or value < 0
           for value in measurements.values()):
        raise ValueError("model measurements must be nonnegative numbers")
    if not isinstance(inspected["SizeRw"], int) or inspected["SizeRw"] < 0:
        raise ValueError("invalid inspected writable-layer size")


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
    validate_publication(evidence)
    inspected = evidence["container"]["raw"]
    model = evidence["model_trial"]["measurements"]
    lines = [
        "# Workflow edit smoke qualification", "",
        "Observing clients: Docker CLI (`docker inspect`) and Smithers + Pier model loop.",
        "",
        f"- Docker writable layer: {inspected['SizeRw']} bytes (`docker inspect`).",
        (
            f"- Docker memory limit: {inspected['HostConfig']['Memory']} bytes "
            "(`docker inspect`)."
        ),
        f"- Docker PID limit: {inspected['HostConfig']['PidsLimit']} (`docker inspect`).",
    ]
    for name, value in model.items():
        lines.append(f"- {name}: {value} (Smithers + Pier model loop).")
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
