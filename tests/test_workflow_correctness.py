from __future__ import annotations

import asyncio
import os
import signal
import sys
from pathlib import Path

import pytest

from assay.investigations import workflow_correctness as correctness
from assay.investigations.workflow_correctness import (
    DockerWorkflowRunner,
    WorkflowRunnerSettings,
    WorkflowTestGroup,
    workflow_tree_digest,
)

IMAGE = "sha256:" + "a" * 64
REAL_SPAWN = asyncio.create_subprocess_exec
BASELINE = {
    "src.ts": "export const value = 0;\n",
    "tsconfig.json": '{"compilerOptions":{"target":"ES2022","module":"commonjs"}}',
}
FINAL_TREE = {**BASELINE, "src.ts": "export const value = 1;\n"}
PATCH = """diff --git a/src.ts b/src.ts
--- a/src.ts
+++ b/src.ts
@@ -1 +1 @@
-export const value = 0;
+export const value = 1;
"""


def test_tree_digest_matches_bridge_regular_tree_encoding() -> None:
    assert workflow_tree_digest({"file.ts": "x\n"}) == (
        "sha256:602f0f36522f6b7b005f72b1abe2d296fa2e1646073508bb243cbd0701469ee7"
    )


def groups(*, hang: bool = False) -> tuple[WorkflowTestGroup, ...]:
    command = (
        "node",
        "-e",
        "setInterval(() => {}, 1000)"
        if hang
        else "process.exit(require('fs').readFileSync('src.ts','utf8').includes('value = 1')?0:1)",
    )
    return tuple(
        WorkflowTestGroup(name=name, files={f"tests/{name}.js": "// frozen\n"}, command=command)
        for name in correctness.GROUP_NAMES
    )  # type: ignore[return-value]


def prepare_fake_toolchain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, emit_build: bool = True
) -> Path:
    tools = tmp_path / "tools"
    tools.mkdir()
    tsc = tools / "tsc"
    tsc.write_text(
        f"#!{sys.executable}\n"
        "import os\n"
        "from pathlib import Path\n"
        "import sys\n"
        "args = sys.argv[1:]\n"
        "with open(os.environ['ASSAY_TSC_LOG'], 'a', encoding='utf-8') as log:\n"
        "    log.write(' '.join(args) + '\\n')\n"
        "if args == ['--version']:\n"
        "    print('Version 5.9.2')\n"
        "elif '--outDir' in args and os.environ['ASSAY_EMIT_BUILD'] == '1':\n"
        "    output = Path(args[args.index('--outDir') + 1])\n"
        "    output.mkdir(parents=True)\n"
        "    (output / 'src.js').write_text('compiled')\n"
    )
    tsc.chmod(0o755)
    git = tools / "git"
    git.write_text('#!/bin/sh\necho call >> "$ASSAY_GIT_LOG"\nexec /usr/bin/git "$@"\n')
    git.chmod(0o755)
    node = tools / "node"
    node.write_text(
        f"#!{sys.executable}\n"
        "import os\n"
        "from pathlib import Path\n"
        "import sys\n"
        "import time\n"
        "with open(os.environ['ASSAY_NODE_LOG'], 'a', encoding='utf-8') as log:\n"
        "    log.write(sys.argv[1] + '\\n')\n"
        "if sys.argv[1:] == ['--version']:\n"
        "    print('v22.21.1')\n"
        "elif len(sys.argv) == 3 and sys.argv[1] == '-e':\n"
        "    if 'setInterval' in sys.argv[2]:\n"
        "        time.sleep(30)\n"
        "    if 'print_big' in sys.argv[2]:\n"
        "        print('x' * 1000000)\n"
        "        sys.exit(0)\n"
        "    sys.exit(0 if 'value = 1' in Path('src.ts').read_text() else 1)\n"
        "else:\n"
        "    sys.exit(2)\n"
    )
    node.chmod(0o755)
    log = tmp_path / "git.log"
    monkeypatch.setenv("ASSAY_GIT_LOG", str(log))
    monkeypatch.setenv("ASSAY_TSC_LOG", str(tmp_path / "tsc.log"))
    monkeypatch.setenv("ASSAY_NODE_LOG", str(tmp_path / "node.log"))
    monkeypatch.setenv("ASSAY_EMIT_BUILD", "1" if emit_build else "0")
    monkeypatch.setenv("PATH", str(tools) + os.pathsep + os.environ["PATH"])
    return log


