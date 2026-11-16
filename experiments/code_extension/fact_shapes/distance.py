"""Distances measured from relative TypeScript imports and POSIX directories."""

import posixpath
import re
from collections import deque
from collections.abc import Mapping, Sequence
from pathlib import PurePosixPath

# Quoted strings and comments are opaque, so examples in documentation cannot
# create graph edges. Only static import/re-export statements are considered.
_TOKEN = re.compile(
    r'''//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`|[\w$]+|[^\s]''',
    re.S,
)


def _specifiers(source: str) -> tuple[str, ...]:
    tokens = [token for token in _TOKEN.findall(source)
              if not token.startswith(('//', '/*'))]
    result = []
    for index, token in enumerate(tokens[:-1]):
        if token not in ('import', 'export'):
            continue
        following = tokens[index + 1]
        if token == 'import' and following.startswith(('"', "'")):
            result.append(following[1:-1])
            continue
        if following in ('(', '.'):
            continue
        if token == 'export' and following not in ('{', '*', 'type'):
            continue
        for cursor in range(index + 1, len(tokens) - 1):
            if tokens[cursor] in (';', 'import', 'export', 'const', 'let', 'function'):
                break
            if tokens[cursor] == 'from' and tokens[cursor + 1].startswith(('"', "'")):
                result.append(tokens[cursor + 1][1:-1])
                break
    return tuple(result)


def imports(tree: Mapping[str, str], path: str) -> tuple[str, ...]:
    """Resolve static relative imports and re-exports to existing tree paths."""
    result: list[str] = []
    for specifier in _specifiers(tree[path]):
        if not specifier.startswith('.'):
            continue
        stem = posixpath.normpath(posixpath.join(posixpath.dirname(path), specifier))
        candidates = (
            (stem,) if stem.endswith(('.ts', '.tsx'))
            else (stem + '.ts', stem + '.tsx', stem + '/index.ts')
        )
        for candidate in candidates:
            if candidate in tree:
                result.append(candidate)
                break
    return tuple(result)


def import_hops(tree: Mapping[str, str], edit_site: str, holders: Sequence[str]) -> int | None:
    """Return the shortest directed path to any holder, including zero edges."""
    queue = deque([(edit_site, 0)])
    visited = {edit_site}
    while queue:
        path, hops = queue.popleft()
        if path in holders:
            return hops
        for target in imports(tree, path):
            if target not in visited:
                visited.add(target)
                queue.append((target, hops + 1))
    return None


def directory_hops(edit_site: str, holders: Sequence[str]) -> int:
    """Count directory edges through the deepest common ancestor."""
    if not holders:
        raise ValueError('at least one holder is required')
    source = PurePosixPath(edit_site).parent.parts
    distances = []
    for holder in holders:
        target = PurePosixPath(holder).parent.parts
        common = 0
        for left, right in zip(source, target, strict=False):
            if left != right:
                break
            common += 1
        distances.append(len(source) + len(target) - 2 * common)
    return min(distances)
