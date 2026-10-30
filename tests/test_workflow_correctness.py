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
        "if '--noEmit' in args and 'FAIL' in Path('src.ts').read_text():\n"
        "    sys.exit(1)\n"
        "with open(os.environ['ASSAY_TSC_LOG'], 'a', encoding='utf-8') as log:\n"
        "    log.write(' '.join(args) + '\\n')\n"
        "if args == ['--version']:\n"
        "    print('Version 5.9.3')\n"
        "elif '--noEmit' in args and '--outDir' not in args "
        "and os.environ.get('ASSAY_CHECK_VISIBLE') == '1':\n"
        "    if any('INVALID' in p.read_text() for p in Path('tests/visible').rglob('*.ts')):\n"
        "        sys.exit(1)\n"
        "elif '--outDir' in args and os.environ['ASSAY_EMIT_BUILD'] == '1':\n"
        "    output = Path(args[args.index('--outDir') + 1])\n"
        "    output.mkdir(parents=True, exist_ok=True)\n"
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
        "    if 'print_nul' in sys.argv[2]:\n"
        "        os.write(1, bytes(4096))\n"
        "        os.write(2, bytes(4096))\n"
        "        sys.exit(0)\n"
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
    enforce_extension_scope: bool = False,
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
        enforce_extension_scope=enforce_extension_scope,
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
    assert candidate.preflight == correctness.PreflightResult("passed")
    assert candidate.attribution == "candidate_failure"
    assert all(group.timeout_s == 1.0 for group in candidate.groups)

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
    assert infrastructure.attribution == "evaluator_infrastructure"


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
    assert result.preflight == correctness.PreflightResult(
        "unavailable", "candidate_tree_digest_mismatch"
    )
    assert result.attribution == "unresolved"
    assert all(group.status == "unavailable" for group in result.groups)
    assert log.read_text().splitlines() == ["call"]
    assert not (tmp_path / "tsc.log").exists()
    assert not (tmp_path / "node.log").exists()


@pytest.mark.asyncio
async def test_compile_failure_has_separate_failed_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepare_fake_toolchain(tmp_path, monkeypatch)
    runner = DockerWorkflowRunner(WorkflowRunnerSettings(image=IMAGE))
    patch = PATCH.replace("+export const value = 1;", "+export const value = FAIL;")
    final = {**BASELINE, "src.ts": "export const value = FAIL;\n"}
    result = await run_fake_docker(
        monkeypatch, runner, tmp_path / "work", groups_to_run=groups(), patch=patch,
        expected_tree_digest=workflow_tree_digest(final),
    )
    assert result.verdict == "incorrect"
    assert result.cause == "typecheck_nonzero_exit"
    assert result.preflight == correctness.PreflightResult("failed", result.cause)
    assert result.attribution == "candidate_failure"
    assert [group.status for group in result.groups] == ["unavailable"] * 3
    assert sum(group.status == "passed" for group in result.groups) == 0
    assert (tmp_path / "node.log").read_text().splitlines() == ["--version"]


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["typecheck", "build"])
async def test_missing_candidate_tool_after_version_check_fails_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    prepare_fake_toolchain(tmp_path, monkeypatch)
    tools = tmp_path / "tools"
    if stage == "typecheck":
        script = tools / "node"
        script.write_text(script.read_text() + (
            "\nif sys.argv[1:] == ['--version']:\n"
            "    Path(__file__).with_name('tsc').unlink()\n"
        ))
    else:
        script = tools / "tsc"
        script.write_text(script.read_text() + (
            "\nif args == ['--noEmit']:\n"
            "    Path(__file__).unlink()\n"
        ))
    runner = DockerWorkflowRunner(WorkflowRunnerSettings(image=IMAGE))
    result = await run_fake_docker(
        monkeypatch, runner, tmp_path / "work", groups_to_run=groups()
    )
    cause = f"{stage}_toolchain_unavailable"
    assert result.verdict == "incorrect" and result.cause == cause
    assert result.preflight == correctness.PreflightResult("failed", cause)
    assert result.attribution == "candidate_failure"
    assert all(group.status == "unavailable" for group in result.groups)
    assert (tmp_path / "node.log").read_text().splitlines() == ["--version"]