async def run_fake_docker(
    monkeypatch: pytest.MonkeyPatch,
    runner: DockerWorkflowRunner,
    root: Path,
    *,
    groups_to_run: tuple[WorkflowTestGroup, ...],
    expected_tree_digest: str | None = None,
    patch: str = PATCH,
    baseline: dict[str, str] | None = None,
) -> correctness.WorkflowCorrectnessResult:
    source_tree = baseline if baseline is not None else BASELINE
    async def check_runtime() -> None:
        return None

    async def finish_cleanup(process: asyncio.subprocess.Process | None, name: str) -> bool:
        del name
        if process is not None and process.returncode is None:
            os.killpg(process.pid, signal.SIGKILL)
            await process.wait()
        return True

    monkeypatch.setattr(runner, "_check_runtime", check_runtime)
    monkeypatch.setattr(runner, "_finish_cleanup", finish_cleanup)

    async def spawn(*command: str, **kwargs: object) -> asyncio.subprocess.Process:
        assert command[:2] == ("docker", "run")
        assert "--network=none" in command
        assert "--pull=never" in command
        assert IMAGE in command
        assert "--volume" not in command and "--mount" not in command
        harness = command[-1].replace("Path('/tmp/workflow')", f"Path({str(root)!r})")
        harness = harness.replace(
            "Path('/tmp/workflow-build')", f"Path({str(root.parent / 'build')!r})"
        )
        return await REAL_SPAWN(
            sys.executable, "-I", "-S", "-c", harness, start_new_session=True, **kwargs
        )

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    return await runner.run(
        baseline=source_tree,
        baseline_tree_digest=workflow_tree_digest(source_tree),
        expected_tree_digest=expected_tree_digest
        or workflow_tree_digest({**source_tree, "src.ts": FINAL_TREE["src.ts"]}),
        patch=patch,
        groups=groups_to_run,
    )


