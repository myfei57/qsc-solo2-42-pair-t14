"""Shared fixtures for the control tests."""

from __future__ import annotations

import pytest

from hydro.console.controller import Controller
from hydro.console.server import ControlServer
from hydro.runtime.clock import TickClock


def build_controller(root, start: int = 0) -> Controller:
    return Controller(root, TickClock(start=start))


@pytest.fixture
def controller(tmp_path) -> Controller:
    return build_controller(tmp_path / "data")


@pytest.fixture
def seeded(controller: Controller) -> Controller:
    controller.seed()
    return controller


@pytest.fixture
def server(seeded: Controller):
    instance = ControlServer("127.0.0.1", 0, seeded).start_background()
    yield instance
    instance.shutdown()
