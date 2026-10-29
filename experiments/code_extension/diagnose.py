"""Replay recorded extension failures in the pinned image without changing verdicts."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tempfile
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path

from assay.canonical import canonical_json
from assay.fixture_manifest import FixtureManifestV3
from code_extension.fixture import PILOT, PilotFixture, load_fixture, materialize, read_tree
from code_extension.qualify import require_image

_FAIL = re.compile(r"^\(fail\) (.*?)(?: \[[\d.]+ms\])?$", re.MULTILINE)
_TS_ERROR = re.compile(r"^(\S+\.ts)\(\d+,\d+\): error (TS\d+): (.*)$", re.MULTILINE)
TYPECHECK = ("tsc", "--noEmit", "-p", "tsconfig.json")
_REPLAY = """import json
import subprocess
import sys
from pathlib import Path

payload = json.loads(sys.stdin.buffer.read())
root = Path('/tmp/extension-diagnose')
root.mkdir()
for name, source in payload['tree'].items():
    target = root / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source, encoding='utf-8')
result = subprocess.run(payload['command'], cwd=root, capture_output=True,
                        timeout=180, check=False)
sys.stdout.buffer.write(result.stdout + result.stderr)
"""


def _reset_visible_tests(root: Path, fixture: PilotFixture) -> None:
    visible = root / "tests" / "visible"
    if visible.exists():
        shutil.rmtree(visible)
    for group in fixture.groups:
        if group.restores:
            for name, source in group.files.items():
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(source, encoding="utf-8")


def _install_hidden_tests(root: Path, fixture: PilotFixture) -> None:
    for group in fixture.groups:
        if not group.restores:
            for name, source in group.files.items():
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(source, encoding="utf-8")


def _run(image: str, root: Path, argv: Sequence[str]) -> str:
    name = "assay-extension-diagnose-" + uuid.uuid4().hex
    try:
        completed = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--name",
                name,
                "--pull=never",
                "--network=none",
                "--read-only",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                "--pids-limit",
                "64",
                "--memory",
                "512m",
                "--cpus",
                "1",
                "--tmpfs",
                "/tmp:rw,nosuid,nodev,size=256m",
                "--user",
                "65534:65534",
                "--env",
                "HOME=/tmp",
                "--env",
                "BUN_INSTALL_CACHE_DIR=/tmp/bun",
                "--workdir",
                "/tmp",
                "--entrypoint",
                "python",
                "-i",
                image,
                "-I",
                "-S",
                "-c",
                _REPLAY,
            ],
            input=canonical_json({"tree": read_tree(root), "command": list(argv)}),
            capture_output=True,
            timeout=300,
            check=False,
        )
        if completed.returncode:
            raise RuntimeError("diagnosis sandbox failed")
        return (completed.stdout + completed.stderr).decode("utf-8", errors="replace")
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)


def diagnose_candidate(
    image: str,
    fixture: PilotFixture,
    patch: str,
    groups: Mapping[str, Mapping[str, str | None]],
    *,
    scratch: Path,
    manifest: FixtureManifestV3 | None = None,
) -> dict[str, object]:
    """Return names for already-failed groups; the caller's record is never edited."""
    if manifest is not None:
        require_image(manifest, image)
    commands = {group.name: group.command for group in fixture.groups}
    if set(groups) - commands.keys():
        raise ValueError("unknown recorded group")
    causes = {group.get("cause") for group in groups.values() if group.get("cause")}
    preflight = sorted(
        cause
        for cause in causes
        if cause is not None
        and (
            cause.startswith(("typecheck_", "build_"))
            or cause
            in {
                "patch_rejected",
                "test_path_collision",
                "toolchain_unavailable",
                "candidate_tree_digest_mismatch",
                "sandbox_protocol_error",
            }
        )
    )
    cause = preflight[0] if preflight else None
    if cause is not None and cause != "typecheck_nonzero_exit":
        return {"preflight_cause": cause}
    root = Path(tempfile.mkdtemp(dir=scratch))
    root.chmod(0o755)
    try:
        materialize(root, fixture.repository, patch)
        _reset_visible_tests(root, fixture)
        if cause == "typecheck_nonzero_exit":
            errors = _TS_ERROR.findall(_run(image, root, TYPECHECK))
            return {
                "preflight_cause": cause,
                "typecheck_errors": [
                    {"file": file, "code": code, "message": message}
                    for file, code, message in errors[:5]
                ],
            }
        _install_hidden_tests(root, fixture)
        return {
            "failing_tests": {
                name: sorted(
                    set(
                        _FAIL.findall(
                            _run(
                                image,
                                root,
                                next(
                                    group.command for group in fixture.groups if group.name == name
                                ),
                            )
                        )
                    )
                )
                for name, group in sorted(groups.items())
                if group.get("status") == "failed"
            }
        }
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="assay-code-extension:run-bfb5dd7d9189a983")
    parser.add_argument("--manifest", type=Path, default=PILOT / "qualification" / "manifest.json")
    parser.add_argument("--record", type=Path, required=True)
    parser.add_argument("--patch", type=Path, required=True)
    args = parser.parse_args()
    manifest = FixtureManifestV3.model_validate_json(args.manifest.read_bytes())
    record = json.loads(args.record.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as scratch:
        diagnosis = diagnose_candidate(
            args.image,
            load_fixture(),
            args.patch.read_text(encoding="utf-8"),
            record["groups"],
            scratch=Path(scratch),
            manifest=manifest,
        )
    print(json.dumps(diagnosis, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
