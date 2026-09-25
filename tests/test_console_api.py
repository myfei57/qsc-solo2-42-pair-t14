"""End to end checks over the HTTP console."""

from __future__ import annotations

import json
import urllib.error
import urllib.request


def call(server, method: str, path: str, body=None):
    host, port = server.address
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        "http://{}:{}{}".format(host, port, path), data=data, method=method
    )
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8"))


def test_health_endpoint_reports_ok(server):
    status, payload = call(server, "GET", "/api/health")
    assert status == 200
    assert payload["status"] == "ok"
    assert payload["units"] == 3
    assert payload["watermark"] > 0


def test_meta_endpoint_lists_modules(server):
    status, payload = call(server, "GET", "/api/meta")
    assert status == 200
    assert "journal" in payload["modules"]
    assert payload["routes"] > 40


def test_routes_endpoint_lists_the_route_table(server):
    status, payload = call(server, "GET", "/api/routes")
    assert status == 200
    paths = {entry["path"] for entry in payload["routes"]}
    assert "/api/health" in paths
    assert "/api/gov/dispatch" in paths


def test_state_endpoint_lists_units_with_contract_fields(server):
    status, payload = call(server, "GET", "/api/state")
    assert status == 200
    first = payload["units"][0]
    assert first["id"] == "u1"
    assert first["head_state"] == "persisted"
    assert first["output_limit"] == 192.0
    assert "oil" in first["generations"]
    assert first["sync_state"] == "pending"


def test_guide_open_endpoint_opens_the_vane(server):
    status, payload = call(server, "POST", "/api/guide/open", {"unit_id": "u1"})
    assert status == 200
    assert payload["open"] is True
    assert payload["head"] == 60.0


def test_cooling_stop_endpoint_rejects_high_speed(server):
    call(server, "POST", "/api/cooling/open", {"unit_id": "u1"})
    status, payload = call(
        server, "POST", "/api/cooling/stop", {"unit_id": "u1", "value": 50.0}
    )
    assert status == 409
    assert payload["code"] == "speed-too-high"


def test_excitation_endpoint_rejects_missing_sync(server):
    status, payload = call(server, "POST", "/api/exc/apply", {"unit_id": "u1"})
    assert status == 409
    assert payload["code"] == "sync-not-confirmed"


def test_excitation_endpoint_accepts_a_valid_confirmation(server):
    call(server, "POST", "/api/gov/sync", {"unit_id": "u1", "ttl": 100})
    status, payload = call(server, "POST", "/api/exc/apply", {"unit_id": "u1"})
    assert status == 200
    assert payload["applied"] is True


def test_unknown_route_returns_not_found(server):
    status, payload = call(server, "GET", "/api/does-not-exist")
    assert status == 404
    assert payload["code"] == "not-found"


def test_audit_endpoint_filters_by_event(server):
    call(server, "POST", "/api/guide/open", {"unit_id": "u1"})
    status, payload = call(server, "GET", "/api/audit?event=guide-open&limit=5")
    assert status == 200
    assert [record["event"] for record in payload["records"]] == ["guide-open"]


def test_batch_endpoint_rejects_a_duplicate_identifier(server):
    first = call(
        server, "POST", "/api/batch/open", {"batch_id": "b1", "unit_id": "u1"}
    )
    assert first[0] == 200
    second = call(
        server, "POST", "/api/batch/open", {"batch_id": "b1", "unit_id": "u1"}
    )
    assert second[0] == 409
    assert second[1]["code"] == "duplicate-batch"


def test_sched_plan_endpoint_reports_readiness(server):
    status, payload = call(server, "GET", "/api/sched/plan?unit_id=u1&sequence=startup")
    assert status == 200
    assert payload["ready"] is True
    assert payload["next_stage"] == "head-persist"
    assert payload["stages"][0] == "head-persist"


def test_vib_judge_endpoint_flags_runout(server):
    status, payload = call(
        server, "POST", "/api/vib/judge", {"unit_id": "u1", "raw": {"s1": 9.0}}
    )
    assert status == 200
    assert payload["runout"] is True


def test_overview_page_is_served(server):
    host, port = server.address
    with urllib.request.urlopen(
        "http://{}:{}/web/overview.html".format(host, port), timeout=5
    ) as response:
        body = response.read().decode("utf-8")
    assert response.status == 200
    assert "Unit overview" in body


def test_root_path_serves_the_overview_page(server):
    host, port = server.address
    with urllib.request.urlopen("http://{}:{}/".format(host, port), timeout=5) as response:
        body = response.read().decode("utf-8")
    assert response.status == 200
    assert "Unit overview" in body
