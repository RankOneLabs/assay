"""Package-qualified, importable source snapshots for architecture tests."""

from collections.abc import Mapping


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
