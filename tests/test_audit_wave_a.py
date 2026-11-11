"""Architecture audit Wave A (2026-11-03) — false-success routes, red first.

Items from docs/audits/ARCHITECTURE_AUDIT_2026-11-01.md re-verified open at
16cc305; each class pins one fix.
"""
from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.app import app
from api.errors import ConflictError
from api.service import Service
from api.store import Store
from engine.domain.identities import VerdictState
from tests.verified_run_support import seed_verified_api_run, seed_verified_verdict

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_store():
    import api.app as app_mod

    store = Store()
    app_mod._store = store
    app_mod._service = Service(store)
    yield store


def _create_app(name: str) -> str:
    resp = client.post("/applications", json={ "target_runtime": "spring_boot","name": name, "workload_id": "wl-wave-a"})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _start_verified_run(app_id: str) -> str:
    upload = client.post(
        f"/applications/{app_id}/upload",
        files=[("files", ("A.cob", io.BytesIO(b"A"), "text/plain"))],
    )
    assert upload.status_code == 201, upload.text
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(Service, "_modernize_background", lambda *a, **k: None)
        resp = client.post(f"/applications/{app_id}/modernize")
    assert resp.status_code == 202, resp.text
    run_id = resp.json()["run_id"]
    seed_verified_api_run(run_id)
    return run_id


def _seed_generated(run_id: str) -> None:
    import api.app as app_mod
    from api.artifact_seal import compute_generated_seal

    svc = app_mod._service
    run = svc.get_run(run_id)
    app_rec = svc.get_application(run.application_id)
    target = Path(app_rec.cobol_source_path or ".").parent / f"{app_rec.id}-generated"
    target.mkdir(parents=True, exist_ok=True)
    (target / "Main.java").write_bytes(b"class Main {}")
    app_rec.generated_app_path = str(target)
    svc._store.update_application(app_rec)
    # Real generation records the bundle on the run too (audit F7).
    svc._store.set_run_generated(run_id, str(target), None)
    svc._store.set_generated_seal(run_id, compute_generated_seal(target))


def _approve(run_id: str):
    return client.post(f"/runs/{run_id}/approval",
                       json={"decision": "APPROVED", "approver": "reviewer"})


# ---------------------------------------------------------------------------
# A4 (P0-4 / P0-5): approval bound to the attempt it checked; export
# re-checks the verdict it exports
# ---------------------------------------------------------------------------

class TestA4ApprovalAndExport:
    def test_store_refuses_an_approval_for_a_stale_generation(self, _reset_store):
        store = _reset_store
        run_id = _start_verified_run(_create_app("a4-store"))
        generation = store.get_run(run_id).validation_generation
        store.begin_revalidation(run_id)
        with pytest.raises(ConflictError):
            store.set_run_approval(run_id, state="APPROVED", approver="r", reason=None,
                                   expected_generation=generation)
        assert store.get_run(run_id).approval_state == "PENDING"

    def test_approval_racing_a_revalidation_never_lands_on_the_new_attempt(
            self, _reset_store, monkeypatch):
        import api.app as app_mod

        store = _reset_store
        app_id = _create_app("a4-race")
        run_id = _start_verified_run(app_id)
        _seed_generated(run_id)
        svc = app_mod._service
        checked = svc._require_valid_evidence

        def check_then_reset(run):
            checked(run)
            store.begin_revalidation(run_id)  # a revalidation lands in between

        monkeypatch.setattr(svc, "_require_valid_evidence", check_then_reset)
        response = _approve(run_id)
        assert response.status_code == 409, response.text
        assert store.get_run(run_id).approval_state == "PENDING"

    def test_download_rechecks_the_verdict_it_exports(self, _reset_store):
        store = _reset_store
        run_id = _start_verified_run(_create_app("a4-download"))
        _seed_generated(run_id)
        assert _approve(run_id).status_code == 200
        assert client.get(f"/runs/{run_id}/download").status_code == 200
        # The approved run's verdict is no longer VERIFIED (state the export
        # must not trust the approval column alone for).
        seed_verified_verdict(store, run_id, state=VerdictState.FAILED)
        assert store.get_run(run_id).approval_state == "APPROVED"
        response = client.get(f"/runs/{run_id}/download")
        assert response.status_code == 409, response.text


