"""First-party Rust module graph from Cargo manifests and tree-sitter parses.

A module is one source file, identified by its snapshot path; an inline
``mod name { ... }`` belongs to the file that holds it. Crates and their
targets come from each ``Cargo.toml`` with a ``[package]`` table, and a file
is a module when a target's root reaches it through ``mod`` declarations.
"""

from __future__ import annotations

import posixpath
import tomllib
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

import tree_sitter_rust
from tree_sitter import Language, Node, Parser

from .errors import AnalyzerFailed
from .models import (
    ExternalDependencyV2,
    ImportEdgeV2,
    LanguageCoverage,
    ModuleEntryV2,
    ModuleGraphV2,
)

MANIFEST = "Cargo.toml"
# Crates every target can name without declaring them as dependencies.
_SYSROOT = frozenset({"std", "core", "alloc", "proc_macro", "test"})
_PATH_KEYWORDS = frozenset({"crate", "self", "super"})
_SCOPED = frozenset({"scoped_identifier", "scoped_type_identifier"})
_LANGUAGE = Language(tree_sitter_rust.language())

ModulePath = tuple[str, ...]


@dataclass(frozen=True)
class RustExtraction:
    graph: ModuleGraphV2
    coverage: LanguageCoverage


@dataclass
class _Crate:
    root: str
    dependencies: frozenset[str]
    # Every module path, inline ones included, with the file that holds it.
    modules: dict[ModulePath, str] = field(default_factory=dict)


@dataclass(frozen=True)
class _Context:
    crate: _Crate
    aliases: Mapping[str, tuple[_Crate, ModulePath]]


def extract_rust_graph(files: Mapping[str, str], manifests: Mapping[str, str]) -> RustExtraction:
    """Graph the files the manifests' targets reach; other Rust files have no module."""
    parser = Parser(_LANGUAGE)
    trees = {path: parser.parse(source.encode("utf-8")).root_node for path, source in files.items()}
    crates, libraries = _crates(files, manifests)
    for crate in crates:
        _module_tree(crate, crate.root, (), trees)
    edges: set[tuple[str, str]] = set()
    external: set[tuple[str, str]] = set()
    for crate in crates:
        for module, path in sorted(crate.modules.items()):
            if module and crate.modules.get(module[:-1]) == path:
                continue  # an inline module is walked with its file
            context = _Context(crate, _aliases(trees[path], crate, module, libraries))
            for segments, scope in _references(trees[path], module):
                target = _resolve(segments, scope, context, libraries)
                if isinstance(target, str):
                    if target != path:
                        edges.add((path, target))
                elif target is not None:
                    external.add((path, target[1]))
    reached = sorted({path for crate in crates for path in crate.modules.values()})
    return RustExtraction(
        graph=ModuleGraphV2(
            modules=tuple(
                ModuleEntryV2(module=path, path=path, language="rust") for path in reached
            ),
            edges=tuple(
                ImportEdgeV2(importer=importer, imported=imported)
                for importer, imported in sorted(edges)
            ),
            external_dependencies=tuple(
                ExternalDependencyV2(module=module, package=package)
                for module, package in sorted(external)
            ),
        ),
        coverage=LanguageCoverage(
            language="rust",
            files_seen=len(files),
            files_analyzed=len(reached),
            modules_discovered=len(reached),
            files_without_module=tuple(sorted(files.keys() - set(reached))),
        ),
    )


def _crates(
    files: Mapping[str, str], manifests: Mapping[str, str]
) -> tuple[list[_Crate], dict[str, _Crate]]:
    """Each package's library and its binary, test, example, bench, and build targets."""
    crates: list[_Crate] = []
    libraries: dict[str, _Crate] = {}
    for manifest_path, text in sorted(manifests.items()):
        try:
            manifest = tomllib.loads(text)
        except tomllib.TOMLDecodeError as error:
            raise AnalyzerFailed(f"parse {manifest_path}: {error}") from error
        package = manifest.get("package")
        if not isinstance(package, dict) or not isinstance(package.get("name"), str):
            continue  # a virtual workspace manifest
        directory = posixpath.dirname(manifest_path)
        # Dependencies are declared per package and per [target.<cfg>] table.
        scopes = [
            manifest,
            *(t for t in _table(manifest, "target").values() if isinstance(t, dict)),
        ]
        dependencies = frozenset(
            _crate_name(name)
            for scope in scopes
            for table in ("dependencies", "dev-dependencies", "build-dependencies")
            for name in _table(scope, table)
        )
        library = _table(manifest, "lib")
        library_root = _join(directory, str(library.get("path", "src/lib.rs")))
        if library_root in files:
            crate = _Crate(library_root, dependencies)
            crates.append(crate)
            libraries[_crate_name(str(library.get("name", package["name"])))] = crate
        for root in sorted(_target_roots(files, manifest, directory) - {library_root}):
            crates.append(_Crate(root, dependencies))
    return crates, libraries


