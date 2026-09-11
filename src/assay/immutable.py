"""Owned, read-only JSON containers that retain normal JSON serialization.

Like frozen Pydantic models, these guard the public mutation interface, not
hostile Python code deliberately calling base-class mutators.
"""

from __future__ import annotations

from typing import Any, Never


def _immutable(*args: Any, **kwargs: Any) -> Never:
    raise TypeError("governed JSON values are immutable")


class FrozenDict(dict[Any, Any]):
    __init__ = _immutable
    __setitem__ = _immutable
    __delitem__ = _immutable
    __ior__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable

    def __copy__(self) -> FrozenDict:
        return self

    def __deepcopy__(self, memo: dict[int, Any]) -> FrozenDict:
        return self


class FrozenList(list[Any]):
    __init__ = _immutable
    __setitem__ = _immutable
    __delitem__ = _immutable
    __iadd__ = _immutable
    __imul__ = _immutable
    append = _immutable
    clear = _immutable
    extend = _immutable
    insert = _immutable
    pop = _immutable
    remove = _immutable
    reverse = _immutable
    sort = _immutable

    def __copy__(self) -> FrozenList:
        return self

    def __deepcopy__(self, memo: dict[int, Any]) -> FrozenList:
        return self


def freeze(value: Any) -> Any:
    """Recursively detach JSON containers from caller-owned mutable objects."""
    if isinstance(value, dict):
        mapping = dict.__new__(FrozenDict)
        dict.__init__(mapping, ((key, freeze(item)) for key, item in value.items()))
        return mapping
    if isinstance(value, list):
        sequence = list.__new__(FrozenList)
        list.__init__(sequence, (freeze(item) for item in value))
        return sequence
    if isinstance(value, tuple):
        return tuple(freeze(item) for item in value)
    return value