@pytest.mark.asyncio
async def test_protected_config_edit_is_restored_and_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepare_fake_toolchain(tmp_path, monkeypatch)
    runner = DockerWorkflowRunner(WorkflowRunnerSettings(image=IMAGE))
    baseline = {**BASELINE, "tsconfig.json": "BASELINE\n"}
    patch = (
        "diff --git a/tsconfig.json b/tsconfig.json\n"
        "--- a/tsconfig.json\n+++ b/tsconfig.json\n"
        "@@ -1 +1 @@\n-BASELINE\n+WEAKENED\n"
    )
    submitted = {**baseline, "tsconfig.json": "WEAKENED\n"}
    result = await run_fake_docker(
        monkeypatch, runner, tmp_path / "work", baseline=baseline, patch=patch,
        expected_tree_digest=workflow_tree_digest(submitted), groups_to_run=groups(),
    )
    assert result.preflight == correctness.PreflightResult("passed")
    assert (tmp_path / "work" / "tsconfig.json").read_text() == "BASELINE\n"
    assert result.rejected_changes == (correctness.RejectedChange(
        "tsconfig.json", "restored", correctness.digest_bytes(b"BASELINE\n"),
        correctness.digest_bytes(b"WEAKENED\n"),
    ),)


@pytest.mark.asyncio
async def test_extension_scope_refuses_other_paths_and_records_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepare_fake_toolchain(tmp_path, monkeypatch)
    runner = DockerWorkflowRunner(WorkflowRunnerSettings(image=IMAGE))
    patch = (
        "diff --git a/README.md b/README.md\nnew file mode 100644\n"
        "--- /dev/null\n+++ b/README.md\n@@ -0,0 +1 @@\n+candidate\n"
    )
    source_tree = {**BASELINE, "README.md": "candidate\n"}
    result = await run_fake_docker(
        monkeypatch, runner, tmp_path / "work", groups_to_run=groups(), patch=patch,
        expected_tree_digest=workflow_tree_digest(source_tree),
        enforce_extension_scope=True,
    )
    assert result.verdict == "incorrect" and result.cause == "patch_rejected"
    assert result.preflight == correctness.PreflightResult("failed", "patch_rejected")
    assert all(group.status == "unavailable" for group in result.groups)
    assert result.rejected_changes == (correctness.RejectedChange(
        "README.md", "refused", None, correctness.digest_bytes(b"candidate\n"),
    ),)


@pytest.mark.asyncio
async def test_digest_mismatch_precedes_protected_restoration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepare_fake_toolchain(tmp_path, monkeypatch)
    runner = DockerWorkflowRunner(WorkflowRunnerSettings(image=IMAGE))
    baseline = {**BASELINE, "tsconfig.json": "BASELINE\n"}
    patch = (
        "diff --git a/tsconfig.json b/tsconfig.json\n"
        "--- a/tsconfig.json\n+++ b/tsconfig.json\n"
        "@@ -1 +1 @@\n-BASELINE\n+WEAKENED\n"
    )
    result = await run_fake_docker(
        monkeypatch, runner, tmp_path / "work", baseline=baseline, patch=patch,
        expected_tree_digest="sha256:" + "0" * 64, groups_to_run=groups(),
        enforce_extension_scope=True,
    )
    assert result.verdict == "unavailable"
    assert result.cause == "candidate_tree_digest_mismatch"
    assert result.attribution == "unresolved"
    assert (tmp_path / "work" / "tsconfig.json").read_text() == "WEAKENED\n"
    assert not (tmp_path / "tsc.log").exists()
    assert not (tmp_path / "node.log").exists()


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
    assert all(len(group.stdout.encode()) <= 4096 for group in result.groups)
    assert all(group.exit_status is None for group in result.groups)


@pytest.mark.asyncio
async def test_json_escaped_group_output_preserves_completed_grade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepare_fake_toolchain(tmp_path, monkeypatch)
    runner = DockerWorkflowRunner(WorkflowRunnerSettings(image=IMAGE, max_output_bytes=4096))
    nul_groups = tuple(
        WorkflowTestGroup(name=name, files={f"tests/{name}.js": "// frozen\n"},
                          command=("node", "-e", "print_nul"))
        for name in correctness.GROUP_NAMES
    )
    result = await run_fake_docker(
        monkeypatch, runner, tmp_path / "work", groups_to_run=nul_groups
    )
    assert result.verdict == "correct"
    assert result.preflight == correctness.PreflightResult("passed")
    assert all(group.status == "passed" and group.exit_status == 0 for group in result.groups)
    assert all(group.stdout == "\x00" * 4096 for group in result.groups)
    assert all(group.stderr == "\x00" * 4096 for group in result.groups)


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
@pytest.mark.parametrize("blocked", ["tests", "tests/visible"])
async def test_candidate_file_blocking_visible_restoration_is_a_collision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, blocked: str
) -> None:
    frozen_path = "tests/visible/frozen.test.ts"
    baseline = {**BASELINE, frozen_path: "// frozen\n"}
    patch = (
        f"diff --git a/{frozen_path} b/{frozen_path}\n"
        "deleted file mode 100644\n"
        f"--- a/{frozen_path}\n+++ /dev/null\n"
        "@@ -1 +0,0 @@\n-// frozen\n"
        f"diff --git a/{blocked} b/{blocked}\n"
        "new file mode 100644\n"
        f"--- /dev/null\n+++ b/{blocked}\n"
        "@@ -0,0 +1 @@\n+blocked\n"
    )
    visible = WorkflowTestGroup(
        name="visible_regression", files={frozen_path: "// frozen\n"},
        command=("node", "--version"), restores=True,
    )
    hidden = tuple(
        WorkflowTestGroup(
            name=name, files={f"tests/hidden/{name}.ts": "// test\n"},
            command=("node", "--version"),
        )
        for name in ("hidden_regression", "new_behavior")
    )
    runner = DockerWorkflowRunner(WorkflowRunnerSettings(image=IMAGE))
    result = await run_fake_docker(
        monkeypatch, runner, tmp_path / "work", baseline=baseline, patch=patch,
        expected_tree_digest=workflow_tree_digest({**BASELINE, blocked: "blocked\n"}),
        groups_to_run=(visible, *hidden),
    )
    assert result.verdict == "incorrect", result
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


