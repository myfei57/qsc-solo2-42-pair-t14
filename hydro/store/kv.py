"""Atomic file backed key/value storage.

Keys use forward slashes and map directly onto a directory tree. Writes go to a
temporary sibling file and are renamed into place, so a reader never observes a
partially written value.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from hydro.domain.errors import NotFoundError


class Store:
    def __init__(self, root: os.PathLike[str] | str) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    @property
    def root(self) -> Path:
        return self._root

    def path(self, key: str) -> Path:
        return self._root / Path(key.replace("\\", "/"))

    def write_bytes(self, key: str, data: bytes) -> None:
        with self._lock:
            target = self.path(key)
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(target.name + ".tmp")
            with open(tmp, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, target)

    def read_bytes(self, key: str) -> bytes:
        with self._lock:
            target = self.path(key)
            try:
                return target.read_bytes()
            except FileNotFoundError as exc:
                raise NotFoundError("key not found: " + key) from exc

    def exists(self, key: str) -> bool:
        with self._lock:
            return self.path(key).is_file()

    def remove(self, key: str) -> None:
        with self._lock:
            target = self.path(key)
            try:
                target.unlink()
            except FileNotFoundError as exc:
                raise NotFoundError("key not found: " + key) from exc

    def list_keys(self, prefix: str = "") -> list[str]:
        with self._lock:
            found: list[str] = []
            for path in sorted(self._root.rglob("*")):
                if not path.is_file():
                    continue
                rel = path.relative_to(self._root).as_posix()
                if rel.endswith(".tmp"):
                    continue
                if rel.startswith(prefix):
                    found.append(rel)
            return found

    def write_int(self, key: str, value: int) -> None:
        self.write_bytes(key, str(int(value)).encode("utf-8"))

    def read_int(self, key: str, default: int = 0) -> int:
        try:
            raw = self.read_bytes(key)
        except NotFoundError:
            return default
        return int(raw.decode("utf-8").strip())

    def write_json(self, key: str, value: Any) -> None:
        self.write_bytes(key, json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8"))

    def read_json(self, key: str, default: Any = None) -> Any:
        try:
            raw = self.read_bytes(key)
        except NotFoundError:
            return default
        return json.loads(raw.decode("utf-8"))