def _target_roots(
    files: Mapping[str, str], manifest: Mapping[str, Any], directory: str
) -> set[str]:
    package = manifest["package"]
    roots: set[str] = set()
    for kind, folder in (("bin", "src/bin"), ("test", "tests"), ("example", "examples"),
                         ("bench", "benches")):  # fmt: skip
        declared = manifest.get(kind, [])
        for target in declared if isinstance(declared, list) else []:
            if isinstance(target, dict) and isinstance(target.get("path"), str):
                roots.add(_join(directory, target["path"]))
        if package.get(f"auto{kind}s", True) is False:
            continue
        # A target is folder/name.rs or folder/name/main.rs.
        prefix = _join(directory, folder) + "/"
        for path in files:
            rest = path.removeprefix(prefix)
            nested_main = rest.count("/") == 1 and rest.endswith("/main.rs")
            if rest != path and ("/" not in rest or nested_main):
                roots.add(path)
    main = _join(directory, "src/main.rs")
    if main in files and package.get("autobins", True) is not False:
        roots.add(main)
    build = package.get("build", "build.rs")
    if isinstance(build, str) and _join(directory, build) in files:
        roots.add(_join(directory, build))
    return {root for root in roots if root in files}


def _module_tree(crate: _Crate, path: str, module: ModulePath, trees: Mapping[str, Node]) -> None:
    """Record *path* as *module* and follow its ``mod`` declarations."""
    if module in crate.modules:
        return
    crate.modules[module] = path
    is_root = path == crate.root or posixpath.basename(path) == "mod.rs"
    children = posixpath.dirname(path) if is_root else posixpath.splitext(path)[0]
    _declarations(crate, trees[path], path, module, children, posixpath.dirname(path), trees)


def _declarations(
    crate: _Crate,
    node: Node,
    path: str,
    module: ModulePath,
    children: str,
    attribute_base: str,
    trees: Mapping[str, Node],
) -> None:
    for item in node.named_children:
        if item.type != "mod_item":
            continue
        name = _text(item.child_by_field_name("name"))
        body = item.child_by_field_name("body")
        target = _path_attribute(item)
        if body is not None:
            crate.modules.setdefault((*module, name), path)
            directory = posixpath.join(children, name)
            _declarations(crate, body, path, (*module, name), directory, directory, trees)
            continue
        candidates = (
            [posixpath.normpath(posixpath.join(attribute_base, target))]
            if target is not None
            else [posixpath.join(children, f"{name}.rs"), posixpath.join(children, name, "mod.rs")]
        )
        found = next((candidate for candidate in candidates if candidate in trees), None)
        if found is not None:
            _module_tree(crate, found, (*module, name), trees)


def _path_attribute(item: Node) -> str | None:
    """The ``#[path = "..."]`` value on the attributes just before a ``mod`` item."""
    sibling = item.prev_named_sibling
    while sibling is not None and sibling.type == "attribute_item":
        attribute = sibling.named_children[0] if sibling.named_children else None
        names = attribute.named_children if attribute is not None else []
        if attribute is not None and names and _text(names[0]) == "path":
            value = attribute.child_by_field_name("value")
            if value is not None and value.type == "string_literal":
                return _text(value).strip('"')
        sibling = sibling.prev_named_sibling
    return None


def _aliases(
    tree: Node, crate: _Crate, module: ModulePath, libraries: Mapping[str, _Crate]
) -> dict[str, tuple[_Crate, ModulePath]]:
    """Names a file's ``use`` declarations bind to modules, scope ignored."""
    aliases: dict[str, tuple[_Crate, ModulePath]] = {}
    context = _Context(crate, {})
    for node in _walk(tree):
        if node.type != "use_declaration":
            continue
        scope = _scope(node, module)
        for segments, alias in _use_paths(node.child_by_field_name("argument"), ()):
            located = _locate(segments, scope, context, libraries)
            if alias and located is not None and located[1] in located[0].modules:
                aliases[alias] = located
    return aliases


def _references(tree: Node, module: ModulePath) -> Iterator[tuple[list[str], ModulePath]]:
    """Every path the file names, with the module it is named in."""
    for node in _walk(tree):
        if node.type == "use_declaration":
            scope = _scope(node, module)
            for segments, _ in _use_paths(node.child_by_field_name("argument"), ()):
                yield segments, scope
        elif node.type == "extern_crate_declaration":
            yield [_text(node.child_by_field_name("name"))], _scope(node, module)
        elif node.type in _SCOPED and not _inside(node, "use_declaration"):
            if node.parent is None or node.parent.type not in _SCOPED:
                yield _scoped(node), _scope(node, module)
        elif node.type == "token_tree" and not _inside(node, "token_tree"):
            for segments in _token_paths(node):
                yield segments, _scope(node, module)


