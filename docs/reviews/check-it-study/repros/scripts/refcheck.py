import asyncio, sys, tempfile
from pathlib import Path
from workflow_edit.fixture import load_fixture, materialize, read_tree
from assay.investigations.workflow_correctness import DockerWorkflowRunner, WorkflowRunnerSettings, workflow_tree_digest

IMAGE = "sha256:a2848a705b2c638acde713ad68f45d13b337621a510131fcf93fda7c5b8762d1"
f = load_fixture()
runner = DockerWorkflowRunner(WorkflowRunnerSettings(image=IMAGE, toolchain="bun", docker_client_version="29.9.0",
    docker_server_version="29.1.2", command_timeout_s=30.0, deadline_s=600.0, candidate_timeout_s=120.0, max_output_bytes=1_000_000))

async def check(name, patch):
    with tempfile.TemporaryDirectory() as d:
        materialize(Path(d), f.repository, patch)
        tree = {p.relative_to(d).as_posix(): p.read_text() for p in Path(d).rglob("*") if p.is_file()}
    res = await runner.run(baseline=f.repository, baseline_tree_digest=f.tree_digest,
        expected_tree_digest=workflow_tree_digest(tree), patch=patch, groups=f.groups)
    print(name, res)

async def main():
    for name in sys.argv[1:]:
        patch = {"reference": f.reference_patch, "negative": f.negative_patch, "empty": ""}[name]
        await check(name, patch)
asyncio.run(main())
