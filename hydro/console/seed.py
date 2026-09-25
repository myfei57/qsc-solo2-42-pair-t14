"""Initial operating data for a fresh data directory."""

from __future__ import annotations

from typing import Any

from hydro.console.controller import Controller


def seed(controller: Controller) -> dict[str, Any]:
    return controller.seed()