@pytest.mark.asyncio
async def test_offline_runner_applies_patch_once_and_reports_named_groups(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = prepare_fake_toolchain(tmp_path, monkeypatch)
    runner = DockerWorkflowRunner(WorkflowRunnerSettings(image=IMAGE))
    result = await run_fake_docker(monkeypatch, runner, tmp_path / "work", groups_to_run=groups())
    assert result.verdict == "correct"
    assert [group.name for group in result.groups] == list(correctness.GROUP_NAMES)
    assert all(group.status == "passed" for group in result.groups)
    assert log.read_text().splitlines() == ["call"]
    assert (tmp_path / "tsc.log").read_text().splitlines() == [
        "--version",
        "--noEmit",
        f"--noEmit false --emitDeclarationOnly false --outDir {tmp_path / 'build'}",
    ]
    assert (tmp_path / "node.log").read_text().splitlines() == [
        "--version",
        "-e",
        "-e",
        "-e",
    ]


@pytest.mark.asyncio
async def test_candidate_timeout_and_evaluator_deadline_have_distinct_causes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepare_fake_toolchain(tmp_path, monkeypatch)
    runner = DockerWorkflowRunner(
        WorkflowRunnerSettings(image=IMAGE, candidate_timeout_s=1.0, deadline_s=10)
    )
    candidate = await run_fake_docker(
        monkeypatch, runner, tmp_path / "candidate", groups_to_run=groups(hang=True)
    )
    assert candidate.verdict == "incorrect" and candidate.cause == "candidate_timeout"
    assert all(group.cause == "candidate_timeout" for group in candidate.groups)

    runner = DockerWorkflowRunner(
        WorkflowRunnerSettings(image=IMAGE, candidate_timeout_s=10, deadline_s=0.05)
    )

    class StalledProcess:
        returncode = None

        async def communicate(self, payload: bytes) -> tuple[bytes, bytes]:
            del payload
            await asyncio.Event().wait()
            return b"", b""

    async def stalled_spawn(*args: str, **kwargs: object) -> StalledProcess:
        del args, kwargs
        return StalledProcess()

    async def check_runtime() -> None:
        return None

    async def finish_cleanup(process: object, name: str) -> bool:
        del process, name
        return True

    monkeypatch.setattr(asyncio, "create_subprocess_exec", stalled_spawn)
    monkeypatch.setattr(runner, "_check_runtime", check_runtime)
    monkeypatch.setattr(runner, "_finish_cleanup", finish_cleanup)
    infrastructure = await runner.run(
        baseline=BASELINE,
        baseline_tree_digest=workflow_tree_digest(BASELINE),
        expected_tree_digest=workflow_tree_digest(FINAL_TREE),
        patch=PATCH,
        groups=groups(hang=True),
    )
    assert infrastructure.verdict == "unavailable"
    assert infrastructure.cause == "infrastructure_deadline"


@pytest.mark.asyncio
async def test_baseline_digest_must_match_before_starting_sandbox() -> None:
    runner = DockerWorkflowRunner(WorkflowRunnerSettings(image=IMAGE))
    result = await runner.run(
        baseline=BASELINE,
        baseline_tree_digest="sha256:" + "0" * 64,
        expected_tree_digest=workflow_tree_digest(FINAL_TREE),
        patch=PATCH,
        groups=groups(),
    )
    assert result.verdict == "unavailable" and result.cause == "baseline_digest_mismatch"


@pytest.mark.asyncio
async def test_patched_tree_must_match_declared_candidate_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = prepare_fake_toolchain(tmp_path, monkeypatch)
    runner = DockerWorkflowRunner(WorkflowRunnerSettings(image=IMAGE))
    result = await run_fake_docker(
        monkeypatch,
        runner,
        tmp_path / "work",
        groups_to_run=groups(),
        expected_tree_digest="sha256:" + "0" * 64,
    )
    assert result.verdict == "unavailable"
    assert result.cause == "candidate_tree_digest_mismatch"
    assert log.read_text().splitlines() == ["call"]


@pytest.mark.asyncio
async def test_empty_patch_is_graded_against_unchanged_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = prepare_fake_toolchain(tmp_path, monkeypatch)
    runner = DockerWorkflowRunner(WorkflowRunnerSettings(image=IMAGE))
    result = await run_fake_docker(
        monkeypatch,
        runner,
        tmp_path / "work",
        groups_to_run=groups(),
        expected_tree_digest=workflow_tree_digest(BASELINE),
        patch="",
    )
    assert result.verdict == "incorrect"
    assert all(group.status == "failed" for group in result.groups)
    assert log.read_text().splitlines() == ["call"]


@pytest.mark.asyncio
async def test_candidate_output_is_bounded_before_buffering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepare_fake_toolchain(tmp_path, monkeypatch)
    runner = DockerWorkflowRunner(WorkflowRunnerSettings(image=IMAGE, max_output_bytes=4096))
    noisy_groups = tuple(
        WorkflowTestGroup(name=name, files={f"tests/{name}.js": "// frozen\n"},
                          command=("node", "-e", "print_big"))
        for name in correctness.GROUP_NAMES
    )
    result = await run_fake_docker(
        monkeypatch, runner, tmp_path / "work", groups_to_run=noisy_groups
    )
    assert result.verdict == "incorrect"
    assert all(group.cause == "output_limit" for group in result.groups)


@pytest.mark.asyncio
async def test_candidate_file_cannot_block_frozen_test_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepare_fake_toolchain(tmp_path, monkeypatch)
    runner = DockerWorkflowRunner(WorkflowRunnerSettings(image=IMAGE))
    patch = PATCH + """diff --git a/tests b/tests
new file mode 100644
--- /dev/null
+++ b/tests
@@ -0,0 +1 @@
+blocked
"""
    result = await run_fake_docker(
        monkeypatch, runner, tmp_path / "work", groups_to_run=groups(), patch=patch,
        expected_tree_digest=workflow_tree_digest({**FINAL_TREE, "tests": "blocked\n"}),
    )
    assert result.verdict == "incorrect"
    assert result.cause == "test_path_collision"


@pytest.mark.asyncio
async def test_build_requires_emitted_javascript(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepare_fake_toolchain(tmp_path, monkeypatch, emit_build=False)
    runner = DockerWorkflowRunner(WorkflowRunnerSettings(image=IMAGE))
    baseline = {**BASELINE, "tsconfig.json": '{"compilerOptions":{"noEmit":true}}'}
    result = await run_fake_docker(
        monkeypatch, runner, tmp_path / "work", groups_to_run=groups(), baseline=baseline
    )
    assert result.verdict == "incorrect"
    assert result.cause == "build_output_missing"
    assert (tmp_path / "tsc.log").read_text().splitlines()[-1] == (
        f"--noEmit false --emitDeclarationOnly false --outDir {tmp_path / 'build'}"
    )
