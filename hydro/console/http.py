"""Request and response value objects for the console."""

from __future__ import annotations

import dataclasses
from typing import Any

Response = tuple[int, dict[str, Any]]


@dataclasses.dataclass(frozen=True)
class Request:
    method: str
    path: str
    query: dict[str, str]
    body: dict[str, Any]

    def unit_id(self) -> str:
        value = self.body.get("unit_id") or self.query.get("unit_id") or ""
        return str(value)

    def number(self, key: str, default: float = 0.0) -> float:
        raw = self.body.get(key, self.query.get(key, default))
        return float(raw) if raw is not None and raw != "" else default

    def integer(self, key: str, default: int = 0) -> int:
        raw = self.body.get(key, self.query.get(key, default))
        if raw is None or raw == "":
            return default
        return int(float(raw))

    def text(self, key: str, default: str = "") -> str:
        raw = self.body.get(key, self.query.get(key, default))
        return default if raw is None else str(raw)

    def raw_map(self, key: str = "raw") -> dict[str, float]:
        raw = self.body.get(key) or {}
        return {str(k): float(v) for k, v in raw.items()}


def ok(payload: dict[str, Any]) -> Response:
    return 200, payload


def bad_request(message: str) -> Response:
    return 400, {"error": message, "code": "bad-request"}


def not_found(message: str) -> Response:
    return 404, {"error": message, "code": "not-found"}
