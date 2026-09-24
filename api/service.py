"""Service adapter boundary between the API and the validation engine.

Owns orchestration state transitions.  Does NOT duplicate transformation
or validation logic — it delegates to:
  - engine.transformation.application_discovery.ApplicationDiscovery
  - engine.transformation.application_generator.ApplicationGenerator
  - engine.pipeline.VerticalSlicePipeline
  - engine.verdict.derivation.derive_verdict
  - engine.evidence.integrity.EvidenceIntegrityValidator

P0 MVP canonical path:
  COBOL ZIP/upload -> secure ingestion -> discovery -> per-program
  transformation -> JavaApplication -> Spring Boot mapping ->
  SpringBootGenerator -> generated Spring Boot project ->
  Docker (Maven/JAR) validation of the GENERATED artifact.

Transformation invariant: each discovered program is transformed within its
own per-program boundary and COBOL files are never concatenated. The
GENERATED application artifact (not any uploaded candidate) is the candidate
used by validation.

Production validation constraint: candidates are always executed inside
Docker (use_docker_java=True). Host javac/java is never used for validation.
Java candidate upload remains internal/test-only and out of the UI workflow.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
import threading
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from api.models import RunStage
from api.store import ApplicationRecord, RunRecord, Store
from engine.pipeline import PipelineConfig, VerticalSlicePipeline

logger = logging.getLogger(__name__)

# Legacy source tree root markers — first match wins.
SOURCE_ROOT_MARKERS = {"main.cob", "main.cbl", "main.COB", "main.CBL"}


class ServiceError(Exception):
    """Raised when a service operation fails."""


class Service:
    """Thin orchestration layer over the engine."""

    def __init__(self, store: Store) -> None:
        self._store = store

    # -- applications -------------------------------------------------------

    def create_application(
        self,
        name: str,
        description: str,
        workload_id: str,
        java_entrypoint: str,
    ) -> ApplicationRecord:
        app_id = f"app-{uuid.uuid4().hex[:12]}"
        record = ApplicationRecord(
            id=app_id,
            name=self._store.unique_name(name),
            description=description,
            workload_id=workload_id,
            java_entrypoint=java_entrypoint,
        )
        return self._store.add_application(record)

    def get_application(self, app_id: str) -> ApplicationRecord:
        rec = self._store.get_application(app_id)
        if rec is None:
            raise ServiceError(f"Application {app_id!r} not found")
        return rec

    def ingest_application(self, app_id: str, data: bytes, zip_filename: str = "") -> dict:
        """Ingest a ZIP archive into an application workspace and run discovery.

        Replaces the two-step COBOL upload + Java candidate upload workflow.
        Extracts the ZIP, detects the source tree root, runs application
        discovery, and returns structured results.

        Detects the application name from the ZIP and updates the record
        if the current name is the generic placeholder.
        """
        from api.ingestion import ingest_zip, discover_application, IngestionError
        from api.name_derivation import derive_application_name_from_zip_bytes

        app = self.get_application(app_id)

        # 0. Derive name from ZIP contents (peek without full extraction)
        detected_name, top_entries = derive_application_name_from_zip_bytes(
            data, zip_filename
        )

        # 1. Extract ZIP to workspace
        workspace = ingest_zip(data, app_id)

        # 2. Detect source root (top-level dir if ZIP contains a single root dir)
        source_root = self._detect_source_root(workspace)

        # 3. Run application discovery
        discovery = discover_application(source_root, app_id)

        # 4. Persist paths on the application record
        app.cobol_source_path = str(source_root)

        # 5. Update application name if it was auto-generated placeholder
        #    or if the detected name is more specific (single dir override)
        if detected_name and detected_name != "application":
            # If the user didn't provide a meaningful name (empty or generic),
            # use the detected name. Always deduplicate.
            current_is_generic = not app.name or app.name == "application"
            if current_is_generic:
                app.name = self._store.unique_name(detected_name)
            else:
                # User provided a name — preserve it, but deduplicate if needed
                existing = self._store.find_application_by_name(app.name)
                if existing is not None and existing.id != app_id:
                    app.name = self._store.unique_name(app.name)

        self._store.update_application(app)

        result = discovery.to_dict()
        result["detected_name"] = detected_name
        result["top_level_entries"] = top_entries
        return result

    def _detect_source_root(self, workspace: Path) -> Path:
        """Return the actual source root inside an extracted workspace.

        If the ZIP contains a single top-level directory, descend into it.
        If well-known markers exist at the top level, use the workspace directly.
        """
        children = list(workspace.iterdir())
        dirs = [c for c in children if c.is_dir()]
        files = [c for c in children if c.is_file()]

        # Single-directory ZIP — use that directory as root
        if len(dirs) == 1 and len(files) == 0:
            return dirs[0]

        # Check for source markers at top level
        if any(f.name in SOURCE_ROOT_MARKERS for f in files):
            return workspace

        # Check one level down
        for d in dirs:
            if any((d / m).exists() for m in SOURCE_ROOT_MARKERS):
                return d

        # Fallback: workspace itself
        return workspace

    def upload_cobol_source(self, app_id: str, files: dict[str, bytes]) -> tuple[ApplicationRecord, int]:
        """Write COBOL source files into a temp directory and update the record."""
        app = self.get_application(app_id)

        base = Path(tempfile.mkdtemp(prefix=f"cobol-{app_id}-"))
        for name, content in files.items():
            safe_name = Path(name).name
            if not safe_name:
                continue
            (base / safe_name).write_bytes(content)

        app.cobol_source_path = str(base)
        self._store.update_application(app)
        return app, len(files)

    def upload_java_candidate(self, app_id: str, files: dict[str, bytes]) -> tuple[ApplicationRecord, int]:
        """Write Java candidate files into a temp directory and update the record.

        Internal/test-only: the normal modernization workflow never requires
        an uploaded candidate. Uploaded files are validated only when the
        modernize endpoint is explicitly called with use_uploaded_candidate.
        """
        app = self.get_application(app_id)

        base = Path(tempfile.mkdtemp(prefix=f"java-{app_id}-"))
        for name, content in files.items():
            safe_name = Path(name).name
            if not safe_name:
                continue
            (base / safe_name).write_bytes(content)

        app.java_candidate_path = str(base)
        self._store.update_application(app)
        return app, len(files)

    # -- modernize (transform + validate) -----------------------------------

    def modernize(
        self, app_id: str, *, use_uploaded_candidate: bool = False
    ) -> RunRecord:
        """Trigger the full modernization pipeline asynchronously.

        Returns immediately with a CREATED run record.  A background thread
        advances through real stages: DISCOVERING → DISCOVERY_COMPLETED →
        TRANSFORMING → GENERATING → EXECUTING_ORACLE → BUILDING →
        EXECUTING_GENERATED → COMPARING → VALIDATING_EVIDENCE → COMPLETED
        (or FAILED).  The frontend polls GET /runs/{id} to observe progress.
        Each stage is recorded as its underlying operation starts; no
        stage is emitted without the operation actually running.
        """
        app = self.get_application(app_id)

        if app.cobol_source_path is None:
            raise ServiceError("No COBOL source uploaded for this application")

        run_id = f"run-{uuid.uuid4().hex[:12]}"
        run = RunRecord(
            id=run_id,
            application_id=app_id,
            workload_id=app.workload_id,
            stage=RunStage.CREATED,
        )
        self._store.add_run(run)

        # Return a snapshot so the caller sees CREATED regardless of how
        # quickly the background thread advances the live record.
        snapshot = replace(run)

        # Launch background worker — daemon thread dies with the process.
        thread = threading.Thread(
            target=self._modernize_background,
            args=(app_id, run_id, use_uploaded_candidate),
            daemon=True,
            name=f"modernize-{run_id}",
        )
        thread.start()

        return snapshot

    def _modernize_background(
        self,
        app_id: str,
        run_id: str,
        use_uploaded_candidate: bool,
    ) -> None:
        """Background worker: run the full pipeline with real stage transitions.

        Called in a daemon thread.  All exceptions are caught and persisted
        as run failures.  Stages are updated before each expensive operation
        so the frontend can observe real progress via polling.
        """
        run = self._store.get_run(run_id)
        if run is None:
            logger.error("Background modernize: run %s not found", run_id)
            return

        app = self._store.get_application(app_id)
        if app is None:
            run.stage = RunStage.FAILED
            run.error = f"Application {app_id!r} not found"
            run.completed_at = datetime.now(timezone.utc).isoformat()
            self._store.update_run(run)
            return

        try:
            if use_uploaded_candidate:
                if app.java_candidate_path is None:
                    raise ServiceError(
                        "No uploaded Java candidate available "
                        "(internal/test-only path)"
                    )
                java_dir = Path(app.java_candidate_path)
                entrypoint = self._resolve_uploaded_entrypoint(app, java_dir)
            else:
                java_dir, entrypoint = self._generate_application(app, run)

            adapter = None
            if not use_uploaded_candidate:
                from engine.candidate.docker_spring_boot_adapter import (
                    DockerSpringBootCandidateAdapter,
                )

                adapter = DockerSpringBootCandidateAdapter()
            self._run_validation(app, run, java_dir, entrypoint, adapter)

            # Terminal state is set here; VALIDATING_EVIDENCE itself is
            # emitted by the pipeline progress hook at the true point.
            run.stage = RunStage.COMPLETED
            run.completed_at = datetime.now(timezone.utc).isoformat()
        except Exception as exc:
            logger.exception("Background modernize %s failed", run_id)
            run.stage = RunStage.FAILED
            run.error = str(exc)
            run.completed_at = datetime.now(timezone.utc).isoformat()

        self._store.update_run(run)

    # -- validate (re-run) --------------------------------------------------

    def revalidate(self, run_id: str) -> RunRecord:
        """Re-run validation on an existing run's artifacts.

        Explicit behavior: consistent with :meth:`modernize`, revalidation
        is asynchronous. The run is reset to ``CREATED`` (clearing the
        previous terminal state) and a background daemon thread — the same
        minimal mechanism used by modernization — re-executes validation of
        the GENERATED artifact (``generated_app_path``, falling back to the
        legacy ``java_candidate_path``). Callers poll ``GET /runs/{id}``
        until a terminal stage; the returned snapshot always shows the
        stage at call time.
        """
        run = self._store.get_run(run_id)
        if run is None:
            raise ServiceError(f"Run {run_id!r} not found")

        app = self._store.get_application(run.application_id)
        if app is None:
            raise ServiceError(f"Application {run.application_id!r} not found")

        candidate_path = app.generated_app_path or app.java_candidate_path
        if app.cobol_source_path is None or candidate_path is None:
            raise ServiceError("Run lacks source or candidate paths for re-validation")

        run.stage = RunStage.CREATED
        run.completed_at = None
        run.error = None
        self._store.update_run(run)

        snapshot = replace(run)

        thread = threading.Thread(
            target=self._revalidate_background,
            args=(run_id,),
            daemon=True,
            name=f"revalidate-{run_id}",
        )
        thread.start()

        return snapshot

    def _revalidate_background(self, run_id: str) -> None:
        """Background worker: re-execute validation for a reset run."""
        run = self._store.get_run(run_id)
        if run is None:
            logger.error("Background revalidate: run %s not found", run_id)
            return

        app = self._store.get_application(run.application_id)
        if app is None:
            run.stage = RunStage.FAILED
            run.error = f"Application {run.application_id!r} not found"
            run.completed_at = datetime.now(timezone.utc).isoformat()
            self._store.update_run(run)
            return

        try:
            candidate_path = app.generated_app_path or app.java_candidate_path
            if app.cobol_source_path is None or candidate_path is None:
                raise ServiceError(
                    "Run lacks source or candidate paths for re-validation"
                )
            entrypoint = (
                app.generated_entrypoint
                or app.java_entrypoint
            )
            candidate_dir = Path(candidate_path)
            adapter = None
            if (candidate_dir / "pom.xml").exists():
                from engine.candidate.docker_spring_boot_adapter import (
                    DockerSpringBootCandidateAdapter,
                )

                adapter = DockerSpringBootCandidateAdapter()
            self._run_validation(
                app, run, candidate_dir, entrypoint, adapter
            )
            run.stage = RunStage.COMPLETED
            run.completed_at = datetime.now(timezone.utc).isoformat()
        except Exception as exc:
            logger.exception("Background revalidate %s failed", run_id)
            run.stage = RunStage.FAILED
            run.error = str(exc)
            run.completed_at = datetime.now(timezone.utc).isoformat()

        self._store.update_run(run)

    # -- internal -----------------------------------------------------------

    def _generate_application(
        self,
        app: ApplicationRecord,
        run: RunRecord,
    ) -> tuple[Path, str]:
        """Delegate to UniversalModernizationPipeline for phases 1-5.

        The pipeline is the SINGLE authoritative orchestrator for:
          Discovery → Capability Analysis → Transformation Plan →
          Transform → Spring Boot Assembly

        Returns (generated_project_dir, entrypoint). Raises ServiceError on
        controlled generation failure.
        """
        from engine.modernization.pipeline import (
            ModernizationConfig,
            UniversalModernizationPipeline,
        )

        if app.cobol_source_path is None:
            raise ServiceError("No COBOL source available for discovery")

        output_dir = str(Path(tempfile.mkdtemp(prefix=f"pipeline-output-{run.id}-")))

        pipeline_config = ModernizationConfig(
            source_dir=app.cobol_source_path,
            output_dir=output_dir,
            application_id=app.id,
            entrypoint=app.java_entrypoint or "",
            docker_available=True,
        )

        def _pipeline_progress(phase: str) -> None:
            stage_map = {
                "DISCOVERING": RunStage.DISCOVERING,
                "DISCOVERY_COMPLETED": RunStage.DISCOVERY_COMPLETED,
                "ANALYZING": RunStage.ANALYZING,
                "ANALYSIS_COMPLETED": RunStage.ANALYSIS_COMPLETED,
                "PLANNING": RunStage.PLANNING,
                "PLAN_COMPLETED": RunStage.PLAN_COMPLETED,
                "TRANSFORMING": RunStage.TRANSFORMING,
                "ASSEMBLING": RunStage.ASSEMBLING,
                "ASSEMBLY_COMPLETED": RunStage.ASSEMBLY_COMPLETED,
            }
            stage = stage_map.get(phase)
            if stage is not None:
                run.stage = stage
                self._store.update_run(run)

        pipeline = UniversalModernizationPipeline(pipeline_config)
        report = pipeline.execute(progress=_pipeline_progress)

        if not report.generation_success:
            details = list(report.generation_errors)
            if report.verification_readiness == "BLOCKED":
                details.extend(report.readiness_reasons)
            if not details:
                details.extend(report.limitations)
            detail_text = "; ".join(details) or "unknown"
            raise ServiceError(f"Pipeline generation failed: {detail_text}")

        if not report.generated_project_dir:
            limit_detail = "; ".join(report.limitations) if report.limitations else "unknown"
            raise ServiceError(
                f"Pipeline produced no generated project directory: {limit_detail}"
            )

        # Persist the report on the run record
        run_report = run.modernization_report or {}
        run_report["pipeline_report"] = report.to_dict()
        run_report["limitations"] = list(report.limitations)
        run_report["recommendations"] = list(report.recommendations)
        run.modernization_report = run_report

        # Update application provenance
        app.discovered_program_ids = report.discovered_programs
        app.generated_app_path = report.generated_project_dir
        app.generated_entrypoint = report.generated_entrypoint
        app.generated_program_ids = report.generated_program_ids
        app.java_candidate_path = report.generated_project_dir
        self._store.update_application(app)

        return Path(report.generated_project_dir), report.generated_entrypoint

    @staticmethod
    def _resolve_uploaded_entrypoint(
        app: ApplicationRecord,
        java_dir: Path,
    ) -> str:
        """Entrypoint resolution for the internal/test-only uploaded path."""
        entrypoint = app.java_entrypoint
        if entrypoint == "Main":
            for jf in sorted(java_dir.rglob("*.java")):
                content = jf.read_text(encoding="utf-8", errors="replace")
                if "public static void main" in content:
                    entrypoint = jf.stem
                    break
        return entrypoint

    def _run_validation(
        self,
        app: ApplicationRecord,
        run: RunRecord,
        java_dir: Path,
        entrypoint: str,
        candidate_adapter=None,
    ) -> None:
        """Run the validation pipeline and persist evidence + verdict.

        Canonical selection: DockerSpringBootCandidateAdapter for the
        generated Spring Boot project (injected by the caller). The
        internal/test-only uploaded path uses DockerJavaCandidateAdapter
        via use_docker_java=True. RealJavaCandidateAdapter (host
        javac/java) is never selected here. If Docker is unavailable the
        pipeline returns UNAVAILABLE semantics instead of executing on
        the host.

        Comparison/evidence/verdict stay inside the pipeline trust boundary;
        this method only orchestrates and persists the pipeline result.
        """
        from engine.workload import WorkloadDefinition, WorkloadArtifact

        workload_def = WorkloadDefinition(
            workload_id=app.workload_id,
            description=f"API-driven workload for {app.name}",
            artifacts=(
                WorkloadArtifact(
                    logical_name="stdout",
                    artifact_type="STDOUT",
                    comparator_id="stdout-exact",
                ),
                WorkloadArtifact(
                    logical_name="exit-status",
                    artifact_type="EXIT_STATUS",
                    comparator_id="exit-status-exact",
                ),
            ),
        )

        config = PipelineConfig(
            workload_id=app.workload_id,
            cobol_source_path=app.cobol_source_path,
            java_candidate_path=str(java_dir),
            java_entrypoint=entrypoint,
            workload=workload_def,
            use_docker_java=True,
        )

        phase_to_stage = {
            "EXECUTING_ORACLE": RunStage.EXECUTING_ORACLE,
            "BUILDING": RunStage.BUILDING,
            "EXECUTING_GENERATED": RunStage.EXECUTING_GENERATED,
            "COMPARING": RunStage.COMPARING,
            "VALIDATING_EVIDENCE": RunStage.VALIDATING_EVIDENCE,
        }

        def _record_progress(phase: str) -> None:
            stage = phase_to_stage.get(phase)
            if stage is not None:
                run.stage = stage
                self._store.update_run(run)

        pipeline = VerticalSlicePipeline(
            config, candidate_adapter=candidate_adapter
        )
        result = pipeline.run(progress=_record_progress)

        run.evidence_manifest = result.evidence_manifest
        run.verdict = result.verdict
        self._store.update_run(run)

    # -- queries ------------------------------------------------------------

    def get_run(self, run_id: str) -> RunRecord:
        rec = self._store.get_run(run_id)
        if rec is None:
            raise ServiceError(f"Run {run_id!r} not found")
        return rec

    def get_artifacts(self, run_id: str) -> list[dict]:
        """Return artifact metadata from the evidence manifest."""
        run = self.get_run(run_id)
        if run.evidence_manifest is None:
            return []
        return [
            {
                "artifact_id": ae.artifact.artifact_id,
                "artifact_type": ae.artifact.artifact_type,
                "logical_name": ae.artifact.logical_name,
                "producer_role": ae.artifact.producer_role,
                "content_hash": str(ae.content_hash),
                "size_bytes": ae.size_bytes,
                "record_count": ae.record_count,
            }
            for ae in run.evidence_manifest.artifact_evidence
        ]

    def get_verdict(self, run_id: str) -> dict:
        """Return verdict details as a dict.

        The ``run_id`` key is the API run-record ID so verdicts correlate
        with ``GET /runs/{id}`` polling. The engine pipeline mints its own
        internal run ID; it is preserved as ``engine_run_id`` and never
        alters verdict semantics.
        """
        run = self.get_run(run_id)
        if run.verdict is None:
            raise ServiceError("No verdict available for this run")
        data = dict(run.verdict.to_dict())
        engine_run_id = data.get("run_id")
        data["run_id"] = run.id
        if engine_run_id is not None and engine_run_id != run.id:
            data["engine_run_id"] = engine_run_id
        else:
            data.setdefault("engine_run_id", None)
        return data

    def get_comparisons(self, run_id: str) -> list[dict]:
        """Return comparison details from the evidence manifest."""
        run = self.get_run(run_id)
        if run.evidence_manifest is None:
            return []
        return [
            {
                "comparison_id": c.comparison_id,
                "comparator_id": c.comparator_id,
                "comparator_version": getattr(c, "comparator_version", ""),
                "artifact_type": c.artifact_type,
                "result": c.result,
                "differences": list(c.differences),
            }
            for c in run.evidence_manifest.comparison_evidence
        ]

    def list_applications(self) -> list[ApplicationRecord]:
        """Return all applications ordered by creation time."""
        return self._store.list_applications()

    def list_runs(self, app_id: str) -> list[RunRecord]:
        """Return all runs for an application ordered by creation time."""
        self.get_application(app_id)  # raise ServiceError for unknown apps
        return self._store.list_runs_for_application(app_id)

    def get_run_report(self, run_id: str) -> dict:
        """Return the full modernization report for a run.

        Contains capability report, transformation plan, limitations,
        and recommendations. Only returned when the universal pipeline
        produced a report — never fabricated.
        """
        run = self.get_run(run_id)
        if run.modernization_report is None:
            raise ServiceError(
                "No modernization report available for this run"
            )
        return run.modernization_report

    def get_run_detail(self, run_id: str) -> dict:
        """Return a coherent run-detail payload.

        Combines run state, application identity, current stage, a
        best-effort discovery summary, generated file listing, error, and
        verdict status. No verdict semantics are duplicated here — the
        verdict state string is read from the stored verdict only.
        """
        run = self.get_run(run_id)
        app = self.get_application(run.application_id)

        discovery: dict | None = None
        if app.cobol_source_path is not None:
            try:
                from api.ingestion import discover_application

                discovery = discover_application(
                    Path(app.cobol_source_path), app.id
                ).to_dict()
            except Exception:
                discovery = None

        generated_files: list[str] = []
        if app.generated_app_path is not None:
            try:
                root = Path(app.generated_app_path)
                if root.exists():
                    generated_files = sorted(
                        str(f.relative_to(root)).replace("\\", "/")
                        for f in root.rglob("*")
                        if f.is_file()
                    )
            except Exception:
                generated_files = []

        verdict_state: str | None = None
        if run.verdict is not None:
            try:
                verdict_state = str(run.verdict.to_dict().get("state"))
            except Exception:
                verdict_state = None

        stage_messages = [run.stage.value]
        if run.error:
            stage_messages.append(run.error)

        return {
            "id": run.id,
            "application_id": run.application_id,
            "application_name": app.name,
            "workload_id": run.workload_id,
            "stage": run.stage,
            "created_at": run.created_at,
            "completed_at": run.completed_at,
            "error": run.error,
            "verdict_state": verdict_state,
            "discovery": discovery,
            "stage_messages": stage_messages,
            "generated_files": generated_files,
        }
