"""Layer 4 wiring through the real API service: library orders and dialect profile ids reach the engine.

The readiness assessment the modernize gate already runs carries discovery's per-program library orders and
DialectProfile ids as plain data; ``Service._generate_application`` hands the orders to the generator and
``Service._run_validation`` seals the profile ids into the evidence manifest.  Removing either bridge changes
the observable result (mutation checks below).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from api import discovery_routes, readiness
from api.service import Service, ServiceError
from api.store import Store
from engine.transformation.application_generator import ApplicationGenerator
from enterprise.discovery.compilers import ToolchainConfig
from enterprise.discovery.discover import DiscoveryRequest, discover
from enterprise.discovery.model import rmtree_force
from enterprise.discovery.runs import DiscoveryRunService
from tests.comparison_doubles import Candidate, Oracle
from tests.discovery.helpers import write_tree
from tests.discovery.test_compilers_applications import FakeCobc
from tests.test_library_order_wiring import L12, L21, _estate

FAKE = ToolchainConfig(backend="local", runner=FakeCobc(), which=lambda name: "/fake/cobc" if name == "cobc" else None)


@pytest.fixture()
def service(tmp_path: Path, monkeypatch):
    for name in ("CONTROL_PLANE_API_TOKEN", "CONTROL_PLANE_ROLE_TOKENS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DISCOVERY_COMPILER_BACKEND", "none")
    monkeypatch.setattr(ToolchainConfig, "from_environment", classmethod(lambda cls: FAKE))
    monkeypatch.setattr("api.service.docker_cli.docker_available_with_retry", lambda *a, **k: True)
    discovery = DiscoveryRunService(tmp_path / "discovery")
    discovery_routes.reset_service_for_tests(discovery)
    yield Service(Store())
    discovery.shutdown()
    discovery_routes.reset_service_for_tests(None)
    rmtree_force(tmp_path / "discovery")


def _application(svc: Service, root: Path):
    app = svc.create_application("orders-app", "", "wl-orders", "A", "spring_boot")
    return svc._store.update_application_fields(app.id, cobol_source_path=str(root))


def _run(svc: Service, app):
    from api.store import RunRecord

    run = RunRecord(id="run-orders", application_id=app.id, workload_id=app.workload_id,
                    stage=svc_stage(), source_path=app.cobol_source_path)
    svc._store.add_run(run)
    return run


def svc_stage():
    from api.service import RunStage

    return RunStage.CREATED


def _generated_text(project: Path) -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8", errors="replace") for p in project.rglob("*.java")}


def _estate_root(tmp_path: Path) -> Path:
    return write_tree(tmp_path / "estate", _estate(A=L12, B=L21))


# --- readiness record carries the facts ------------------------------------------------------------------------


def test_readiness_record_carries_orders_and_profile_pairs_from_discovery(service, tmp_path) -> None:
    root = _estate_root(tmp_path)
    record = service.readiness_for(str(root), "orders-app")
    assert record["library_orders"] == {"A": [list(L12)], "B": [list(L21)]}
    result = discover(DiscoveryRequest("directory", str(root), label="x"), tmp_path / "other-store")
    expected = sorted([p["file"], p["profile_id"]] for p in result.report["dialects"]["profiles"])
    assert record["dialect_profiles"] == expected and len(expected) == 4
    assert readiness.engine_wiring(record)[1] == tuple(map(tuple, expected))
    assert "library_orders" not in readiness.public(record)  # the public surface is unchanged


def test_engine_wiring_of_a_record_without_the_facts_is_empty() -> None:
    assert readiness.engine_wiring({}) == ((), ())
    assert readiness.engine_wiring(readiness.blocked_record("X", "y")) == ((), ())


# --- library orders reach the generator ------------------------------------------------------------------------


def test_modernization_generation_applies_each_programs_library_order(service, tmp_path, monkeypatch) -> None:
    root = _estate_root(tmp_path)
    app = _application(service, root)
    seen: list[object] = []
    real = ApplicationGenerator.generate

    def spy(self, application, *args, **kwargs):
        seen.append(kwargs.get("orders"))
        return real(self, application, *args, **kwargs)

    monkeypatch.setattr(ApplicationGenerator, "generate", spy)
    project, _entry = service._generate_application(app, _run(service, app))

    assert seen == [{"A": (L12,), "B": (L21,)}]
    sources = "\n".join(_generated_text(Path(project)).values())
    assert "ABCDE" in sources and "123" in sources  # A used LIB1 (123), B used LIB2 (ABCDE)


def test_dropping_the_bridge_makes_generation_fail_closed(service, tmp_path, monkeypatch) -> None:
    """Mutation check: without the orders the same estate is ambiguous and the run does not generate."""
    root = _estate_root(tmp_path)
    app = _application(service, root)
    monkeypatch.setattr(readiness, "engine_wiring", lambda record: ((), ()))
    with pytest.raises(ServiceError) as raised:
        service._generate_application(app, _run(service, app))
    assert "RATES" in str(raised.value)


# --- profile ids reach the sealed manifest ---------------------------------------------------------------------


def _validated_manifest(service, tmp_path, monkeypatch, root: Path):
    import api.service as service_module

    app = _application(service, root)
    run = _run(service, app)
    java_dir = tmp_path / "java"
    java_dir.mkdir()
    (java_dir / "Main.java").write_text("class Main {}", encoding="utf-8")

    class EntryOracle(Oracle):
        def execute(self, run_id, source_path, input_data=None, input_files=None, **_ignored):
            return super().execute(run_id, source_path, input_data, input_files)

    class Doubled(service_module.VerticalSlicePipeline):
        def __init__(self, config, candidate_adapter=None, registry=None):
            super().__init__(config, candidate_adapter=Candidate(b"HI\n", None, 0), registry=registry)
            self._oracle_adapter = EntryOracle(b"HI\n", None, 0)

    monkeypatch.setattr(service_module, "VerticalSlicePipeline", Doubled)
    monkeypatch.setattr(Service, "_run_job_lane", lambda *a, **k: None)
    monkeypatch.setattr(Service, "_persist_integrated_proof", lambda *a, **k: None)
    service._run_validation(app, run, java_dir, "Main")
    return service._store.get_run(run.id)


def test_sealed_manifest_carries_the_discovery_profile_ids(service, tmp_path, monkeypatch) -> None:
    root = _estate_root(tmp_path)
    run = _validated_manifest(service, tmp_path, monkeypatch, root)
    manifest = run.evidence_manifest  # persisted and re-decoded with its seal verified
    discovered = discover(DiscoveryRequest("directory", str(root), label="x"), tmp_path / "other-store")
    expected = tuple(sorted((p["file"], p["profile_id"]) for p in discovered.report["dialects"]["profiles"]))
    assert manifest.dialect_profiles == expected
    assert manifest.oracle_identity.profile_id is None  # four files: no single run-level id


def test_sole_file_estate_also_sets_the_oracle_profile_id(service, tmp_path, monkeypatch) -> None:
    root = write_tree(tmp_path / "solo", {"src/MAIN.cbl": _estate(A=L12)["src/A.cbl"].replace("COPY RATES.", "")})
    run = _validated_manifest(service, tmp_path, monkeypatch, root)
    manifest = run.evidence_manifest
    assert len(manifest.dialect_profiles) == 1
    assert manifest.oracle_identity.profile_id == manifest.dialect_profiles[0][1]
