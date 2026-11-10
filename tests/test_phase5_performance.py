"""Phase 5 — deterministic performance budgets (2026-11-02).

Budgets are an order of magnitude above the measured baseline
(``docs/reports/evidence/phase5/performance_baseline.json``) so they catch
regressions of that size, not machine noise.  Docker execution and oracle
timings are excluded on purpose (host-dependent; reported in the
certification report, not asserted).
"""
from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "perf"))

# Measured 2026-11-02 (Windows dev host, under load): corpus total 11.8 s,
# slowest application 1.03 s (median of 3).
GENERATION_TOTAL_BUDGET_S = 120.0
GENERATION_PER_APP_BUDGET_S = 15.0
READ_P95_BUDGET_MS = 250.0


def test_corpus_generation_within_budget():
    from measure_generation import corpus, generate

    total = 0.0
    generated = 0
    for app_dir in corpus():
        elapsed, ok = generate(app_dir)
        assert elapsed < GENERATION_PER_APP_BUDGET_S, (app_dir.parent.name, elapsed)
        total += elapsed
        generated += ok
    assert total < GENERATION_TOTAL_BUDGET_S, total
    # Same outcome as the certified corpus: 45 VERIFIED applications plus
    # workload-studentproc (generates; the oracle rejects its source).
    assert generated == 46


def test_read_endpoints_latency_within_budget(monkeypatch):
    from fastapi.testclient import TestClient

    import api.app as app_module
    from api.service import Service
    from api.store import Store

    monkeypatch.delenv("CONTROL_PLANE_API_TOKEN", raising=False)
    monkeypatch.delenv("CONTROL_PLANE_ENV", raising=False)
    # Private in-memory store: the 50 applications must not leak into
    # other tests sharing the module-level service.
    monkeypatch.setattr(app_module, "_service", Service(Store()))
    client = TestClient(app_module.app)
    created = []
    for i in range(50):
        response = client.post("/applications", json={
            "name": f"perf-{i}", "workload_id": "perf", "java_entrypoint": "Main",
        })
        assert response.status_code == 201
        created.append(response.json()["id"])

    def p95(path: str) -> float:
        samples = []
        for _ in range(40):
            started = time.perf_counter()
            assert client.get(path).status_code == 200
            samples.append((time.perf_counter() - started) * 1000)
        return statistics.quantiles(samples, n=20)[18]

    for path in ("/health", "/applications", f"/applications/{created[0]}",
                 f"/applications/{created[0]}/runs"):
        assert p95(path) < READ_P95_BUDGET_MS, path
