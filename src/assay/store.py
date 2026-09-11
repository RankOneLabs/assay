"""Immutable, content-addressed object publication."""

from __future__ import annotations

import os
import re
import tempfile
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
        fd, temporary = tempfile.mkstemp(prefix=".publish-", dir=target.parent)
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