# ---------------------------------------------------------------------------
# A7 (P0-8): one verdict gate for every view that serves a verdict
# ---------------------------------------------------------------------------

class TestA7OneVerdictGate:
    @pytest.mark.parametrize("view", [
        "/runs/{run}", "/runs/{run}/detail", "/runs/{run}/verdict",
        "/applications/{app}/runs",
    ])
    def test_verified_with_integrity_invalid_evidence_is_never_served(self, view, monkeypatch):
        from engine.evidence import integrity

        app_id = _create_app("a7-gate")
        run_id = _start_verified_run(app_id)
        ok = client.get(view.format(run=run_id, app=app_id))
        assert ok.status_code == 200 and "VERIFIED" in ok.text  # served when valid

        # The stored pair still hash-matches; only full integrity fails.
        monkeypatch.setattr(integrity.EvidenceIntegrityValidator, "validate",
                            lambda self, manifest: ["forced violation"])
        response = client.get(view.format(run=run_id, app=app_id))
        assert response.status_code >= 400 or "VERIFIED" not in response.text, (
            view, response.status_code, response.text[:300])


# ---------------------------------------------------------------------------
# A5 (P0-6): a comparison pairs ORACLE with CANDIDATE of its own type, and a
# MATCH records no differences
# ---------------------------------------------------------------------------

class TestA5ComparisonPairing:
    @staticmethod
    def _validate(*, oracle_role="ORACLE", candidate_role="CANDIDATE",
                  candidate_type="STDOUT", candidate_id="art-candidate-stdout",
                  differences=()):
        from engine.domain.identities import RunId
        from engine.evidence.integrity import EvidenceIntegrityValidator
        from tests.adversarial.conftest import (
            make_artifact, make_artifact_evidence, make_comparison, make_manifest)

        run = RunId(value="engine-a5")
        oracle = make_artifact("art-oracle-stdout", "STDOUT", oracle_role, b"out")
        candidate = make_artifact("art-candidate-stdout", candidate_type, candidate_role, b"out")
        manifest = make_manifest(
            run_id=run,
            artifacts=(make_artifact_evidence(oracle, "oracle-exec-1"),
                       make_artifact_evidence(candidate, "candidate-exec-1")),
            comparisons=(make_comparison(run, result="MATCH", candidate_id=candidate_id,
                                         differences=differences),),
        )
        return EvidenceIntegrityValidator().validate(manifest)

    def test_a_genuine_pair_validates(self):
        from engine.evidence.integrity import ValidatedEvidenceManifest

        assert isinstance(self._validate(), ValidatedEvidenceManifest)

    @pytest.mark.parametrize("tamper", [
        {"candidate_id": "art-oracle-stdout"},          # compared with itself
        {"candidate_role": "ORACLE"},                    # two oracle artifacts
        {"oracle_role": "CANDIDATE"},                    # two candidate artifacts
        {"candidate_type": "TEXT_FILE"},                 # STDOUT vs a file
        {"differences": ("line 1 differs",)},            # MATCH with differences
    ])
    def test_tampered_pairing_never_validates(self, tamper):
        from engine.evidence.integrity import ValidatedEvidenceManifest

        outcome = self._validate(**tamper)
        assert not isinstance(outcome, ValidatedEvidenceManifest), tamper
        assert outcome, tamper


# ---------------------------------------------------------------------------
# A3 (P0-3): mapping state is per job, not module-global (the API maps on up
# to four threads at once)
# ---------------------------------------------------------------------------