def _scope(node: Node, module: ModulePath) -> ModulePath:
    """The module *node* sits in: the file's module and the inline modules around it."""
    inline: list[str] = []
    parent = node.parent
    while parent is not None:
        if parent.type == "mod_item":
            inline.append(_text(parent.child_by_field_name("name")))
        parent = parent.parent
    return (*module, *reversed(inline))


def _resolve(
    segments: list[str], scope: ModulePath, context: _Context, libraries: Mapping[str, _Crate]
) -> str | tuple[None, str] | None:
    """The file a path names, the external crate it starts with, or None for neither."""
    located = _locate(segments, scope, context, libraries)
    if located is None:
        first = segments[0] if segments else ""
        if first in _SYSROOT or first in context.crate.dependencies:
            return (None, first)
        return None
    crate, path = located
    # The root module is always present, so some prefix always names a file.
    length = max(n for n in range(len(path) + 1) if path[:n] in crate.modules)
    return crate.modules[path[:length]]


def _locate(
    segments: list[str], scope: ModulePath, context: _Context, libraries: Mapping[str, _Crate]
) -> tuple[_Crate, ModulePath] | None:
    """The crate and full module path a path names, or None when it is not first-party."""
    if not segments:
        return None
    first, rest = segments[0], segments[1:]
    crate = context.crate
    if first == "crate":
        return crate, tuple(rest)
    if first in ("self", "super"):
        base = list(scope)
        index = 0
        while index < len(segments) and segments[index] in ("self", "super"):
            if segments[index] == "super" and base:
                base.pop()
            index += 1
        return crate, (*base, *segments[index:])
    if first == "":  # a leading "::" names a crate
        return (libraries[rest[0]], tuple(rest[1:])) if rest and rest[0] in libraries else None
    if first in context.aliases:
        aliased, base_path = context.aliases[first]
        return aliased, (*base_path, *rest)
    if (*scope, first) in crate.modules:
        return crate, (*scope, *segments)
    if first in libraries:
        return libraries[first], tuple(rest)
    return None


def _use_paths(node: Node | None, prefix: ModulePath) -> Iterator[tuple[list[str], str | None]]:
    """Expand a ``use`` tree into its paths, each with the name it binds, if any."""
    if node is None:
        return
    kind = node.type
    if kind in ("identifier", "crate", "self", "super", "metavariable"):
        name = _text(node)
        if kind == "self" and prefix:
            yield list(prefix), prefix[-1]
        else:
            yield [*prefix, name], name
    elif kind == "scoped_identifier":
        segments = [*prefix, *_scoped(node)]
        yield segments, segments[-1]
    elif kind == "use_as_clause":
        for segments, _ in _use_paths(node.child_by_field_name("path"), prefix):
            yield segments, _text(node.child_by_field_name("alias"))
    elif kind == "use_wildcard":
        wildcard = node.named_children[0] if node.named_children else None
        yield [*prefix, *(_scoped(wildcard) if wildcard is not None else [])], None
    elif kind == "scoped_use_list":
        head = node.child_by_field_name("path")
        inner = tuple(_scoped(head)) if head is not None else ()
        yield from _use_paths(node.child_by_field_name("list"), (*prefix, *inner))
    elif kind == "use_list":
        for child in node.named_children:
            yield from _use_paths(child, prefix)


def _scoped(node: Node) -> list[str]:
    """The segments of a possibly nested path node; a leading ``::`` is an empty segment."""
    if node.type not in _SCOPED and node.type != "scoped_use_list":
        return [_text(node)]
    path = node.child_by_field_name("path")
    name = node.child_by_field_name("name")
    head = _scoped(path) if path is not None else [""]
    return [*head, _text(name)] if name is not None else head


def _token_paths(node: Node) -> Iterator[list[str]]:
    """Paths spelled inside a macro's token tree, such as ``crate::a::f`` in ``vec![...]``."""
    tokens = [child for child in _walk(node) if child.child_count == 0]
    current: list[str] = []
    expect_segment = True
    for token in tokens:
        if token.type == "::":
            expect_segment = True
            if not current:
                current = [""]
            continue
        word = token.type in ("identifier", *_PATH_KEYWORDS)
        if word and expect_segment:
            current.append(_text(token))
            expect_segment = False
            continue
        if len(current) > 1:
            yield current
        current = [_text(token)] if word else []
        expect_segment = not word
    if len(current) > 1:
        yield current


def _walk(node: Node) -> Iterator[Node]:
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(current.children))


def _inside(node: Node, kind: str) -> bool:
    parent = node.parent
    while parent is not None:
        if parent.type == kind:
            return True
        parent = parent.parent
    return False


def _text(node: Node | None) -> str:
    return node.text.decode("utf-8") if node is not None and node.text is not None else ""


def _table(manifest: Mapping[str, Any], key: str) -> dict[str, Any]:
    value = manifest.get(key, {})
    return value if isinstance(value, dict) else {}


def _crate_name(name: str) -> str:
    return name.replace("-", "_")


def _join(directory: str, path: str) -> str:
    return posixpath.normpath(posixpath.join(directory, path))
