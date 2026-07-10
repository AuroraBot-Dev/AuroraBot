"""Immutable object storage implementations.

Content-addressed storage via SHA-256.  Objects are never overwritten;
every write produces a new object id.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from threading import Lock


class MemoryObjectStore:
    """In-memory immutable object store for tests."""

    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}
        self._lock = Lock()

    def put(self, content: bytes) -> str:
        object_id = hashlib.sha256(content).hexdigest()
        with self._lock:
            existing = self._objects.get(object_id)
            if existing is not None and existing != content:
                msg = "hash collision detected"
                raise ValueError(msg)
            self._objects[object_id] = content
        return object_id

    def get(self, object_id: str) -> bytes:
        try:
            return self._objects[object_id]
        except KeyError as exc:
            msg = f"object not found: {object_id}"
            raise KeyError(msg) from exc

    def exists(self, object_id: str) -> bool:
        return object_id in self._objects


class FileObjectStore:
    """Local filesystem immutable object store.

    Objects are addressed by SHA-256 digest and never overwritten.
    Objects are sharded by first two hex chars for filesystem balance.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, content: bytes) -> str:
        object_id = hashlib.sha256(content).hexdigest()
        path = self._path_for(object_id)
        if path.exists():
            existing = path.read_bytes()
            if existing != content:
                msg = "hash collision detected"
                raise ValueError(msg)
            return object_id

        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(content)
        tmp.replace(path)
        return object_id

    def get(self, object_id: str) -> bytes:
        return self._path_for(object_id).read_bytes()

    def exists(self, object_id: str) -> bool:
        return self._path_for(object_id).exists()

    def _path_for(self, object_id: str) -> Path:
        if len(object_id) != 64 or any(ch not in "0123456789abcdef" for ch in object_id):
            msg = f"invalid object id: {object_id}"
            raise ValueError(msg)
        shard = self.root / object_id[:2]
        shard.mkdir(parents=True, exist_ok=True)
        return shard / object_id