def prepare_fake_bun(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A bun that logs each call and whether frozen hidden tests existed at that moment."""
    prepare_fake_toolchain(tmp_path, monkeypatch)
    log = tmp_path / "bun.log"
    bun = tmp_path / "tools" / "bun"
    bun.write_text(
        f"#!{sys.executable}\n"
        "import os, sys\n"
        "from pathlib import Path\n"
        "args = sys.argv[1:]\n"
        "with open(os.environ['ASSAY_BUN_LOG'], 'a', encoding='utf-8') as log:\n"
        "    log.write(' '.join(args) + '|' + str(Path('tests/hidden').exists()) + '\\n')\n"
        "if args == ['--version']:\n"
        "    print('1.3.13')\n"
        "elif args[0] == 'build':\n"
        "    sys.exit(0)\n"
        "elif args[0] == 'test':\n"
        "    frozen = Path('tests/visible.test.ts')\n"
        "    if frozen.exists() and 'weakened' in frozen.read_text():\n"
        "        sys.exit(0)\n"
        "    sys.exit(0 if 'value = 1' in Path('src.ts').read_text() else 1)\n"
    )
    bun.chmod(0o755)
    monkeypatch.setenv("ASSAY_BUN_LOG", str(log))
    return log


def bun_groups(visible: dict[str, str]) -> tuple[WorkflowTestGroup, ...]:
    return (
        WorkflowTestGroup(name="visible_regression", files=visible,
                          command=("bun", "test", "./tests/visible.test.ts"), restores=True),
        WorkflowTestGroup(name="hidden_regression", files={"tests/hidden/r.test.ts": "//\n"},
                          command=("bun", "test", "./tests/hidden")),
        WorkflowTestGroup(name="new_behavior", files={"tests/hidden/n.test.ts": "//\n"},
                          command=("bun", "test", "./tests/hidden/n.test.ts")),
    )


@pytest.mark.asyncio
async def test_bun_mode_typechecks_and_builds_the_candidate_before_tests_arrive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = prepare_fake_bun(tmp_path, monkeypatch)
    baseline = {**BASELINE, "src/lib.ts": "export {};\n",
                "tests/visible.test.ts": "// frozen visible\n"}
    runner = DockerWorkflowRunner(WorkflowRunnerSettings(image=IMAGE, toolchain="bun"))
    result = await run_fake_docker(
        monkeypatch, runner, tmp_path / "work", baseline=baseline,
        groups_to_run=bun_groups({"tests/visible.test.ts": "// frozen visible\n"}),
    )
    assert result.verdict == "correct", result
    calls = log.read_text().splitlines()
    assert calls[0] == "--version|False"
    build = next(call for call in calls if call.startswith("build"))
    assert build.startswith("build --target=bun --outdir") and "src/lib.ts" in build
    assert build.endswith("|False")
    tests = [call for call in calls if call.startswith("test")]
    assert len(tests) == 3 and all(call.endswith("|True") for call in tests)
    assert (tmp_path / "tsc.log").read_text().splitlines()[-1] == "--noEmit -p tsconfig.json"


@pytest.mark.asyncio
async def test_restored_visible_tests_undo_a_candidates_edit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepare_fake_bun(tmp_path, monkeypatch)
    frozen = "// frozen visible\n"
    baseline = {**BASELINE, "src/lib.ts": "export {};\n", "tests/visible.test.ts": frozen}
    weakening = (
        "diff --git a/tests/visible.test.ts b/tests/visible.test.ts\n"
        "--- a/tests/visible.test.ts\n+++ b/tests/visible.test.ts\n"
        "@@ -1 +1 @@\n-// frozen visible\n+// weakened\n"
    )
    final = {**baseline, "tests/visible.test.ts": "// weakened\n"}
    runner = DockerWorkflowRunner(WorkflowRunnerSettings(image=IMAGE, toolchain="bun"))
    result = await run_fake_docker(
        monkeypatch, runner, tmp_path / "work", baseline=baseline, patch=weakening,
        expected_tree_digest=workflow_tree_digest(final),
        groups_to_run=bun_groups({"tests/visible.test.ts": frozen}),
    )
    # The weakened test would pass; restoring the frozen bytes makes the
    # unimplemented change fail instead.
    assert result.verdict == "incorrect", result
    assert result.groups[0].status == "failed"


@pytest.mark.asyncio
@pytest.mark.parametrize("toolchain", ["bun", "node-tsc"])
async def test_visible_test_edits_cannot_change_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, toolchain: str
) -> None:
    prepare_fake_bun(tmp_path, monkeypatch)
    monkeypatch.setenv("ASSAY_CHECK_VISIBLE", "1")
    frozen = "// frozen\n"
    path = "tests/visible/frozen.test.ts"
    baseline = {**BASELINE, "src/lib.ts": "export {};\n", path: frozen}
    visible = WorkflowTestGroup(
        name="visible_regression",
        files={path: frozen},
        command=(("bun" if toolchain == "bun" else "node"), "--version"),
        restores=True,
    )
    hidden = tuple(
        WorkflowTestGroup(
            name=name,
            files={f"tests/hidden/{name}.ts": "// test\n"},
            command=(("bun" if toolchain == "bun" else "node"), "--version"),
        )
        for name in ("hidden_regression", "new_behavior")
    )
    runner = DockerWorkflowRunner(WorkflowRunnerSettings(image=IMAGE, toolchain=toolchain))
    unchanged = await run_fake_docker(
        monkeypatch,
        runner,
        tmp_path / "unchanged",
        baseline=baseline,
        patch="",
        expected_tree_digest=workflow_tree_digest(baseline),
        groups_to_run=(visible, *hidden),
    )
    edit = (
        f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n"
        "@@ -1 +1 @@\n-// frozen\n+// INVALID\n"
        "diff --git a/tests/visible/added.test.ts b/tests/visible/added.test.ts\n"
        "new file mode 100644\n--- /dev/null\n+++ b/tests/visible/added.test.ts\n"
        "@@ -0,0 +1 @@\n+// INVALID\n"
    )
    edited = {**baseline, path: "// INVALID\n", "tests/visible/added.test.ts": "// INVALID\n"}
    result = await run_fake_docker(
        monkeypatch,
        runner,
        tmp_path / "edited",
        baseline=baseline,
        patch=edit,
        expected_tree_digest=workflow_tree_digest(edited),
        groups_to_run=(visible, *hidden),
    )
    assert (result.verdict, result.groups, result.cause, result.preflight) == (
        unchanged.verdict, unchanged.groups, unchanged.cause, unchanged.preflight
    )
    assert {item.path for item in result.rejected_changes} == {
        path, "tests/visible/added.test.ts"
    }
    assert all(item.disposition == "restored" for item in result.rejected_changes)
    assert result.verdict == "correct"


@pytest.mark.asyncio
async def test_restored_files_must_be_the_baselines_own_bytes() -> None:
    runner = DockerWorkflowRunner(WorkflowRunnerSettings(image=IMAGE, toolchain="bun"))
    baseline = {**BASELINE, "tests/visible.test.ts": "// frozen visible\n"}
    result = await runner.run(
        baseline=baseline, baseline_tree_digest=workflow_tree_digest(baseline),
        expected_tree_digest=workflow_tree_digest(baseline), patch="",
        groups=bun_groups({"tests/visible.test.ts": "// something else\n"}),
    )
    assert result.verdict == "unavailable" and result.cause == "restored_test_mismatch"


@pytest.mark.asyncio
async def test_bun_mode_rejects_node_test_commands() -> None:
    runner = DockerWorkflowRunner(WorkflowRunnerSettings(image=IMAGE, toolchain="bun"))
    result = await runner.run(
        baseline=BASELINE, baseline_tree_digest=workflow_tree_digest(BASELINE),
        expected_tree_digest=workflow_tree_digest(BASELINE), patch="", groups=groups(),
    )
    assert result.cause == "invalid_test_command"
