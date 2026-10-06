"""Declaration-driven validation pipeline.

Orchestrates:
- Real GnuCOBOL oracle execution via Docker
- Real Java candidate execution via Docker (production)
- Real artifact capture (declaration-driven)
- Real typed comparator execution (registry-driven)
- Real evidence manifest generation
- Real verdict derivation

This pipeline is workload-agnostic. Artifact processing is driven entirely
by the WorkloadDefinition. Adding a new workload means creating a
WorkloadDefinition, NOT editing pipeline.py.

Production adapter selection:
- DockerJavaCandidateAdapter is the ONLY production V1 Java execution adapter
- RealJavaCandidateAdapter is dev/reference only, never selected implicitly
- Docker unavailable -> AdapterStatus.UNAVAILABLE, no host fallback
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from engine.candidate.adapter import (
    CandidateAdapter,
    CandidateExecutionResult,
    CandidateManifest,
)
from engine.candidate.docker_java_adapter import (
    DockerJavaCandidateAdapter,
    DockerJavaConfig,
)
from engine.candidate.java_adapter import RealJavaCandidateAdapter
from engine.comparators.framework import (
    ComparatorRegistry,
    create_default_registry,
    resolve_comparator_id,
)
from engine.domain.identities import (
    AdapterStatus,
    CandidateIdentity,
    ContentHash,
    EnvironmentIdentity,
    ExecutionId,
    InputIdentity,
    OracleIdentity,
    RunId,
    SourceIdentity,
    WorkloadId,
)
from engine.evidence.integrity import EvidenceIntegrityValidator
from engine.evidence.models import (
    ArtifactEvidence,
    ComparisonEvidence,
    EvidenceManifest,
    ExecutionEvidence,
)
from engine.execution.artifacts import ArtifactCapturer, CapturedArtifact
from engine.oracle.adapter import OracleAdapterConfig
from engine.oracle.docker_adapter import DockerOracleAdapter
from engine.verdict.derivation import (
    Verdict,
    derive_verdict_validated,
    derive_verdict_untrusted,
)
from engine.workload import WorkloadDefinition


@dataclass(frozen=True)
class PipelineConfig:
    """Configuration for the declaration-driven pipeline."""
    workload_id: str
    cobol_source_path: str
    java_candidate_path: str
    java_entrypoint: str
    workload: WorkloadDefinition | None = None
    oracle_image: str = os.environ.get(
        "SYSTEMAOPS_ORACLE_IMAGE", "gnucobol-ocesql:latest"
    )
    # Declared immutable pin. Empty means auto-pin: the oracle adapter
    # resolves the image's immutable identity at execution time and records
    # it as the executed identity (fail closed on mismatch when set).
    oracle_digest: str = os.environ.get("SYSTEMAOPS_ORACLE_DIGEST", "")
    oracle_compiler_version: str = "3.1.2.0"
    javac_path: str = "javac"
    java_path: str = "java"
    timeout_seconds: int = 30
    use_docker_java: bool = True


@dataclass
class PipelineResult:
    """Result of the declaration-driven pipeline."""
    run_id: RunId
    workload_id: WorkloadId
    source_identity: SourceIdentity
    oracle_identity: OracleIdentity
    candidate_identity: CandidateIdentity
    oracle_evidence: ExecutionEvidence
    candidate_evidence: ExecutionEvidence
    artifact_evidence: tuple[ArtifactEvidence, ...]
    comparison_evidence: tuple[ComparisonEvidence, ...]
    evidence_manifest: EvidenceManifest
    verdict: Verdict
    oracle_stdout: bytes
    candidate_stdout: bytes
    oracle_stderr: bytes
    candidate_stderr: bytes
    oracle_exit_code: int | None
    candidate_exit_code: int | None


class VerticalSlicePipeline:
    """Declaration-driven validation pipeline.

    Artifact processing is driven entirely by WorkloadDefinition.
    Comparator dispatch is driven by ComparatorRegistry.
    No hardcoded artifact names or comparator instantiation in this class.
    """

    def __init__(
        self,
        config: PipelineConfig,
        candidate_adapter: CandidateAdapter | None = None,
        registry: ComparatorRegistry | None = None,
    ) -> None:
        self._config = config
        self._capturer = ArtifactCapturer()
        self._registry = registry or create_default_registry()
        self._integrity_validator = EvidenceIntegrityValidator()

        oracle_config = OracleAdapterConfig(
            oracle_id="gnucobol-3.1.2",
            image_digest=config.oracle_digest,
            compiler_version=config.oracle_compiler_version,
            timeout_seconds=config.timeout_seconds,
            image=config.oracle_image,
        )
        self._oracle_adapter = DockerOracleAdapter(oracle_config)

        if candidate_adapter is not None:
            self._candidate_adapter = candidate_adapter
        elif config.use_docker_java:
            docker_config = DockerJavaConfig(
                timeout_seconds=config.timeout_seconds,
            )
            self._candidate_adapter = DockerJavaCandidateAdapter(docker_config)
        else:
            self._candidate_adapter = RealJavaCandidateAdapter(
                javac_path=config.javac_path,
                java_path=config.java_path,
            )

    def _compute_source_identity(self) -> SourceIdentity:
        source_path = Path(self._config.cobol_source_path)
        hasher = hashlib.sha256()
        if source_path.is_file():
            hasher.update(source_path.read_bytes())
        elif source_path.is_dir():
            for f in sorted(source_path.rglob("*")):
                if f.is_file():
                    hasher.update(str(f.relative_to(source_path)).encode())
                    hasher.update(f.read_bytes())

        file_count = 0
        total_size = 0
        if source_path.is_file():
            file_count = 1
            total_size = source_path.stat().st_size
        elif source_path.is_dir():
            for f in source_path.rglob("*"):
                if f.is_file():
                    file_count += 1
                    total_size += f.stat().st_size

        return SourceIdentity(
            source_id=f"cobol-{self._config.workload_id}",
            source_hash=ContentHash(digest=hasher.hexdigest()),
            file_count=file_count,
            total_size_bytes=total_size,
        )

    def _compute_candidate_identity(self, source_hash: ContentHash) -> CandidateIdentity:
        candidate_path = Path(self._config.java_candidate_path)
        hasher = hashlib.sha256()
        file_count = 0
        total_size = 0
        if candidate_path.is_file():
            hasher.update(candidate_path.read_bytes())
            file_count = 1
            total_size = candidate_path.stat().st_size
        elif candidate_path.is_dir():
            for f in sorted(candidate_path.rglob("*")):
                if f.is_file():
                    hasher.update(str(f.relative_to(candidate_path)).encode())
                    hasher.update(f.read_bytes())
                    file_count += 1
                    total_size += f.stat().st_size

        return CandidateIdentity(
            candidate_id=f"java-{self._config.workload_id}",
            candidate_hash=ContentHash(digest=hasher.hexdigest()),
            source_hash=source_hash,
            file_count=file_count,
            total_size_bytes=total_size,
        )

    def _build_candidate_manifest(self, source_hash: ContentHash) -> CandidateManifest:
        candidate_path = Path(self._config.java_candidate_path)
        generated_files = {}
        if candidate_path.is_dir():
            for f in candidate_path.rglob("*.java"):
                rel = f.relative_to(candidate_path)
                file_hash = ContentHash.from_bytes(f.read_bytes())
                generated_files[str(rel)] = str(file_hash)
        elif candidate_path.is_file():
            file_hash = ContentHash.from_bytes(candidate_path.read_bytes())
            generated_files[candidate_path.name] = str(file_hash)

        return CandidateManifest(
            candidate_id=f"java-{self._config.workload_id}",
            workload_id=self._config.workload_id,
            source_hash=str(source_hash),
            generated_files=generated_files,
            entrypoint=self._config.java_entrypoint,
            java_version="21",
        )

    def _extract_artifact_content(
        self,
        artifact_type: str,
        output_path: str | None,
        execution_result: object,
    ) -> bytes | None:
        """Extract artifact content; missing declared files return None."""
        if artifact_type == "STDOUT":
            return execution_result.stdout
        if artifact_type == "STDERR":
            return execution_result.stderr
        if artifact_type == "EXIT_STATUS":
            _ec = execution_result.exit_code
            return str(_ec if _ec is not None else -1).encode()
        if artifact_type in ("TEXT_FILE", "FIXED_RECORD"):
            generated = getattr(execution_result, "generated_files", None) or {}
            if output_path and output_path in generated:
                return generated[output_path]
            return None
        return None

    def _capture_artifact(
        self,
        artifact_type: str,
        output_path: str | None,
        execution_id: ExecutionId,
        content: bytes | None,
        logical_name: str,
        producer_role: str,
        record_length: int | None = None,
    ) -> CapturedArtifact:
        """Capture an artifact; None content means the artifact is absent."""
        if content is None:
            return self._capturer.capture_missing(
                execution_id, artifact_type, logical_name, producer_role,
                record_length=record_length,
            )
        if artifact_type == "STDOUT":
            return self._capturer.capture_stdout(
                execution_id, content, logical_name, producer_role
            )
        if artifact_type == "STDERR":
            return self._capturer.capture_stderr(
                execution_id, content, logical_name, producer_role
            )
        if artifact_type == "EXIT_STATUS":
            return self._capturer.capture_exit_status(
                execution_id, int(content), producer_role
            )
        if artifact_type == "TEXT_FILE":
            return self._capturer.capture_text_file_from_bytes(
                execution_id, content, logical_name, producer_role
            )
        if artifact_type == "FIXED_RECORD":
            return self._capturer.capture_fixed_record(
                execution_id, content, logical_name, producer_role,
                record_length=record_length,
            )
        raise ValueError(f"Unsupported artifact_type: {artifact_type}")

    def _make_comparison_evidence(
        self,
        run_id: RunId,
        artifact_def: object,
        oracle_ca: CapturedArtifact,
        candidate_ca: CapturedArtifact,
        comp_result: object,
    ) -> ComparisonEvidence:
        """Build ComparisonEvidence from a ComparatorResult."""
        return ComparisonEvidence(
            comparison_id=f"comp-{artifact_def.logical_name}-{run_id.value}",
            run_id=run_id,
            comparator_id=comp_result.comparator_id.comparator_id,
            comparator_version=comp_result.comparator_id.version,
            oracle_artifact_id=oracle_ca.artifact.artifact_id,
            candidate_artifact_id=candidate_ca.artifact.artifact_id,
            artifact_type=artifact_def.artifact_type,
            result=comp_result.result.value,
            normalization_applied=comp_result.normalization_applied,
            differences=tuple(d.description for d in comp_result.differences),
            field_level_results=(),
            ordering_applied=getattr(comp_result, "ordering_applied", "SEQUENTIAL"),
            failure_policy=getattr(comp_result, "failure_policy", ""),
            content_hash=ContentHash.from_string(json.dumps({
                "result": comp_result.result.value,
                "differences": [
                    {"location": d.location, "expected": d.expected, "actual": d.actual}
                    for d in comp_result.differences
                ],
            }, sort_keys=True)),
        )

    def _run_declaration_driven(
        self,
        run_id: RunId,
        workload_id: WorkloadId,
        oracle_result: object,
        candidate_result: object,
        source_identity: SourceIdentity,
        candidate_identity: CandidateIdentity,
    ) -> tuple[
        tuple[ArtifactEvidence, ...],
        tuple[ComparisonEvidence, ...],
        list[CapturedArtifact],
        list[CapturedArtifact],
    ]:
        """Execute declaration-driven artifact capture and comparison."""
        workload = self._config.workload
        assert workload is not None

        oracle_artifacts_list: list[CapturedArtifact] = []
        candidate_artifacts_list: list[CapturedArtifact] = []
        comparison_evidence: list[ComparisonEvidence] = []

        for artifact_def in workload.artifacts:
            # Extract content
            oracle_content = self._extract_artifact_content(
                artifact_def.artifact_type, artifact_def.output_path, oracle_result
            )
            candidate_content = self._extract_artifact_content(
                artifact_def.artifact_type, artifact_def.output_path, candidate_result
            )

            # Capture artifacts
            oracle_ca = self._capture_artifact(
                artifact_def.artifact_type, artifact_def.output_path,
                oracle_result.execution_id, oracle_content,
                artifact_def.logical_name, "ORACLE",
                record_length=artifact_def.record_length,
            )
            candidate_ca = self._capture_artifact(
                artifact_def.artifact_type, artifact_def.output_path,
                candidate_result.execution_id, candidate_content,
                artifact_def.logical_name, "CANDIDATE",
                record_length=artifact_def.record_length,
            )

            oracle_artifacts_list.append(oracle_ca)
            candidate_artifacts_list.append(candidate_ca)

            # Get comparator from registry (literal get call — tests assert
            # dispatch is registry-driven, never direct instantiation).
            comparator = self._registry.get(artifact_def.artifact_type)
            if comparator is None:
                raise ValueError(
                    f"No comparator registered for artifact_type={artifact_def.artifact_type!r}"
                )

            # Comparator binding: the comparator the declaration names (after
            # alias resolution) must be exactly the comparator the registry
            # dispatches for this artifact type. A disagreement means the
            # evidence would be produced by an unbound comparator — fail closed.
            declared_id = (getattr(artifact_def, "comparator_id", "") or "").strip()
            if declared_id:
                resolved_declared = resolve_comparator_id(declared_id)
                registered_id = comparator.comparator_id.comparator_id
                if resolved_declared != registered_id:
                    raise ValueError(
                        "Comparator binding mismatch for artifact_type="
                        f"{artifact_def.artifact_type!r}: declaration "
                        f"{declared_id!r} resolves to {resolved_declared!r} "
                        f"but registry provides {registered_id!r}"
                    )

            # Compare
            normalization = (
                artifact_def.normalization.allowed_normalizations
                if artifact_def.normalization else ()
            )
            ordering = artifact_def.ordering.order if artifact_def.ordering else "SEQUENTIAL"
            comp_result = comparator.compare(
                oracle_ca.artifact, oracle_ca.content,
                candidate_ca.artifact, candidate_ca.content,
                normalization_policy=normalization,
                ordering=ordering,
                failure_policy=artifact_def.failure,
            )
            comparison_evidence.append(self._make_comparison_evidence(
                run_id, artifact_def, oracle_ca, candidate_ca, comp_result,
            ))

        artifact_evidence = tuple(
            a.to_evidence() for a in oracle_artifacts_list + candidate_artifacts_list
        )

        return artifact_evidence, tuple(comparison_evidence), oracle_artifacts_list, candidate_artifacts_list

    def _load_input_files(self) -> dict[str, bytes] | None:
        """Load input files from workload declaration.

        Returns dict keyed by file name (e.g. 'claims.dat'), which the
        oracle and candidate adapters write into a temp input directory
        mounted at /workspace/input/.

        A declared input that does not exist on disk fails closed: silently
        omitting it would validate a different workload than declared.
        Duplicate staging names are rejected when the WorkloadDefinition is
        constructed, so keys are unambiguous here.
        """
        workload = self._config.workload
        if not workload or not workload.inputs:
            return None
        fixture_root = Path(self._config.cobol_source_path).parent.parent
        files: dict[str, bytes] = {}
        for inp in workload.inputs:
            source = fixture_root / inp.source_path
            if not source.is_file():
                raise ValueError(
                    f"Declared input {inp.source_path!r} (logical_name="
                    f"{inp.logical_name!r}) not found at {source}: refusing "
                    f"to run with a different input set than declared"
                )
            files[source.name] = source.read_bytes()
        return files if files else None

    def _input_file_identities(self) -> dict[str, ContentHash]:
        """Hashes of declared input files, keyed by container path.

        Keyed by the declared ``container_path`` (not the staging name) so
        the recorded input identity matches the workload declaration.
        """
        workload = self._config.workload
        if not workload or not workload.inputs:
            return {}
        fixture_root = Path(self._config.cobol_source_path).parent.parent
        identities: dict[str, ContentHash] = {}
        for inp in workload.inputs:
            source = fixture_root / inp.source_path
            if not source.is_file():
                raise ValueError(
                    f"Declared input {inp.source_path!r} (logical_name="
                    f"{inp.logical_name!r}) not found at {source}: refusing "
                    f"to record an input identity for missing input"
                )
            identities[inp.container_path] = ContentHash.from_bytes(source.read_bytes())
        return identities

    #: Directories excluded from the candidate source-tree mutation hash
    #: (build outputs written during compile are not source).
    _SOURCE_TREE_EXCLUDED_DIRS = frozenset({
        "target", "build", "out", ".git", "__pycache__", "node_modules",
    })

    def _candidate_resource_limits(self) -> dict[str, str]:
        """Resource limits of the configured candidate adapter (best effort)."""
        cfg = getattr(self._candidate_adapter, "_config", None)
        return {
            "memory": str(getattr(cfg, "memory_limit", "512m")),
            "cpus": str(getattr(cfg, "cpu_limit", "1.0")),
            "pids_limit": str(getattr(cfg, "pids_limit", 256)),
        }

    def _candidate_source_tree_hash(self) -> ContentHash:
        """Hash the candidate's source tree at call time (build outputs excluded).

        Recorded before and after build/execute so evidence proves the
        candidate sources were not rewritten during validation.
        """
        candidate_path = Path(self._config.java_candidate_path)
        hasher = hashlib.sha256()
        if candidate_path.is_file():
            hasher.update(candidate_path.read_bytes())
        elif candidate_path.is_dir():
            for f in sorted(candidate_path.rglob("*")):
                if not f.is_file():
                    continue
                rel = f.relative_to(candidate_path)
                if any(part in self._SOURCE_TREE_EXCLUDED_DIRS for part in rel.parts):
                    continue
                hasher.update(str(rel).encode())
                hasher.update(f.read_bytes())
        return ContentHash(digest=hasher.hexdigest())

    def run(
        self,
        controlled_input: bytes | None = None,
        progress: Callable[[str], None] | None = None,
    ) -> PipelineResult:
        """Run the full validation pipeline.

        The optional progress callback receives phase names
        (EXECUTING_ORACLE, BUILDING, EXECUTING_GENERATED, COMPARING,
        VALIDATING_EVIDENCE) as each phase STARTS. It changes nothing
        about execution, comparison, evidence, or verdict semantics.
        """
        run_id = RunId(value=f"run-{self._config.workload_id}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}")
        workload_id = WorkloadId(value=self._config.workload_id)

        source_identity = self._compute_source_identity()

        input_files = self._load_input_files()
        input_file_hashes = self._input_file_identities()

        if progress is not None:
            progress("EXECUTING_ORACLE")
        oracle_result = self._oracle_adapter.execute(
            run_id=run_id,
            source_path=self._config.cobol_source_path,
            input_data=controlled_input,
            input_files=input_files,
        )
        oracle_evidence = oracle_result.to_execution_evidence()

        candidate_identity = self._compute_candidate_identity(source_identity.source_hash)
        candidate_source_before = self._candidate_source_tree_hash()

        if progress is not None:
            progress("BUILDING")
        compilation = self._candidate_adapter.compile(
            candidate_path=self._config.java_candidate_path,
            manifest=self._build_candidate_manifest(source_identity.source_hash),
        )

        if compilation.success:
            with tempfile.TemporaryDirectory() as tmpdir:
                for name, bytecode in compilation.class_files.items():
                    class_file = Path(tmpdir) / name
                    class_file.parent.mkdir(parents=True, exist_ok=True)
                    class_file.write_bytes(bytecode)

                if progress is not None:
                    progress("EXECUTING_GENERATED")
                candidate_result = self._candidate_adapter.execute(
                    run_id=run_id,
                    compiled_path=tmpdir,
                    manifest=self._build_candidate_manifest(source_identity.source_hash),
                    input_data=controlled_input,
                    input_files=input_files,
                )
        else:
            from datetime import timezone as tz
            candidate_result = CandidateExecutionResult(
                execution_id=ExecutionId(value=f"candidate-{run_id.value}-compile-fail"),
                run_id=run_id,
                status=AdapterStatus.FAILED,
                exit_code=1,
                stdout=b"",
                stderr="; ".join(compilation.compilation_errors).encode(),
                start_time=datetime.now(tz.utc).isoformat(),
                end_time=datetime.now(tz.utc).isoformat(),
                termination_status="nonzero_exit",
                timeout_applied=False,
            )

        candidate_source_after = self._candidate_source_tree_hash()
        candidate_evidence = candidate_result.to_execution_evidence()

        # Bind both executions to the declared workload. Candidate evidence
        # records the real source-tree hashes so a rewrite during build or
        # execution is provable, and a compile failure is marked BUILD (it
        # is not an execution of the candidate program).
        oracle_evidence = replace(oracle_evidence, workload_id=workload_id)
        candidate_evidence = replace(
            candidate_evidence,
            workload_id=workload_id,
            source_tree_hash_before=candidate_source_before,
            source_tree_hash_after=candidate_source_after,
            execution_phase="EXECUTE" if compilation.success else "BUILD",
        )

        if progress is not None:
            progress("COMPARING")
        if self._config.workload is not None:
            artifact_evidence, comparison_evidence, _, _ = self._run_declaration_driven(
                run_id, workload_id, oracle_result, candidate_result,
                source_identity, candidate_identity,
            )
        else:
            artifact_evidence, comparison_evidence = self._run_legacy(
                run_id, oracle_result, candidate_result,
            )
        comparison_evidence = tuple(
            replace(c, workload_id=workload_id) for c in comparison_evidence
        )

        environment_identities = (
            EnvironmentIdentity(
                runtime_id="oracle-gnucobol-3.1.2",
                cobol_compiler=self._config.oracle_compiler_version,
                os_base="gnucobol-ocesql",
                network_policy="none",
                resource_limits={"memory": "512m", "cpus": "1.0", "pids_limit": "256"},
            ),
            EnvironmentIdentity(
                runtime_id="candidate-java",
                java_version=getattr(self._candidate_adapter, "java_version", "") or None,
                network_policy="none",
                resource_limits=self._candidate_resource_limits(),
            ),
        )
        controlled_input_identity = InputIdentity(
            input_id=f"input-{run_id.value}",
            stdin_hash=ContentHash.from_bytes(controlled_input or b""),
            input_files=input_file_hashes,
        )

        manifest = EvidenceManifest(
            manifest_version="1.0",
            run_id=run_id,
            workload_id=workload_id,
            source_identity=source_identity,
            candidate_identity=candidate_identity,
            oracle_identity=self._oracle_adapter.get_identity(),
            environment_identities=environment_identities,
            controlled_input=controlled_input_identity,
            execution_evidence=(oracle_evidence, candidate_evidence),
            artifact_evidence=artifact_evidence,
            comparison_evidence=comparison_evidence,
        )

        # Trust-boundary admission: validate evidence integrity before derivation
        if progress is not None:
            progress("VALIDATING_EVIDENCE")
        validation_result = self._integrity_validator.validate(manifest)
        if isinstance(validation_result, list):
            # Trust boundary violated — untrusted evidence can never certify
            # equivalence: derive the natural verdict for diagnostics, but
            # clamp VERIFIED to ERROR with the violations as differences.
            verdict = derive_verdict_untrusted(manifest, validation_result)
        else:
            verdict = derive_verdict_validated(validation_result)

        return PipelineResult(
            run_id=run_id,
            workload_id=workload_id,
            source_identity=source_identity,
            oracle_identity=self._oracle_adapter.get_identity(),
            candidate_identity=candidate_identity,
            oracle_evidence=oracle_evidence,
            candidate_evidence=candidate_evidence,
            artifact_evidence=artifact_evidence,
            comparison_evidence=comparison_evidence,
            evidence_manifest=manifest,
            verdict=verdict,
            oracle_stdout=oracle_result.stdout,
            candidate_stdout=candidate_result.stdout,
            oracle_stderr=oracle_result.stderr,
            candidate_stderr=candidate_result.stderr,
            oracle_exit_code=oracle_result.exit_code,
            candidate_exit_code=candidate_result.exit_code,
        )

    def _run_legacy(
        self, run_id: RunId, oracle_result: object, candidate_result: object,
    ) -> tuple[tuple[ArtifactEvidence, ...], tuple[ComparisonEvidence, ...]]:
        """Legacy hardcoded path for backward compatibility."""
        from engine.comparators.framework import (
            ExitStatusComparator,
            FixedRecordComparator,
            StderrComparator,
            StdoutComparator,
            TextFileComparator,
        )

        oracle_stdout_artifact = self._capturer.capture_stdout(
            oracle_result.execution_id, oracle_result.stdout, "oracle-stdout", "ORACLE"
        )
        oracle_stderr_artifact = self._capturer.capture_stderr(
            oracle_result.execution_id, oracle_result.stderr, "oracle-stderr", "ORACLE"
        )
        _oracle_ec = oracle_result.exit_code
        oracle_exit_artifact = self._capturer.capture_exit_status(
            oracle_result.execution_id, _oracle_ec if _oracle_ec is not None else -1, "ORACLE"
        )

        candidate_stdout_artifact = self._capturer.capture_stdout(
            candidate_result.execution_id, candidate_result.stdout, "candidate-stdout", "CANDIDATE"
        )
        candidate_stderr_artifact = self._capturer.capture_stderr(
            candidate_result.execution_id, candidate_result.stderr, "candidate-stderr", "CANDIDATE"
        )
        _cand_ec = candidate_result.exit_code
        candidate_exit_artifact = self._capturer.capture_exit_status(
            candidate_result.execution_id, _cand_ec if _cand_ec is not None else -1, "CANDIDATE"
        )

        oracle_artifacts_list = [
            oracle_stdout_artifact,
            oracle_stderr_artifact,
            oracle_exit_artifact,
        ]
        candidate_artifacts_list = [
            candidate_stdout_artifact,
            candidate_stderr_artifact,
            candidate_exit_artifact,
        ]

        oracle_generated = oracle_result.generated_files or {}
        candidate_generated = candidate_result.generated_files or {}

        all_generated_names = sorted(set(list(oracle_generated.keys()) + list(candidate_generated.keys())))

        oracle_file_artifacts: dict[str, CapturedArtifact] = {}
        candidate_file_artifacts: dict[str, CapturedArtifact] = {}

        for name in all_generated_names:
            oracle_content = oracle_generated.get(name, b"")
            candidate_content = candidate_generated.get(name, b"")

            is_fixed = name.endswith((".dat", ".rec"))
            logical = name.rsplit(".", 1)[0] if "." in name else name

            if is_fixed:
                oa = self._capturer.capture_fixed_record(
                    oracle_result.execution_id, oracle_content, logical, "ORACLE"
                )
                ca = self._capturer.capture_fixed_record(
                    candidate_result.execution_id, candidate_content, logical, "CANDIDATE"
                )
            else:
                oa = self._capturer.capture_text_file_from_bytes(
                    oracle_result.execution_id, oracle_content, logical, "ORACLE"
                )
                ca = self._capturer.capture_text_file_from_bytes(
                    candidate_result.execution_id, candidate_content, logical, "CANDIDATE"
                )

            oracle_artifacts_list.append(oa)
            candidate_artifacts_list.append(ca)
            oracle_file_artifacts[name] = oa
            candidate_file_artifacts[name] = ca

        artifact_evidence = tuple(a.to_evidence() for a in oracle_artifacts_list + candidate_artifacts_list)

        comparison_evidence = []

        stdout_comparator = StdoutComparator()
        stdout_result = stdout_comparator.compare(
            oracle_stdout_artifact.artifact,
            oracle_stdout_artifact.content,
            candidate_stdout_artifact.artifact,
            candidate_stdout_artifact.content,
        )
        comparison_evidence.append(ComparisonEvidence(
            comparison_id=f"comp-stdout-{run_id.value}",
            run_id=run_id,
            comparator_id="stdout-exact",
            comparator_version="1.0.0",
            oracle_artifact_id=oracle_stdout_artifact.artifact.artifact_id,
            candidate_artifact_id=candidate_stdout_artifact.artifact.artifact_id,
            artifact_type="STDOUT",
            result=stdout_result.result.value,
            normalization_applied=stdout_result.normalization_applied,
            differences=tuple(d.description for d in stdout_result.differences),
            field_level_results=(),
            content_hash=ContentHash.from_string(json.dumps({
                "result": stdout_result.result.value,
                "differences": [{"location": d.location, "expected": d.expected, "actual": d.actual} for d in stdout_result.differences],
            }, sort_keys=True)),
        ))

        exit_comparator = ExitStatusComparator()
        exit_result = exit_comparator.compare(
            oracle_exit_artifact.artifact,
            oracle_exit_artifact.content,
            candidate_exit_artifact.artifact,
            candidate_exit_artifact.content,
        )
        comparison_evidence.append(ComparisonEvidence(
            comparison_id=f"comp-exit-{run_id.value}",
            run_id=run_id,
            comparator_id="exit-status-exact",
            comparator_version="1.0.0",
            oracle_artifact_id=oracle_exit_artifact.artifact.artifact_id,
            candidate_artifact_id=candidate_exit_artifact.artifact.artifact_id,
            artifact_type="EXIT_STATUS",
            result=exit_result.result.value,
            normalization_applied=exit_result.normalization_applied,
            differences=tuple(d.description for d in exit_result.differences),
            field_level_results=(),
            content_hash=ContentHash.from_string(json.dumps({
                "result": exit_result.result.value,
                "differences": [{"location": d.location, "expected": d.expected, "actual": d.actual} for d in exit_result.differences],
            }, sort_keys=True)),
        ))

        stderr_comparator = StderrComparator()
        stderr_result = stderr_comparator.compare(
            oracle_stderr_artifact.artifact,
            oracle_stderr_artifact.content,
            candidate_stderr_artifact.artifact,
            candidate_stderr_artifact.content,
        )
        comparison_evidence.append(ComparisonEvidence(
            comparison_id=f"comp-stderr-{run_id.value}",
            run_id=run_id,
            comparator_id="stderr-exact",
            comparator_version="1.0.0",
            oracle_artifact_id=oracle_stderr_artifact.artifact.artifact_id,
            candidate_artifact_id=candidate_stderr_artifact.artifact.artifact_id,
            artifact_type="STDERR",
            result=stderr_result.result.value,
            normalization_applied=stderr_result.normalization_applied,
            differences=tuple(d.description for d in stderr_result.differences),
            field_level_results=(),
            content_hash=ContentHash.from_string(json.dumps({
                "result": stderr_result.result.value,
                "differences": [{"location": d.location, "expected": d.expected, "actual": d.actual} for d in stderr_result.differences],
            }, sort_keys=True)),
        ))

        for name in all_generated_names:
            oa = oracle_file_artifacts[name]
            ca = candidate_file_artifacts[name]
            is_fixed = name.endswith((".dat", ".rec"))
            comp_id = "fixed-record-exact" if is_fixed else "text-file-exact"
            artifact_type = "FIXED_RECORD" if is_fixed else "TEXT_FILE"
            comparator = FixedRecordComparator() if is_fixed else TextFileComparator()
            comp_result = comparator.compare(
                oa.artifact, oa.content, ca.artifact, ca.content,
            )
            comparison_evidence.append(ComparisonEvidence(
                comparison_id=f"comp-{artifact_type.lower()}-{name}-{run_id.value}",
                run_id=run_id,
                comparator_id=comp_id,
                comparator_version="1.0.0",
                oracle_artifact_id=oa.artifact.artifact_id,
                candidate_artifact_id=ca.artifact.artifact_id,
                artifact_type=artifact_type,
                result=comp_result.result.value,
                normalization_applied=comp_result.normalization_applied,
                differences=tuple(d.description for d in comp_result.differences),
                field_level_results=(),
                content_hash=ContentHash.from_string(json.dumps({
                    "result": comp_result.result.value,
                    "differences": [{"location": d.location, "expected": d.expected, "actual": d.actual} for d in comp_result.differences],
                }, sort_keys=True)),
            ))

        return artifact_evidence, tuple(comparison_evidence)
