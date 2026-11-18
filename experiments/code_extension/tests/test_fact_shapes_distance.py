"""Distance resolution and planned layout checks."""

from pathlib import Path

from code_extension.fact_shapes.cells import CELLS
from code_extension.fact_shapes.distance import directory_hops, import_hops, imports
from code_extension.fixture import read_tree


def test_import_distances() -> None:
    tree = {
        'src/a.ts': 'import { b } from "./b"; import "package";',
        'src/b.ts': 'export { c } from "./c.ts";',
        'src/c.ts': 'import "../folder";',
        'folder/index.ts': 'import "../src/a.ts";',
        'unreachable.ts': '',
    }
    assert imports(tree, 'src/a.ts') == ('src/b.ts',)
    assert import_hops(tree, 'src/a.ts', ['src/c.ts']) == 2
    assert import_hops(tree, 'src/a.ts', ['folder/index.ts']) == 3
    assert import_hops(tree, 'src/a.ts', ['unreachable.ts']) is None
    assert import_hops(tree, 'src/a.ts', ['src/a.ts']) == 0


def test_directory_distances() -> None:
    assert directory_hops('src/a/x.ts', ['src/b/y.ts']) == 2
    assert directory_hops('src/a/x.ts', ['src/a/y.ts']) == 0
    assert directory_hops('src/a/x.ts', ['src/b/y.ts', 'src/a/z.ts']) == 0


def test_tsx_directory_import() -> None:
    tree = {'src/a.ts': 'import "./view";', 'src/view/index.tsx': ''}
    assert imports(tree, 'src/a.ts') == ('src/view/index.tsx',)
    assert import_hops(tree, 'src/a.ts', ['src/view/index.tsx']) == 1


def test_base_planned_distances() -> None:
    root = Path(__file__).resolve().parents[1] / 'fact_shapes/base'
    tree = read_tree(root)
    for cell in CELLS:
        assert directory_hops(cell.edit_site, cell.holders) == cell.directory_hops
        assert import_hops(tree, cell.edit_site, cell.holders) == cell.import_hops


def test_resolution_forms() -> None:
    tree = {
        'src/a.ts': '''import type {
          Thing,
        } from "../types";
        export * from "../view";
        import "./setup.ts";
        import "missing-package";''',
        'types/index.ts': '',
        'view.tsx': '',
        'src/setup.ts': '',
    }
    assert imports(tree, 'src/a.ts') == ('types/index.ts', 'view.tsx', 'src/setup.ts')


def test_committed_arm_distances() -> None:
    from code_extension.fact_shapes.generate import DIRECTORY, scenario_name

    shapes: dict[str, set[int]] = {}
    for cell in CELLS:
        scenario = scenario_name(cell)
        root = DIRECTORY.parent / 'fixtures' / scenario / 'repository' / cell.shape
        tree = read_tree(root)
        assert import_hops(tree, cell.edit_site, cell.holders) == cell.import_hops, cell.fact_id
        distance = directory_hops(cell.edit_site, cell.holders)
        assert distance == cell.directory_hops, cell.fact_id
        shapes.setdefault(cell.shape, set()).add(distance)
    assert len(shapes) == 6
    assert all(len(distances) == 1 for distances in shapes.values())


def test_documentation_and_dynamic_imports_are_not_edges() -> None:
    tree = {
        'a.ts': '''// import "./state.ts";
        /* export * from "./state.ts"; */
        const example = "import './state.ts'";
        const template = `import "./state.ts"`;
        const dynamic = import("./state.ts");
        export const name = "./state.ts";
        import "./real.ts";''',
        'state.ts': '',
        'real.ts': '',
    }
    assert imports(tree, 'a.ts') == ('real.ts',)
    assert import_hops(tree, 'a.ts', ['state.ts']) is None
