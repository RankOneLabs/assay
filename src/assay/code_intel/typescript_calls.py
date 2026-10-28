"""Call candidates from the symbols parse, with conservative target resolution."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Literal

from tree_sitter import Node

from assay.code_intel.models import CallEdge, ResolvedCall, SymbolDefinition, UnresolvedCall
from assay.code_metrics.models import ModuleGraphV2

type UnresolvedReason = Literal[
    "dynamic import()", "string-keyed dispatch", "any-typed value",
    "unknown target", "ambiguous target",
]


@dataclass(frozen=True)
class CallCandidate:
    caller: str
    callee: str
    file_path: str
    start_line: int
    end_line: int
    reason: UnresolvedReason | None = None
    imported: bool = False


def _text(node: Node, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _end_line(node: Node) -> int:
    return max(node.start_point.row + 1, node.end_point.row + (node.end_point.column != 0))


def _nodes(root: Node) -> list[Node]:
    pending = [root]
    found: list[Node] = []
    while pending:
        node = pending.pop()
        found.append(node)
        pending.extend(reversed(node.named_children))
    return found


def _string(node: Node, source: bytes) -> str:
    return _text(node, source).strip("\"'`")


def _has_import_call(node: Node) -> bool:
    return any(
        child.type == "call_expression"
        and (function := child.child_by_field_name("function")) is not None
        and function.type == "import"
        for child in _nodes(node)
    )


def extract_calls_from_tree(path: str, source: bytes, root: Node) -> tuple[CallCandidate, ...]:
    """Walk an existing parse; do not create another parser or import graph."""
    aliases: dict[str, str] = {}
    any_values: dict[str, str] = {}
    dynamic_values: set[str] = set()
    dispatch: dict[tuple[str, str], str] = {}
    for node in _nodes(root):
        if node.type == "import_specifier":
            name = node.child_by_field_name("name")
            if name is not None:
                local = node.named_children[-1]
                aliases[_text(local, source)] = _text(name, source)
        if node.type in ("variable_declarator", "required_parameter", "optional_parameter"):
            name = node.child_by_field_name("name")
            if name is None or name.type != "identifier":
                continue
            variable = _text(name, source)
            annotation = node.child_by_field_name("type")
            value = node.child_by_field_name("value")
            if annotation is not None and re.search(r"\bany\b", _text(annotation, source)):
                any_values[variable] = (_text(value, source)
                                        if value is not None and value.type == "identifier"
                                        else variable)
            if value is not None and _has_import_call(value):
                dynamic_values.add(variable)
            if value is not None and value.type == "object":
                for pair in value.named_children:
                    key = pair.child_by_field_name("key")
                    target = pair.child_by_field_name("value")
                    if key is not None and target is not None and target.type == "identifier":
                        dispatch[(variable, _string(key, source))] = _text(target, source)

    found: list[CallCandidate] = []
    stack: list[tuple[Node, str, bool]] = [(root, "<module>", False)]
    while stack:
        node, caller, dynamic = stack.pop()
        if node.type in ("function_declaration", "generator_function_declaration",
                         "method_definition"):
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                caller = _text(name_node, source)
        elif node.type == "variable_declarator":
            name_node = node.child_by_field_name("name")
            value = node.child_by_field_name("value")
            if name_node is not None and value is not None and value.type in (
                "arrow_function", "function_expression"
            ):
                caller = _text(name_node, source)
        if node.type == "call_expression":
            function = node.child_by_field_name("function")
            if function is not None:
                if function.type == "import":
                    dynamic = True
                elif function.type == "identifier":
                    callee_name = _text(function, source)
                    imported = callee_name in aliases
                    reason: UnresolvedReason | None = None
                    if callee_name in any_values:
                        reason = "any-typed value"
                        callee_name = any_values[callee_name]
                    elif callee_name in dynamic_values or dynamic:
                        reason = "dynamic import()"
                    found.append(CallCandidate(
                        caller, aliases.get(callee_name, callee_name), path,
                        node.start_point.row + 1, _end_line(node), reason, imported,
                    ))
                elif function.type == "subscript_expression":
                    obj = function.child_by_field_name("object")
                    index = function.child_by_field_name("index")
                    if obj is not None and index is not None:
                        dispatch_key = _string(index, source)
                        callee_name = dispatch.get(
                            (_text(obj, source), dispatch_key), dispatch_key
                        )
                        found.append(CallCandidate(
                            caller, aliases.get(callee_name, callee_name), path,
                            node.start_point.row + 1, _end_line(node),
                            "string-keyed dispatch",
                        ))
                elif function.type == "member_expression":
                    obj = function.child_by_field_name("object")
                    property_node = function.child_by_field_name("property")
                    if property_node is not None:
                        callee_name = _text(property_node, source)
                        reason = "unknown target"
                        if dynamic or (obj is not None and (
                            _has_import_call(obj) or _text(obj, source) in dynamic_values
                        )):
                            reason = "dynamic import()"
                        elif obj is not None and _text(obj, source) in any_values:
                            reason = "any-typed value"
                        found.append(CallCandidate(
                            caller, callee_name, path, node.start_point.row + 1,
                            _end_line(node), reason,
                        ))
                if _has_import_call(function):
                    dynamic = True
        stack.extend((child, caller, dynamic) for child in reversed(node.named_children))
    return tuple(found)


def resolve_call_targets(
    candidates: tuple[CallCandidate, ...], definitions: tuple[SymbolDefinition, ...],
    graph: ModuleGraphV2,
) -> tuple[CallEdge, ...]:
    """Only a unique local or imported definition is a resolved call edge."""
    names: dict[tuple[str, str], set[str]] = defaultdict(set)
    for definition in definitions:
        if definition.kind not in ("interface_declaration", "type_alias_declaration",
                                   "function_signature", "method_signature"):
            names[(definition.file_path, definition.name)].add(definition.file_path)
    imports: dict[str, set[str]] = defaultdict(set)
    for edge in graph.edges:
        imports[edge.importer].add(edge.imported)
    resolved: list[CallEdge] = []
    for candidate in candidates:
        possible = (set() if candidate.imported else
                    names.get((candidate.file_path, candidate.callee), set()).copy())
        if candidate.imported:
            for imported in imports[candidate.file_path]:
                possible.update(names.get((imported, candidate.callee), set()))
        target = next(iter(possible)) if len(possible) == 1 else None
        reason = candidate.reason
        if reason is None and not possible:
            reason = "unknown target"
        elif reason is None and len(possible) > 1:
            reason = "ambiguous target"
        resolved.append(CallEdge(
            caller=candidate.caller, callee=candidate.callee,
            file_path=candidate.file_path, start_line=candidate.start_line,
            end_line=candidate.end_line, target_path=target if reason is None else None,
            resolution=ResolvedCall() if reason is None else UnresolvedCall(reason=reason),
        ))
    return tuple(resolved)
