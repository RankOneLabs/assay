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
# Fixture B adds one direct dependency from pkg.a. alpha={a,b} and beta={c}
# are what make the added edge cross a boundary, so Ce moves with it.
FIXTURE_B_BEFORE = package_snapshot("pkg", {"a": ("b",), "b": (), "c": ()})
FIXTURE_B_AFTER = package_snapshot("pkg", {"a": ("b", "c"), "b": (), "c": ()})
# Fixture C creates a cycle; Fixture D removes the same closing edge.
FIXTURE_C_BEFORE = package_snapshot("pkg", {"a": ("b",), "b": ("c",), "c": ()})
FIXTURE_C_AFTER = package_snapshot("pkg", {"a": ("b",), "b": ("c",), "c": ("a",)})
FIXTURE_D_BEFORE = FIXTURE_C_AFTER
FIXTURE_D_AFTER = FIXTURE_C_BEFORE
# Fixture E routes one edge across the alpha={a,b} / beta={c,d} boundary
# without changing either component's membership.
FIXTURE_E_BEFORE = package_snapshot("pkg", {"a": ("b",), "b": (), "c": ("d",), "d": ()})
FIXTURE_E_AFTER = package_snapshot("pkg", {"a": ("b",), "b": ("c",), "c": ("d",), "d": ()})
# Fixture F raises internal cohesion inside a single alpha={a,b,c}. Its
# before-shape matches Fixture B's; the component grouping is the difference.
FIXTURE_F_BEFORE = package_snapshot("pkg", {"a": ("b",), "b": (), "c": ()})
FIXTURE_F_AFTER = package_snapshot("pkg", {"a": ("b",), "b": ("c",), "c": ("a",)})
# Fixture G holds alpha={a,b,c} at three modules and replaces its closing
# internal edge with one reaching beta={d}, so cohesion falls by reach alone.
FIXTURE_G_BEFORE = package_snapshot("pkg", {"a": ("b",), "b": ("c",), "c": ("a",), "d": ()})
FIXTURE_G_AFTER = package_snapshot("pkg", {"a": ("b",), "b": ("c",), "c": ("d",), "d": ()})
# Fixture H uses pkg.isolated with no imports or importers.
FIXTURE_H = package_snapshot("pkg", {"isolated": ()})
# Fixture I has pkg.a available for two overlapping component patterns.
FIXTURE_I = package_snapshot("pkg", {"a": ()})
# Fixture J leaves pkg.b outside the configured component.
FIXTURE_J = package_snapshot("pkg", {"a": ("b",), "b": ()})
# Exact four-leaf coupling and cohesion fixture; pkg itself is unassigned.
FIXTURE_COUPLING = package_snapshot("pkg", {"a": ("b",), "b": ("c",), "c": (), "d": ("a",)})
# Fixture K adds pkg.b -> pkg.d to the coupling fixture under the same
# alpha={a,b} / beta={c,d} split: alpha's Ce gains pkg.d, beta's incoming
# edges rise while its Ca stays {pkg.b}, and {a,b,d} closes into a cycle.
FIXTURE_K_BEFORE = FIXTURE_COUPLING
FIXTURE_K_AFTER = package_snapshot("pkg", {"a": ("b",), "b": ("c", "d"), "c": (), "d": ("a",)})
