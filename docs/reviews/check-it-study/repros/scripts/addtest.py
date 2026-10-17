import asyncio, tempfile
from pathlib import Path
from workflow_edit.fixture import load_fixture, materialize
from assay.investigations.workflow_correctness import DockerWorkflowRunner, WorkflowRunnerSettings, workflow_tree_digest
IMAGE = "sha256:a2848a705b2c638acde713ad68f45d13b337621a510131fcf93fda7c5b8762d1"
f = load_fixture()
runner = DockerWorkflowRunner(WorkflowRunnerSettings(image=IMAGE, toolchain="bun", docker_client_version="29.9.0",
    docker_server_version="29.1.2", command_timeout_s=30.0, deadline_s=600.0, candidate_timeout_s=120.0, max_output_bytes=1_000_000))
extra = """diff --git a/tests/visible/extra.test.ts b/tests/visible/extra.test.ts
new file mode 100644
--- /dev/null
+++ b/tests/visible/extra.test.ts
@@ -0,0 +1,3 @@
+import { test } from "bun:test";
+const unused = 1;
+test("x", () => {});
"""
async def main():
    patch = f.reference_patch + extra
    with tempfile.TemporaryDirectory() as d:
        materialize(Path(d), f.repository, patch)
        tree = {p.relative_to(d).as_posix(): p.read_text() for p in Path(d).rglob("*") if p.is_file()}
    print(await runner.run(baseline=f.repository, baseline_tree_digest=f.tree_digest,
        expected_tree_digest=workflow_tree_digest(tree), patch=patch, groups=f.groups))
asyncio.run(main())
