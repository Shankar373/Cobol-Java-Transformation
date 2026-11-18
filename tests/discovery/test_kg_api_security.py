"""Knowledge-graph API security: read-only, role-gated, bounded, no path/filesystem leaks, routing order."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import discovery_routes
from api.app import app
from enterprise.discovery.model import rmtree_force
from enterprise.discovery.runs import DiscoveryRunService
from tests.discovery.test_api import TOKEN_OPERATOR, TOKEN_VIEWER, estate_zip, submit, wait

KG_PATHS = ("kg", "kg/nodes", "kg/node?id=x", "kg/neighbors?node=x", "kg/impact?node=x", "kg/path?src=a&dst=b",
            "kg/slice?node=x", "kg/diff", "kg/export")
HUGE = 10 ** 30


@pytest.fixture()
def service(tmp_path: Path, monkeypatch):
    for name in ("CONTROL_PLANE_API_TOKEN", "CONTROL_PLANE_ROLE_TOKENS"):
        monkeypatch.delenv(name, raising=False)
    svc = DiscoveryRunService(tmp_path / "discovery", workers=2)
    discovery_routes.reset_service_for_tests(svc)
    yield svc
    svc.shutdown()
    discovery_routes.reset_service_for_tests(None)
    rmtree_force(tmp_path / "discovery")


@pytest.fixture()
def run_id(service) -> str:
    client = TestClient(app)
    run = wait(client, submit(client, estate_zip()).json()["run_id"])
    assert run["state"] == "succeeded"
    return run["run_id"]


@pytest.fixture()
def client(service) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def _no_server_paths(service, response) -> None:
    text = response.text
    for fragment in (str(service.root), str(service.root).replace("\\", "/"), "Traceback", "sqlite3.", "File \""):
        assert fragment not in text, f"leaked {fragment!r}: {text[:300]}"


@pytest.mark.parametrize("suffix", KG_PATHS)
def test_kg_routes_reject_every_non_get_method(client: TestClient, run_id: str, suffix: str) -> None:
    path = suffix.split("?")[0]
    for method in ("post", "put", "patch", "delete"):
        response = getattr(client, method)(f"/discovery/runs/{run_id}/{path}")
        assert response.status_code == 405, (method, path, response.status_code)


@pytest.mark.parametrize("suffix", KG_PATHS)
def test_kg_routes_need_auth_and_accept_viewer(service, run_id: str, monkeypatch, suffix: str) -> None:
    monkeypatch.setenv("CONTROL_PLANE_ROLE_TOKENS", json.dumps({TOKEN_VIEWER: "viewer", TOKEN_OPERATOR: "operator"}))
    client = TestClient(app, raise_server_exceptions=False)
    url = f"/discovery/runs/{run_id}/{suffix}"
    assert client.get(url).status_code == 401
    assert client.get(url, headers={"Authorization": "Bearer wrong-token-0123456789abcdefgh"}).status_code in (401, 403)
    viewer = client.get(url, headers={"Authorization": f"Bearer {TOKEN_VIEWER}"})
    assert viewer.status_code not in (401, 403), viewer.text
    # Writes stay forbidden for a viewer, even on a kg path.
    assert client.post(f"/discovery/runs/{run_id}/kg", headers={"Authorization": f"Bearer {TOKEN_VIEWER}"}).status_code in (403, 405)


@pytest.mark.parametrize("bad", ["..", "%2e%2e", "not-a-run-id", "0" * 32, "A" * 32, "a" * 31, "a" * 33, "%00", "..%2f..%2fetc"])
@pytest.mark.parametrize("suffix", KG_PATHS)
def test_malformed_or_unknown_run_ids_are_404_without_leaks(client: TestClient, service, bad: str, suffix: str) -> None:
    response = client.get(f"/discovery/runs/{bad}/{suffix}")
    assert response.status_code in (404, 422), (bad, suffix, response.status_code)
    _no_server_paths(service, response)


@pytest.mark.parametrize("query", [f"limit={HUGE}", f"offset={HUGE}", f"limit={HUGE}&offset={HUGE}", "limit=-1", "offset=-1",
                                   "limit=abc", "offset=1.5", "limit=1&offset=-5"])
def test_nodes_paging_parameters_are_bounded(client: TestClient, service, run_id: str, query: str) -> None:
    response = client.get(f"/discovery/runs/{run_id}/kg/nodes?{query}")
    assert response.status_code in (200, 400, 422), (query, response.status_code, response.text[:200])
    if response.status_code == 200:
        body = response.json()
        assert body["count"] == len(body["nodes"]) <= 5000
    _no_server_paths(service, response)


def test_nodes_limit_zero_and_page_beyond_end_are_safe(client: TestClient, run_id: str) -> None:
    assert client.get(f"/discovery/runs/{run_id}/kg/nodes?limit=0").json()["nodes"] == []
    assert client.get(f"/discovery/runs/{run_id}/kg/nodes?limit=5&offset=1000000").json()["nodes"] == []


def test_neighbors_limit_is_bounded_and_negative_is_never_a_slice(client: TestClient, run_id: str) -> None:
    graph = client.get(f"/discovery/runs/{run_id}/kg/export").json()
    busy = next(e["from"] for e in graph["edges"])
    everything = client.get(f"/discovery/runs/{run_id}/kg/neighbors?node={busy}").json()["neighbors"]
    response = client.get(f"/discovery/runs/{run_id}/kg/neighbors?node={busy}&limit=-1")
    # A negative limit must be rejected or return nothing; it must not silently drop only the last neighbour.
    if response.status_code == 200:
        assert response.json()["neighbors"] == [] or response.json()["neighbors"] == everything
        assert len(everything) < 2 or response.json()["neighbors"] != everything[:-1]
    else:
        assert response.status_code in (400, 422)
    assert client.get(f"/discovery/runs/{run_id}/kg/neighbors?node={busy}&limit={HUGE}").status_code in (200, 400, 422)


@pytest.mark.parametrize("route", ["impact?node=program:PAYROLL", "slice?node=program:PAYROLL"])
@pytest.mark.parametrize("depth", [str(HUGE), "-1", "abc", "1.5", "2", "0"])
def test_depth_is_bounded(client: TestClient, service, run_id: str, route: str, depth: str) -> None:
    response = client.get(f"/discovery/runs/{run_id}/kg/{route}&depth={depth}")
    assert response.status_code in (200, 400, 404, 422), (route, depth, response.status_code, response.text[:200])
    _no_server_paths(service, response)


def test_direction_and_relation_inputs_are_validated(client: TestClient, run_id: str) -> None:
    for route in ("impact?node=x&direction=sideways", "path?src=a&dst=b&direction=;drop", "neighbors?node=x&direction=up"):
        assert client.get(f"/discovery/runs/{run_id}/kg/{route}").status_code in (400, 422)
    injected = client.get(f"/discovery/runs/{run_id}/kg/neighbors", params={"node": "x", "relation": "calls' OR '1'='1"})
    assert injected.status_code in (200, 400) and injected.status_code != 500


def test_empty_required_parameters_are_rejected(client: TestClient, run_id: str) -> None:
    for route in ("node?id=", "neighbors?node=", "impact?node=", "path?src=&dst=", "slice?node="):
        assert client.get(f"/discovery/runs/{run_id}/kg/{route}").status_code in (400, 404, 422), route
    assert client.get(f"/discovery/runs/{run_id}/kg/node").status_code == 422


@pytest.mark.parametrize("fmt", ["xml", "yaml", "JSON", "json ", "", "../../etc/passwd", "csv;ls", "%00"])
def test_unknown_export_formats_are_rejected(client: TestClient, service, run_id: str, fmt: str) -> None:
    response = client.get(f"/discovery/runs/{run_id}/kg/export", params={"format": fmt})
    assert response.status_code in (400, 422)
    _no_server_paths(service, response)


@pytest.mark.parametrize("fmt, media", [("json", "application/json"), ("dot", "text/vnd.graphviz"),
                                         ("graphml", "application/xml"), ("csv", "text/csv")])
def test_known_export_formats_have_fixed_attachment_names(client: TestClient, run_id: str, fmt: str, media: str) -> None:
    response = client.get(f"/discovery/runs/{run_id}/kg/export", params={"format": fmt})
    assert response.status_code == 200 and response.headers["content-type"].startswith(media)
    assert response.headers["content-disposition"] == f'attachment; filename="knowledge-graph.{fmt}"'


def test_exports_and_errors_do_not_contain_server_filesystem_paths(client: TestClient, service, run_id: str) -> None:
    root = str(service.root)
    for fmt in ("json", "dot", "graphml", "csv"):
        body = client.get(f"/discovery/runs/{run_id}/kg/export", params={"format": fmt}).text
        assert root not in body and root.replace("\\", "/") not in body
    for url in (f"/discovery/runs/{run_id}/kg/diff?against=../../x", f"/discovery/runs/{run_id}/kg/diff?against={'z' * 5000}",
                f"/discovery/runs/{run_id}/kg/node?id=../../../etc/passwd"):
        response = client.get(url)
        assert response.status_code in (400, 404, 414, 422), (url, response.status_code)
        _no_server_paths(service, response)


def test_diff_with_no_earlier_snapshot_is_a_clean_400(client: TestClient, run_id: str) -> None:
    response = client.get(f"/discovery/runs/{run_id}/kg/diff")
    assert response.status_code == 400 and "earlier snapshot" in response.json()["detail"]
    assert client.get(f"/discovery/runs/{run_id}/kg/diff?against=KG-doesnotexist").status_code == 404


def test_kg_routes_are_declared_before_the_generic_artefact_route() -> None:
    paths = [getattr(route, "path", "") for route in discovery_routes.router.routes]
    generic = paths.index("/discovery/runs/{run_id}/{artefact}")
    for path in paths:
        if "/kg" in path:
            assert paths.index(path) < generic, path
    assert "/discovery/runs/{run_id}/kg" in paths and "/discovery/runs/{run_id}/kg/export" in paths


def test_kg_is_not_reachable_as_an_artefact_and_artefacts_still_work(client: TestClient, run_id: str) -> None:
    # `kg` and `kg/...` are served by the kg routes (JSON snapshot), never by the artefact file matcher.
    snapshot = client.get(f"/discovery/runs/{run_id}/kg")
    assert snapshot.status_code == 200 and "graph_id" in snapshot.json()
    assert client.get(f"/discovery/runs/{run_id}/graph").status_code == 200
    assert client.get(f"/discovery/runs/{run_id}/kg/unknown").status_code == 404
