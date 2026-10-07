"""Package-qualified, importable source snapshots for architecture tests."""

import shutil
from collections.abc import Mapping

import pytest

from assay.code_metrics import api, tools


def stub_jscpd(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace jscpd and its Node preflight so a test needs neither Node nor network."""
    which = shutil.which

    def stub_which(name: str) -> str | None:
        return f"/stub/{name}" if name in {"node", "npx"} else which(name)

    monkeypatch.setattr(api.shutil, "which", stub_which)
    monkeypatch.setattr(
        tools,
        "_jscpd",
        lambda *args: {"jscpd.clones": 0, "jscpd.duplicated_lines": 0, "cloned_lines": {}},
    )


def package_snapshot(package: str, adjacency: Mapping[str, tuple[str, ...]]) -> Mapping[str, str]:
    """Build src/<package> modules; keys and imports are relative to that package."""
    files: dict[str, str] = {f"src/{package}/__init__.py": ""}
    for module, imports in sorted(adjacency.items()):
        files[f"src/{package}/{module}.py"] = "".join(
            f"import {package}.{imported}\n" for imported in imports
        )
    return files


# Fixture A uses pkg.a -> pkg.b -> pkg.c.
FIXTURE_A = package_snapshot("pkg", {"a": ("b",), "b": ("c",), "c": ()})
# Fixture H uses pkg.isolated with no imports or importers.
FIXTURE_H = package_snapshot("pkg", {"isolated": ()})
# Fixture I has pkg.a available for two overlapping component patterns.
FIXTURE_I = package_snapshot("pkg", {"a": ()})
# Fixture J leaves pkg.b outside the configured component.
FIXTURE_J = package_snapshot("pkg", {"a": ("b",), "b": ()})
# Exact four-leaf coupling and cohesion fixture; pkg itself is unassigned.
FIXTURE_COUPLING = package_snapshot("pkg", {"a": ("b",), "b": ("c",), "c": (), "d": ("a",)})
# Fixture C creates a cycle; Fixture D removes the same closing edge.
FIXTURE_C_BEFORE = package_snapshot("pkg", {"a": ("b",), "b": ("c",), "c": ()})
FIXTURE_C_AFTER = package_snapshot("pkg", {"a": ("b",), "b": ("c",), "c": ("a",)})
FIXTURE_D_BEFORE = FIXTURE_C_AFTER
FIXTURE_D_AFTER = FIXTURE_C_BEFORE
