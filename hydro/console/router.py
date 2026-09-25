"""Route table for the console."""

from __future__ import annotations

import dataclasses
from typing import Any, Callable, TYPE_CHECKING

from hydro.console.http import Request, Response

if TYPE_CHECKING:
    from hydro.console.controller import Controller

Handler = Callable[["Controller", Request], Response]


@dataclasses.dataclass(frozen=True)
class Route:
    method: str
    path: str
    handler: Handler


class Router:
    def __init__(self) -> None:
        self._routes: list[Route] = []

    def add(self, method: str, path: str, handler: Handler) -> None:
        self._routes.append(Route(method=method.upper(), path=path, handler=handler))

    def match(self, method: str, path: str) -> Route | None:
        for route in self._routes:
            if route.method == method.upper() and route.path == path:
                return route
        return None

    def routes(self) -> list[dict[str, str]]:
        return [
            {"method": route.method, "path": route.path} for route in sorted(
                self._routes, key=lambda route: (route.path, route.method)
            )
        ]

    def count(self) -> int:
        return len(self._routes)


def build_router() -> Router:
    from hydro.console.handlers import HandlerSet

    router = Router()
    handlers = HandlerSet()
    table: list[tuple[str, str, Callable[..., Any]]] = [
        ("GET", "/api/health", handlers.health),
        ("GET", "/api/meta", handlers.meta),
        ("GET", "/api/routes", handlers.routes),
        ("GET", "/api/units", handlers.units),
        ("GET", "/api/state", handlers.state),
        ("GET", "/api/audit", handlers.audit),
        ("GET", "/api/alarms", handlers.alarms),
        ("GET", "/api/history", handlers.history),
        ("GET", "/api/sched/plan", handlers.sched_plan),
        ("GET", "/api/sched/blocked", handlers.sched_blocked),
        ("GET", "/api/guide", handlers.guide_view),
        ("GET", "/api/cooling", handlers.cooling_view),
        ("GET", "/api/runner", handlers.runner_view),
        ("GET", "/api/gov", handlers.gov_view),
        ("GET", "/api/gov/limit", handlers.gov_limit),
        ("GET", "/api/exc", handlers.exc_view),
        ("GET", "/api/brake", handlers.brake_view),
        ("GET", "/api/intake/head", handlers.intake_head),
        ("GET", "/api/intake/baseline", handlers.intake_baseline),
        ("GET", "/api/vib", handlers.vib_view),
        ("GET", "/api/vib/sensor", handlers.vib_sensor),
        ("GET", "/api/batch", handlers.batch_view),
        ("POST", "/api/guide/open", handlers.guide_open),
        ("POST", "/api/guide/restore", handlers.guide_restore),
        ("POST", "/api/guide/stroke", handlers.guide_stroke),
        ("POST", "/api/guide/close", handlers.guide_close),
        ("POST", "/api/guide/adjust", handlers.guide_adjust),
        ("POST", "/api/guide/latch", handlers.guide_latch),
        ("POST", "/api/guide/release-latch", handlers.guide_release_latch),
        ("POST", "/api/cooling/open", handlers.cooling_open),
        ("POST", "/api/cooling/stop", handlers.cooling_stop),
        ("POST", "/api/runner/start", handlers.runner_start),
        ("POST", "/api/runner/hot-start", handlers.runner_hot_start),
        ("POST", "/api/runner/stop", handlers.runner_stop),
        ("POST", "/api/runner/rundown", handlers.runner_rundown),
        ("POST", "/api/runner/trip", handlers.runner_trip),
        ("POST", "/api/runner/reset", handlers.runner_reset),
        ("POST", "/api/runner/speed", handlers.runner_speed),
        ("POST", "/api/runner/swap-bearing", handlers.runner_swap_bearing),
        ("POST", "/api/gov/sync", handlers.gov_sync),
        ("POST", "/api/gov/reset-sync", handlers.gov_reset_sync),
        ("POST", "/api/gov/speed", handlers.gov_speed),
        ("POST", "/api/gov/threshold", handlers.gov_threshold),
        ("POST", "/api/gov/dispatch", handlers.gov_dispatch),
        ("POST", "/api/gov/recalibrate-oil", handlers.gov_recalibrate_oil),
        ("POST", "/api/gov/overspeed", handlers.gov_overspeed),
        ("POST", "/api/gov/clear-overspeed", handlers.gov_clear_overspeed),
        ("POST", "/api/gov/resume", handlers.gov_resume),
        ("POST", "/api/gov/setpoint", handlers.gov_setpoint),
        ("POST", "/api/gov/guard", handlers.gov_guard),
        ("POST", "/api/exc/apply", handlers.exc_apply),
        ("POST", "/api/exc/apply-retry", handlers.exc_apply_retry),
        ("POST", "/api/exc/reset", handlers.exc_reset),
        ("POST", "/api/exc/breaker", handlers.exc_breaker),
        ("POST", "/api/exc/trip", handlers.exc_trip),
        ("POST", "/api/brake/engage", handlers.brake_engage),
        ("POST", "/api/brake/emergency", handlers.brake_emergency),
        ("POST", "/api/brake/release", handlers.brake_release),
        ("POST", "/api/brake/reset", handlers.brake_reset),
        ("POST", "/api/intake/measure", handlers.intake_measure),
        ("POST", "/api/intake/recalibrate", handlers.intake_recalibrate),
        ("POST", "/api/intake/convert", handlers.intake_convert),
        ("POST", "/api/vib/judge", handlers.vib_judge),
        ("POST", "/api/vib/limit", handlers.vib_limit),
        ("POST", "/api/batch/open", handlers.batch_open),
        ("POST", "/api/batch/advance", handlers.batch_advance),
        ("POST", "/api/sched/advance", handlers.sched_advance),
    ]
    for method, path, handler in table:
        router.add(method, path, handler)
    return router
