"""Immutable, content-addressed object publication."""

from __future__ import annotations

import os
import re
import tempfile
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

from assay.canonical import canonical_json, digest_bytes


class ObjectCollisionError(RuntimeError):
    pass


class ObjectIntegrityError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ObjectRef:
    digest: str

    def __post_init__(self) -> None:
        if re.fullmatch(r"sha256:[0-9a-f]{64}", self.digest) is None:
            raise ValueError(f"invalid object reference: {self.digest}")

    def __str__(self) -> str:
        return self.digest


class ObjectStore:
    def __init__(self, root: Path | str = ".assay") -> None:
        self.root = Path(root)
        self.objects = self.root / "objects" / "sha256"

    def _path(self, ref: ObjectRef | str) -> Path:
        value = ref.digest if isinstance(ref, ObjectRef) else ref
        if re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None:
            raise ValueError(f"invalid object reference: {value}")
        digest = value.removeprefix("sha256:")
        return self.objects / digest

    def publish_bytes(self, data: bytes) -> ObjectRef:
        ref = ObjectRef(digest_bytes(data))
        target = self._path(ref)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if target.read_bytes() != data:
                raise ObjectCollisionError(f"different bytes at {ref}")
            return ref
        # Staging is not part of the committed object namespace. A crash can
        # leave temporary files here without making a valid bundle corrupt.
        staging = self.root / "staging"
        staging.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".publish-", dir=staging)
        temporary_path = Path(temporary)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary_path, target)
            except FileExistsError:
                if target.read_bytes() != data:
                    raise ObjectCollisionError(f"different bytes at {ref}") from None
            directory_fd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            temporary_path.unlink(missing_ok=True)
        return ref

    def publish_json(self, value: object) -> ObjectRef:
        return self.publish_bytes(canonical_json(value))

    def read_bytes(self, ref: ObjectRef | str) -> bytes:
        data = self._path(ref).read_bytes()
        expected = ref.digest if isinstance(ref, ObjectRef) else ref
        if digest_bytes(data) != expected:
            raise ObjectIntegrityError(f"object bytes do not match {expected}")
        return data


class _VerificationSession(ObjectStore):
    """Operation-local verified bytes, never a persistent trust/cache decision.

    Repeated reads see the same verified bytes while resident. Evicted objects
    are re-read and hash-checked. Closure edges contain only references, not
    payloads; retaining them avoids walking the same closure repeatedly.
    """

    def __init__(self, source: ObjectStore, byte_limit: int = 16 * 1024 * 1024) -> None:
        super().__init__(source.root)
        self.source = source
        self.byte_limit = byte_limit
        self.cached_bytes = 0
        self.cache: OrderedDict[str, bytes] = OrderedDict()
        self.edges: dict[tuple[str, str], frozenset[tuple[str, str]]] = {}

    def read_bytes(self, ref: ObjectRef | str) -> bytes:
        key = str(ref)
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        data = self.source.read_bytes(ref)
        if len(data) <= self.byte_limit:
            while self.cached_bytes + len(data) > self.byte_limit:
                _, evicted = self.cache.popitem(last=False)
                self.cached_bytes -= len(evicted)
            self.cache[key] = data
            self.cached_bytes += len(data)
        return data


def verification_session(store: ObjectStore) -> _VerificationSession:
    """Reuse a session only inside one top-level verification/report operation."""
    return store if isinstance(store, _VerificationSession) else _VerificationSession(store)
