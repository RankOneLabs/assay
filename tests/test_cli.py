from pathlib import Path

from test_execution import execution_fixture

from assay.cli import main
from assay.execution import RunSucceeded, execute_plan
from assay.store import ObjectStore


async def test_cli_exports_and_verifies_exact_bundle(tmp_path: Path, monkeypatch) -> None:
    fixture = execution_fixture(ObjectStore(tmp_path / "store"), subject_ids=("ok",))
    result = await execute_plan(**fixture.arguments)
    assert isinstance(result, RunSucceeded)
    root = str(result.manifest_ref)
    monkeypatch.setattr("sys.argv", ["assay", "export", str(tmp_path / "store"),
                                    root, str(tmp_path / "export")])
    assert main() == 0
    monkeypatch.setattr("sys.argv", ["assay", "verify", str(tmp_path / "export"), root])
    assert main() == 0
    ObjectStore(tmp_path / "export").publish_json({"inserted": True})
    assert main() == 1
