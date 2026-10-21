"""The API service must report real Docker availability to the engine.

Master README §14 ("capability analysis must be derived from actual
implementation capability") and §15 (fail-closed planning): the service
layer hardcoded ``docker_available=True`` when constructing the
``ModernizationConfig`` (``api/service.py``, ``_generate_application``),
so capability analysis reported the Docker infrastructure component as
SUPPORTED on hosts without Docker — a planning-honesty defect confirmed
by the runtime-proof gap-closure audit (2026-10-17, §1/§8:
``api/service.py:953``).

Red-first: against the unmodified service both probe tests fail — the
config carries ``True`` regardless of what ``engine.docker_cli.
check_docker_available`` reports.  The fix probes the real Docker CLI
instead of hardcoding, and this file pins the wiring in both
directions (probe False → False; probe True → True) so it cannot
silently flip to either extreme.
"""

from __future__ import annotations

import shutil
from types import SimpleNamespace

import pytest

from api.models import RunStage
from api.service import Service
from api.store import ApplicationRecord, RunRecord, Store


def _fake_pipeline_factory(captured: dict):
    """A pipeline double that only records the ModernizationConfig it got."""

    class FakePipeline:
        def __init__(self, config):
            captured["config"] = config

        def execute(self, progress=None):
            return SimpleNamespace(
                generation_success=True,
                generated_project_dir=captured["config"].output_dir,
                generated_entrypoint="Main",
                discovered_programs=(),
                generated_program_ids=(),
                limitations=(),
                recommendations=(),
                to_dict=lambda: {},
            )

    return FakePipeline


@pytest.fixture()
def service(tmp_path):
    store = Store(db_path=tmp_path / "docker-honesty.db")
    return Service(store)


def _run_generate(service, monkeypatch, *, probe_result: bool) -> dict:
    """Drive ``_generate_application`` with a faked engine pipeline.

    The Docker probe is patched at ``engine.docker_cli`` (the canonical
    helper) so the test exercises the real service wiring regardless of
    whether this host has a Docker daemon.
    """
    captured: dict = {}
    monkeypatch.setattr(
        "engine.modernization.pipeline.UniversalModernizationPipeline",
        _fake_pipeline_factory(captured),
    )
    monkeypatch.setattr(
        "engine.docker_cli.check_docker_available",
        lambda *args, **kwargs: probe_result,
    )

    app = ApplicationRecord(
        id="app-docker-honesty",
        name="docker-honesty",
        description="",
        workload_id="wl-docker-honesty",
        java_entrypoint="Main",
        cobol_source_path="/source",
    )
    service._store.add_application(app)
    run = RunRecord(
        id="run-docker-honesty",
        application_id=app.id,
        workload_id=app.workload_id,
        stage=RunStage.TRANSFORMING,
    )
    service._store.add_run(run)

    try:
        service._generate_application(app, run)
    finally:
        output_dir = getattr(captured.get("config"), "output_dir", None)
        if output_dir:
            shutil.rmtree(output_dir, ignore_errors=True)

    assert "config" in captured, "pipeline was never constructed"
    return captured


class TestDockerAvailabilityIsProbedNotHardcoded:
    def test_probe_false_reaches_pipeline_config(self, service, monkeypatch):
        """No Docker on the host → the engine must be told False (§14)."""
        captured = _run_generate(service, monkeypatch, probe_result=False)
        assert captured["config"].docker_available is False, (
            "api/service.py hardcoded docker_available=True: capability "
            "analysis would claim Docker infrastructure SUPPORTED on a "
            "host without Docker (planning-honesty defect)"
        )

    def test_probe_true_reaches_pipeline_config(self, service, monkeypatch):
        """Docker present → True must still flow through (no overcorrection)."""
        captured = _run_generate(service, monkeypatch, probe_result=True)
        assert captured["config"].docker_available is True
