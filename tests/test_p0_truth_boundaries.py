"""P0 truth-boundary regression tests."""
from __future__ import annotations
from pathlib import Path
from engine.comparators.framework import ComparisonResult, create_default_registry
from engine.domain.identities import ArtifactIdentity, ContentHash, ExecutionId
from engine.execution.artifacts import ArtifactCapturer
from engine.modernization.modernization_planner import ModernizationPlanner, ModernizationStatus
from engine.pipeline import PipelineConfig, VerticalSlicePipeline
from engine.transformation.application_discovery import ApplicationDiscovery

VALID = """IDENTIFICATION DIVISION.
PROGRAM-ID. VALID.
PROCEDURE DIVISION.
MAIN.
    DISPLAY "OK".
    STOP RUN.
"""
INVALID = "THIS IS NOT COBOL.\n"

def _artifact(role: str, name: str) -> ArtifactIdentity:
    return ArtifactIdentity(
        artifact_id=f"{role.lower()}-{name}",
        artifact_type="TEXT_FILE",
        logical_name=name,
        producer_role=role,
        content_hash=ContentHash.from_string(f"{role}:{name}"),
        size_bytes=0,
    )

def test_discovery_preserves_parse_failure_and_blocks_planning(tmp_path: Path) -> None:
    (tmp_path / "valid.cob").write_text(VALID, encoding="utf-8")
    (tmp_path / "invalid.cob").write_text(INVALID, encoding="utf-8")
    app = ApplicationDiscovery().discover(tmp_path, application_id="mixed")
    assert app.discovery_complete is False
    assert {u.source_path for u in app.programs} == {"valid.cob", "invalid.cob"}
    failed = next(u for u in app.programs if u.source_path == "invalid.cob")
    assert failed.program is None
    assert failed.status == "PARSE_FAILED"
    plan = ModernizationPlanner(docker_available=True).plan(tmp_path, application_id="mixed")
    assert plan.discovery_complete is False
    assert plan.overall_status == ModernizationStatus.BLOCKED
    assert any("invalid.cob" in item for item in plan.blocking_summary)

def test_genuine_zero_byte_file_remains_present() -> None:
    captured = ArtifactCapturer().capture_text_file_from_bytes(ExecutionId("exec-empty"), b"", "empty", "ORACLE")
    assert captured.content == b""
    assert captured.artifact.availability == "PRESENT"
    assert captured.size_bytes == 0

def test_both_missing_are_not_empty_and_never_match() -> None:
    capturer = ArtifactCapturer()
    oracle = capturer.capture_missing(ExecutionId("oracle"), "TEXT_FILE", "f", "ORACLE")
    candidate = capturer.capture_missing(ExecutionId("candidate"), "TEXT_FILE", "f", "CANDIDATE")
    policy = type("Policy", (), {"on_missing": "UNAVAILABLE"})()
    result = create_default_registry().get("TEXT_FILE").compare(
        oracle.artifact, oracle.content, candidate.artifact, candidate.content,
        normalization_policy=(), ordering="SEQUENTIAL", failure_policy=policy,
    )
    assert oracle.content is None and candidate.content is None
    assert result.result == ComparisonResult.INCONCLUSIVE

def test_missing_vs_present_honors_failure_policy() -> None:
    capturer = ArtifactCapturer()
    oracle = capturer.capture_missing(ExecutionId("oracle2"), "TEXT_FILE", "f", "ORACLE")
    candidate = capturer.capture_text_file_from_bytes(ExecutionId("candidate2"), b"", "f", "CANDIDATE")
    policy = type("Policy", (), {"on_missing": "FAILED"})()
    result = create_default_registry().get("TEXT_FILE").compare(
        oracle.artifact, oracle.content, candidate.artifact, candidate.content,
        normalization_policy=(), ordering="SEQUENTIAL", failure_policy=policy,
    )
    assert result.result == ComparisonResult.MISMATCH

def test_declared_normalization_controls_comparison() -> None:
    registry = create_default_registry()
    oracle, candidate = _artifact("ORACLE", "out"), _artifact("CANDIDATE", "out")
    no_norm = registry.get("TEXT_FILE").compare(oracle, b"A\r\nB", candidate, b"A\nB", normalization_policy=(), ordering="SEQUENTIAL")
    with_norm = registry.get("TEXT_FILE").compare(oracle, b"A\r\nB", candidate, b"A\nB", normalization_policy=("crlf_to_lf",), ordering="SEQUENTIAL")
    assert no_norm.result == ComparisonResult.MISMATCH
    assert with_norm.result == ComparisonResult.MATCH

def test_declared_ordering_controls_comparison() -> None:
    registry = create_default_registry()
    oracle, candidate = _artifact("ORACLE", "out"), _artifact("CANDIDATE", "out")
    sequential = registry.get("TEXT_FILE").compare(oracle, b"B\nA\n", candidate, b"A\nB\n", normalization_policy=(), ordering="SEQUENTIAL")
    sorted_result = registry.get("TEXT_FILE").compare(oracle, b"B\nA\n", candidate, b"A\nB\n", normalization_policy=(), ordering="SORTED")
    assert sequential.result == ComparisonResult.MISMATCH
    assert sorted_result.result == ComparisonResult.MATCH

def test_missing_extraction_returns_none() -> None:
    class Result:
        stdout = b""
        stderr = b""
        exit_code = 0
        generated_files = {}
    pipeline = VerticalSlicePipeline(PipelineConfig(
        workload_id="p0", cobol_source_path="missing.cob",
        java_candidate_path="candidate", java_entrypoint="Main", use_docker_java=False,
    ))
    assert pipeline._extract_artifact_content("TEXT_FILE", "missing.txt", Result()) is None