_ENTRY_PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ENTRYP.
       PROCEDURE DIVISION.
           DISPLAY "ENTRY"
           STOP RUN.
"""


class TestA3MappingStateIsolation:
    def test_entry_lowering_on_one_thread_does_not_leak_into_another(self, monkeypatch):
        import threading

        import engine.transformation.cobol_to_java_mapping as m
        from engine.transformation.cobol_parser import CobolParser
        from engine.transformation.ir import ExitProgramStatement
        from engine.transformation.java_ir import JavaReturn

        entry = CobolParser().parse(_ENTRY_PROGRAM)
        entry_stmts = {id(s) for p in entry.paragraphs for s in p.statements} | {
            id(s) for s in getattr(entry, "statements", ())}
        real = m.map_cobol_statement
        paused, resume = threading.Event(), threading.Event()
        seen: list[list] = []

        def pausing(stmt, *args, **kwargs):
            if id(stmt) in entry_stmts:
                paused.set()           # thread A is lowering ENTRYP right now
                resume.wait(10)
                resume.clear()
            return real(stmt, *args, **kwargs)

        monkeypatch.setattr(m, "map_cobol_statement", pausing)
        worker = threading.Thread(target=m.map_cobol_program_to_java, args=(entry,))
        worker.start()
        try:
            while worker.is_alive():
                if paused.wait(0.2):
                    paused.clear()
                    # thread B: EXIT PROGRAM of a CALLed program must return
                    seen.append(real(ExitProgramStatement(), None, None))
                    resume.set()
        finally:
            resume.set()
            worker.join(10)
        assert seen, "the entry program was never lowered"
        for lowered in seen:
            assert any(isinstance(s, JavaReturn) for s in lowered), lowered

    def test_generated_names_are_per_thread(self):
        import threading

        import engine.transformation.cobol_to_java_mapping as m

        m._reset_file_io_vars()
        first = m._fresh_io_var("read")
        other: list[str] = []

        def elsewhere():
            m._reset_file_io_vars()
            other.extend(m._fresh_io_var("read") for _ in range(3))

        t = threading.Thread(target=elsewhere)
        t.start()
        t.join()
        assert first == "_read_0" and other == ["_read_0", "_read_1", "_read_2"]
        assert m._fresh_io_var("read") == "_read_1"  # this thread's sequence continues


# ---------------------------------------------------------------------------
# A6 (P0-7): renderers and the Spring lane fail closed
# ---------------------------------------------------------------------------

class TestA6FailClosed:
    def test_unknown_expression_raises_in_both_renderers(self):
        from engine.transformation.java_generator import JavaGenerator
        from engine.transformation.java_ir import JavaExpression
        from engine.transformation.spring_boot_generator import SpringBootGenerator

        class Unknown(JavaExpression):
            pass

        for renderer in (JavaGenerator(), SpringBootGenerator()):
            with pytest.raises(ValueError, match="no Java rendering for expression Unknown"):
                renderer._expr_to_string(Unknown())

    @staticmethod
    def _service(name, *statements):
        from engine.transformation.java_ir import JavaBasicType, JavaType
        from engine.transformation.spring_boot_ir import SpringBootService, SpringBootServiceMethod

        method = SpringBootServiceMethod(
            name="run", return_type=JavaType(basic_type=JavaBasicType.VOID),
            body_statements=statements)
        return SpringBootService(name=name, methods=(method,))

    @staticmethod
    def _call(target):
        from engine.transformation.java_ir import JavaMethodCall, JavaMethodCallStatement

        return JavaMethodCallStatement(call=JavaMethodCall(class_name=target, is_static=True))

    @staticmethod
    def _symbols(services) -> str:
        return repr([m.body_statements for s in services for m in s.methods])

    def test_a_recursive_call_is_an_unsupported_symbol_not_a_comment(self):
        from engine.transformation.java_to_spring_mapping import _rewrite_service_calls

        out = _rewrite_service_calls([self._service("Payroll", self._call("Payroll"))])
        assert "UNSUPPORTED_CALL$RECURSIVE" in self._symbols(out)
        assert "JavaComment" not in self._symbols(out)

    def test_a_call_inside_perform_with_test_after_is_rewritten(self):
        from engine.transformation.java_ir import JavaDoWhile, JavaLiteral
        from engine.transformation.java_to_spring_mapping import _rewrite_service_calls

        loop = JavaDoWhile(condition=JavaLiteral(value="false"), body=(self._call("Owner"),))
        out = _rewrite_service_calls([self._service("Owner", loop)])
        # Before: the do-while body was never visited and the raw static
        # self-call survived; now it is rewritten (here: fail-closed).
        assert "UNSUPPORTED_CALL$RECURSIVE" in self._symbols(out)

    def test_an_unknown_selected_service_does_not_run_every_service(self):
        from engine.transformation import spring_boot_generator as sbg

        source = Path(sbg.__file__).read_text(encoding="utf-8")
        assert "if selected and selected not in known:" in source

    def test_an_unknown_statement_type_has_no_silent_mapping(self):
        from engine.transformation.cobol_to_java_mapping import map_cobol_statement

        class Unknown:
            pass

        with pytest.raises(NotImplementedError, match="Unknown has no Java mapping"):
            map_cobol_statement(Unknown())


# ---------------------------------------------------------------------------
# A8: the plan takes every non-SUPPORTED CALL; a non-transformable copybook
# blocks generation; J-3 guard pinned
# ---------------------------------------------------------------------------

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


class TestA8PlanBlocksWhatAnalysisRefuses:
    @staticmethod
    def _analysed(app_name: str):
        from engine.modernization.capability_analyzer import CapabilityAnalyzer
        from engine.transformation.application_discovery import ApplicationDiscovery

        app = ApplicationDiscovery().discover(str(_FIXTURES / app_name / "cobol"),
                                              application_id=app_name)
        return app, CapabilityAnalyzer(docker_available=True).analyze(app)

    def test_a_non_supported_call_verdict_becomes_a_skipped_plan_entry(self):
        import dataclasses

        from engine.modernization.capability_analyzer import (
            CapabilityLevel, ComponentCapability)
        from engine.modernization.transformation_plan import TransformationPlanGenerator

        app, report = self._analysed("workload-call-chain")
        refused = ComponentCapability(component_id="MAIN->CALLEE-X", component_type="CALL",
                                      level=CapabilityLevel.UNSUPPORTED,
                                      reason="ARITY_MISMATCH: 2 arguments, 3 parameters")
        report = dataclasses.replace(report, components=report.components + (refused,))
        plan = TransformationPlanGenerator().generate(app, report, "")
        entries = [c for c in plan.components if c.component_id == "MAIN->CALLEE-X"]
        assert entries and entries[0].action.name == "SKIP"
        assert "ARITY_MISMATCH" in entries[0].reason

    def test_a_skipped_copybook_blocks_generation(self, tmp_path, monkeypatch):
        from engine.modernization import pipeline as pipeline_mod
        from engine.modernization.transformation_plan import (
            ComponentPlan, TransformationAction, TransformerType)

        real_generate = pipeline_mod.TransformationPlanGenerator.generate

        def with_skipped_copybook(self, *args, **kwargs):
            import dataclasses

            plan = real_generate(self, *args, **kwargs)
            return dataclasses.replace(plan, components=tuple(plan.components) + (ComponentPlan(
                component_id="BOOK", component_type="COPYBOOK",
                action=TransformationAction.SKIP, transformer=TransformerType.SKIP,
                reason="PARTIAL: ambiguous REPLACING"),))

        monkeypatch.setattr(pipeline_mod.TransformationPlanGenerator, "generate",
                            with_skipped_copybook)
        report = pipeline_mod.UniversalModernizationPipeline(pipeline_mod.ModernizationConfig(
            source_dir=str(_FIXTURES / "workload-minimal" / "cobol"),
            output_dir=str(tmp_path), application_id="a8", docker_available=True,
        )).execute()
        assert not report.generation_success or not report.generated_project_dir
        assert any("non-transformable copybooks: BOOK" in e for e in report.generation_errors)

    def test_j3_unmapped_statement_types_raise(self):
        from engine.transformation.cobol_to_java_mapping import map_cobol_statement
        from engine.transformation.ir import SqlStatement

        with pytest.raises(NotImplementedError, match="has no Java mapping"):
            map_cobol_statement(SqlStatement(statement_type="SELECT", raw_sql="SELECT 1"))


# ---------------------------------------------------------------------------
# B4: an infrastructure failure is UNAVAILABLE, never the program's FAILED
# ---------------------------------------------------------------------------

class TestB4InfrastructureIsNotProgramFailure:
    def test_unavailable_build_image_is_flagged_infrastructure(self):
        from engine.candidate.docker_spring_boot_adapter import (
            CandidateManifest, DockerSpringBootCandidateAdapter, DockerSpringBootConfig)
        from engine.domain.identities import AdapterStatus

        adapter = object.__new__(DockerSpringBootCandidateAdapter)
        adapter._status = AdapterStatus.UNAVAILABLE
        adapter._config = DockerSpringBootConfig()
        result = adapter.compile(".", CandidateManifest(
            candidate_id="b4", workload_id="b4", source_hash="x",
            generated_files={"pom.xml": "x"}, entrypoint="Main"))
        assert result.success is False and result.infrastructure_error is True

    @pytest.mark.docker
    def test_a_build_that_could_not_run_derives_unavailable(self, tmp_path):
        from engine.candidate.adapter import CompilationResult
        from engine.candidate.maven_adapter import MavenProjectCandidateAdapter
        from engine.pipeline import PipelineConfig, VerticalSlicePipeline

        class NoBuildImage(MavenProjectCandidateAdapter):
            def compile(self, candidate_path, manifest):
                return CompilationResult(success=False, class_files={},
                                         compilation_errors=("Docker or Maven image not available",),
                                         infrastructure_error=True)

        project = tmp_path / "java"
        project.mkdir()
        (project / "pom.xml").write_text("<project/>", encoding="utf-8")
        result = VerticalSlicePipeline(PipelineConfig(
            workload_id="wl-b4", cobol_source_path=str(_FIXTURES / "workload-minimal" / "cobol"),
            java_candidate_path=str(project), java_entrypoint="Main", use_docker_java=True,
        ), candidate_adapter=NoBuildImage()).run()
        # Was FAILED: the build that never ran was recorded as the program's
        # nonzero exit and compared against the oracle. Now the candidate
        # execution is an infrastructure ``error``, which the derivation
        # reports as ERROR (its error check precedes the UNAVAILABLE check;
        # derivation.py is left untouched) - never the program's FAILED.
        assert result.verdict.state.value in ("ERROR", "UNAVAILABLE"), result.verdict.state
        assert result.verdict.state.value != "FAILED"
        candidate = [e for e in result.evidence_manifest.execution_evidence
                     if e.runtime_id.startswith("candidate")]
        assert candidate and all(e.termination_status == "error" for e in candidate)


# ---------------------------------------------------------------------------
# C1: one Java source renderer (no per-generator copies to drift apart)
# ---------------------------------------------------------------------------

def test_generators_share_one_renderer():
    from engine.transformation.java_generator import JavaGenerator
    from engine.transformation.java_render import JavaSourceRenderer
    from engine.transformation.spring_boot_generator import SpringBootGenerator

    for generator in (JavaGenerator, SpringBootGenerator):
        assert issubclass(generator, JavaSourceRenderer)
        for method in ("_stmt_to_string", "_expr_to_string", "_method_call_to_string",
                       "_escape_java_string"):
            assert method not in vars(generator), (generator.__name__, method)
