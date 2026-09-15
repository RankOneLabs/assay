from __future__ import annotations

import builtins
import sys
from pathlib import Path

import pytest

from assay.cli import main
from assay.review import export as review_export
from assay.store import ObjectStore


def _reject_review_server_import(
    monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    original_import = builtins.__import__
    monkeypatch.delitem(sys.modules, "assay.review.server", raising=False)

    def guarded_import(
        name: str,
        globals: dict[str, object] | None = None,
        locals: dict[str, object] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> object:
        if name == "assay.review.server":
            raise ImportError(f"No module named {missing!r}", name=missing)
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)


def test_review_help_does_not_import_server(monkeypatch: pytest.MonkeyPatch) -> None:
    _reject_review_server_import(monkeypatch, "fastapi")
    monkeypatch.setattr(sys, "argv", ["assay", "review", "--help"])

    with pytest.raises(SystemExit) as stopped:
        main()

    assert stopped.value.code == 0


def test_review_serve_missing_extra_has_actionable_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _reject_review_server_import(monkeypatch, "fastapi")
    monkeypatch.setattr(sys, "argv", ["assay", "review", "serve", "store"])

    assert main() == 1
    output = capsys.readouterr()
    assert "assay[review]" in output.out
    assert "Traceback" not in output.out + output.err


def test_review_serve_does_not_misreport_unrelated_import_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _reject_review_server_import(monkeypatch, "review_internal_bug")
    monkeypatch.setattr(sys, "argv", ["assay", "review", "serve", "store"])

    assert main() == 1
    output = capsys.readouterr()
    assert "review_internal_bug" in output.out
    assert "assay[review]" not in output.out
    assert "Traceback" not in output.out + output.err


def test_review_export_works_without_server_extra(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[Path, str, Path]] = []

    def export(store: ObjectStore, root_ref: str, output: str) -> None:
        calls.append((store.root, root_ref, Path(output)))

    monkeypatch.setattr(review_export, "export_review", export)
    _reject_review_server_import(monkeypatch, "fastapi")
    output = tmp_path / "review.html"
    monkeypatch.setattr(
        sys,
        "argv",
        ["assay", "review", "export", str(tmp_path / "store"), "sha256:root", str(output)],
    )

    assert main() == 0
    assert calls == [(tmp_path / "store", "sha256:root", output)]


def test_review_serve_enforces_remote_opt_in_and_uses_cli_default_port(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pytest.importorskip("fastapi")
    uvicorn = pytest.importorskip("uvicorn")
    calls: list[tuple[str, int]] = []

    def run(app: object, *, host: str, port: int) -> None:
        calls.append((host, port))

    monkeypatch.setattr(uvicorn, "run", run)
    monkeypatch.setattr(
        sys,
        "argv",
        ["assay", "review", "serve", str(tmp_path / "store"), "--host", "192.0.2.10"],
    )
    with pytest.raises(SystemExit) as stopped:
        main()
    assert stopped.value.code == 2
    error = capsys.readouterr().err
    assert "usage: assay review serve" in error
    assert "python -m assay.review.server" not in error
    assert "requires --allow-remote" in error
    assert not calls

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "assay",
            "review",
            "serve",
            str(tmp_path / "store"),
            "--host",
            "192.0.2.10",
            "--allow-remote",
        ],
    )
    assert main() == 0
    assert calls == [("192.0.2.10", 7557)]
    assert "exposed remotely without authentication" in capsys.readouterr().err


@pytest.mark.parametrize("command", ["serve", "export"])
def test_runtime_import_errors_are_not_dependency_errors(
    command: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    error = ImportError("runtime import failed", name="fastapi")

    def fail(*args: object, **kwargs: object) -> None:
        raise error

    arguments = ["assay", "review", command, str(tmp_path / "store")]
    if command == "serve":
        pytest.importorskip("fastapi")
        uvicorn = pytest.importorskip("uvicorn")
        monkeypatch.setattr(uvicorn, "run", fail)
    else:
        monkeypatch.setattr(review_export, "export_review", fail)
        arguments.extend(["sha256:root", str(tmp_path / "out.html")])
    monkeypatch.setattr(sys, "argv", arguments)

    with pytest.raises(ImportError) as caught:
        main()
    assert caught.value is error
    output = capsys.readouterr()
    assert "review_" not in output.out + output.err
    assert "assay[review]" not in output.out + output.err
