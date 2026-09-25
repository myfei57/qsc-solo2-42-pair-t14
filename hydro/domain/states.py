"""Unit lifecycle states and their allowed transitions."""

from __future__ import annotations

import enum


class UnitState(str, enum.Enum):
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    RUNDOWN = "rundown"
    TRIPPED = "tripped"


START_ACTIONS = ("start",)
STOP_ACTIONS = ("stop",)
ACTION_RESULT = {
    "start": UnitState.RUNNING,
    "stop": UnitState.STOPPING,
    "rundown": UnitState.RUNDOWN,
    "trip": UnitState.TRIPPED,
    "reset": UnitState.IDLE,
}

STARTABLE = (UnitState.IDLE, UnitState.STOPPING, UnitState.RUNDOWN)
STOPPABLE = (UnitState.RUNNING, UnitState.STARTING)


def can_start(state: UnitState) -> bool:
    return state in STARTABLE


def can_stop(state: UnitState) -> bool:
    return state in STOPPABLE


def next_state(current: UnitState, action: str) -> UnitState:
    return ACTION_RESULT.get(action, current)
