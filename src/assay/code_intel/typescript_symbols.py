"""Deterministic TypeScript/TSX symbol extraction from the pinned grammar."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass

import tree_sitter_typescript
from tree_sitter import Language, Node, Parser

from assay.code_intel.models import AstStructure, SymbolDefinition, SymbolReference
from assay.code_metrics.errors import AnalyzerFailed
from assay.code_metrics.models import LanguageCoverage

_LANGUAGE = Language(tree_sitter_typescript.language_typescript())
_TSX_LANGUAGE = Language(tree_sitter_typescript.language_tsx())
_DECLARATIONS = frozenset({
    "function_declaration", "generator_function_declaration", "class_declaration",
    "abstract_class_declaration", "interface_declaration", "type_alias_declaration",
    "enum_declaration", "method_definition", "method_signature", "function_signature",
    "variable_declarator",
})
_STRUCTURES = frozenset({
    "program", "class_body", "interface_body", "statement_block", "if_statement",
    "for_statement", "for_in_statement", "while_statement", "switch_statement",
    "call_expression", "return_statement", *_DECLARATIONS,
})
_IDENTIFIERS = frozenset({"identifier", "type_identifier", "property_identifier"})


@dataclass(frozen=True)
class TypeScriptExtraction:
    definitions: tuple[SymbolDefinition, ...]
    references: tuple[SymbolReference, ...]
    structures: tuple[AstStructure, ...]
    coverage: LanguageCoverage


def _walk(root: Node) -> Iterator[tuple[Node, str | None]]:
    stack: list[tuple[Node, str | None]] = [(root, None)]
    while stack:
        node, parent = stack.pop()
        yield node, parent
        stack.extend((child, node.type) for child in reversed(node.named_children))


def _end_line(node: Node) -> int:
    return max(node.start_point.row + 1, node.end_point.row + (node.end_point.column != 0))


def _signature(node: Node, source: bytes) -> str:
    body = node.child_by_field_name("body")
    value = node.child_by_field_name("value")
    boundary = body or value
    limit = boundary.start_byte if boundary is not None else node.end_byte
    return source[node.start_byte:limit].decode("utf-8", errors="replace").strip()[:400]


def extract_typescript_symbols(files: Mapping[str, str]) -> TypeScriptExtraction:
    """Extract source spans and identifiers without inferring runtime relations."""
    definitions: list[SymbolDefinition] = []
    references: list[SymbolReference] = []
    structures: list[AstStructure] = []
    analyzed: list[str] = []
    for path, text in sorted(files.items()):
        if not path.endswith((".ts", ".tsx", ".mts", ".cts")) or path.endswith(".d.ts"):
            continue
        source = text.encode("utf-8")
        try:
            parser = Parser(_TSX_LANGUAGE if path.endswith(".tsx") else _LANGUAGE)
            root = parser.parse(source).root_node
        except Exception as error:
            raise AnalyzerFailed(f"parse {path}: {error}") from error
        analyzed.append(path)
        definition_positions: set[tuple[int, int]] = set()
        for node, parent in _walk(root):
            if node.type in _STRUCTURES:
                structures.append(AstStructure(
                    kind=node.type, file_path=path, start_line=node.start_point.row + 1,
                    end_line=_end_line(node), parent_kind=parent,
                ))
            if node.type not in _DECLARATIONS:
                continue
            name = node.child_by_field_name("name")
            if name is None or name.type not in _IDENTIFIERS:
                continue
            definition_positions.add((name.start_byte, name.end_byte))
            definitions.append(SymbolDefinition(
                name=source[name.start_byte:name.end_byte].decode("utf-8", errors="replace"),
                kind=node.type, file_path=path, start_line=node.start_point.row + 1,
                end_line=_end_line(node), signature=_signature(node, source),
            ))
        for node, _ in _walk(root):
            if (node.type not in _IDENTIFIERS
                    or (node.start_byte, node.end_byte) in definition_positions):
                continue
            references.append(SymbolReference(
                name=source[node.start_byte:node.end_byte].decode("utf-8", errors="replace"),
                file_path=path, line=node.start_point.row + 1,
                column=node.start_point.column + 1,
            ))
    return TypeScriptExtraction(
        definitions=tuple(definitions), references=tuple(references),
        structures=tuple(structures),
        coverage=LanguageCoverage(
            language="typescript", files_seen=len(files), files_analyzed=len(analyzed),
            modules_discovered=len(analyzed),
            files_without_module=tuple(sorted(set(files) - set(analyzed))),
        ),
    )
