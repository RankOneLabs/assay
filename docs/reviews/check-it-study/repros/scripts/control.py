import asyncio, tempfile, subprocess
from pathlib import Path
from workflow_edit.fixture import load_fixture, materialize
from assay.investigations.workflow_correctness import DockerWorkflowRunner, WorkflowRunnerSettings, workflow_tree_digest
IMAGE = "sha256:a2848a705b2c638acde713ad68f45d13b337621a510131fcf93fda7c5b8762d1"
f = load_fixture()
runner = DockerWorkflowRunner(WorkflowRunnerSettings(image=IMAGE, toolchain="bun", docker_client_version="29.9.0",
    docker_server_version="29.1.2", command_timeout_s=30.0, deadline_s=600.0, candidate_timeout_s=120.0, max_output_bytes=1_000_000))
async def main():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        materialize(d, f.repository)
        subprocess.run("git init -q && git add -A && git -c commit.gpgsign=false -c core.hooksPath=/dev/null -c user.email=a@b -c user.name=a commit -qm base", shell=True, cwd=d, check=True)
        subprocess.run(["git", "apply", "-"], input=f.reference_patch.encode(), cwd=d, check=True)
        g = d / "src/domain/gates.ts"
        g.write_text(g.read_text().replace("(artifactType: string, disposition: GateDisposition)", "(artifactType: 'dev.assessment', disposition: GateDisposition)"))
        pass
        subprocess.run("git add -A", shell=True, cwd=d, check=True)
        patch = subprocess.run(["git", "diff", "--cached"], cwd=d, capture_output=True, text=True, check=True).stdout
        subprocess.run("rm -rf .git", shell=True, cwd=d, check=True)
        tree = {p.relative_to(d).as_posix(): p.read_text() for p in d.rglob("*") if p.is_file()}
    print(await runner.run(baseline=f.repository, baseline_tree_digest=f.tree_digest,
        expected_tree_digest=workflow_tree_digest(tree), patch=patch, groups=f.groups))
    # control: same patch but keep the test (should fail typecheck)
asyncio.run(main())
