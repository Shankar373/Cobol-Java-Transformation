"""Phase 9 batch P2a — carry-forward defect fixes (BL-050/051/054).

Each test pins the fixed behavior; red-first evidence is captured in the
Phase 9 audit (defects were verified statically at baseline ``4deddfc``).
Docker is not required: the adapters are constructed without ``__init__``
(image resolution) and ``subprocess.run`` is monkeypatched, mirroring the
established pattern in ``tests/candidate/test_maven_failure_reporting.py``.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from engine.domain.identities import AdapterStatus, ContentHash, RunId


# ---------------------------------------------------------------------------
# BL-050 — docker_java_adapter compile-timeout path
# ---------------------------------------------------------------------------
def test_bl050_java_compile_timeout_reports_and_cleans_container(
    tmp_path, monkeypatch
):
    from engine.candidate.docker_java_adapter import (
        DockerJavaCandidateAdapter,
        DockerJavaConfig,
        CandidateManifest,
    )

    adapter = object.__new__(DockerJavaCandidateAdapter)
    adapter._status = AdapterStatus.AVAILABLE
    adapter._config = DockerJavaConfig()
    adapter._resolved_digest = "sha256:" + "0" * 64

    (tmp_path / "Main.java").write_text("class Main {}", encoding="utf-8")
    manifest = CandidateManifest(
        candidate_id="bl050",
        workload_id="wl-bl050",
        source_hash="test",
        generated_files={"Main.java": "test"},
        entrypoint="Main",
    )

    cleaned: list[str] = []
    monkeypatch.setattr(
        DockerJavaCandidateAdapter,
        "_cleanup_container",
        staticmethod(lambda name: (cleaned.append(name), "removed")[1]),
    )

    def _timeout(command, **kwargs):
        raise subprocess.TimeoutExpired(cmd=command, timeout=1)

    monkeypatch.setattr(subprocess, "run", _timeout)

    result = adapter.compile(str(tmp_path), manifest)

    assert result.success is False
    # The real timeout message reaches the caller (no UnboundLocalError /
    # generic-failure masking).
    assert any("timed out" in e for e in result.compilation_errors)
    # The container is explicitly removed on the timeout path.
    assert cleaned and cleaned[0].startswith("javac-")


# ---------------------------------------------------------------------------
# BL-051 — oracle docker timeout path has no name / no cleanup
# ---------------------------------------------------------------------------
def test_bl051_oracle_timeout_names_and_cleans_container(tmp_path, monkeypatch):
    import engine.oracle.docker_adapter as oracle_mod
    from engine.oracle.docker_adapter import DockerOracleAdapter
    from engine.oracle.adapter import OracleAdapterConfig

    cob = tmp_path / "MAIN.cob"
    cob.write_text(
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. MAIN.\n"
        "       PROCEDURE DIVISION.\n"
        "           DISPLAY 'X'.\n"
        "           STOP RUN.\n",
        encoding="utf-8",
    )

    adapter = object.__new__(DockerOracleAdapter)
    adapter._config = OracleAdapterConfig(
        oracle_id="gnucobol-test",
        image_digest="",
        compiler_version="3.1.2.0",
        timeout_seconds=1,
    )
    adapter._docker_available = True
    monkeypatch.setattr(
        adapter, "_resolve_image_identity", lambda: ("img@sha256:" + "a" * 64, "sha256:" + "a" * 64)
    )
    monkeypatch.setattr(
        adapter,
        "_compute_source_hash",
        lambda _p: ContentHash(digest="b" * 64),
    )

    cleaned: list[str] = []
    monkeypatch.setattr(
        oracle_mod,
        "cleanup_container",
        lambda name: (cleaned.append(name) or True, "removed"),
    )

    def _timeout(command, **kwargs):
        # The run must be issued with a --name so cleanup is possible.
        assert "--name" in command
        raise subprocess.TimeoutExpired(cmd=command, timeout=1)

    monkeypatch.setattr(subprocess, "run", _timeout)

    result = adapter.execute(
        run_id=RunId(value="bl051-run"),
        source_path=str(tmp_path),
        entry_program="MAIN",
    )

    assert result.termination_status == "timeout"
    assert result.timeout_applied is True
    # Container named with the oracle- prefix and removed on timeout.
    assert cleaned and cleaned[0].startswith("oracle-")
    assert b"Oracle execution timeout" in result.stderr


# ---------------------------------------------------------------------------
# BL-054 — candidate identity must ignore build outputs (target/)
# ---------------------------------------------------------------------------
def test_bl054_candidate_identity_ignores_build_output_target_dir(tmp_path):
    from engine.pipeline import PipelineConfig, VerticalSlicePipeline

    candidate = tmp_path / "candidate"
    (candidate / "src").mkdir(parents=True)
    (candidate / "src" / "Main.java").write_text("class Main {}", encoding="utf-8")
    (candidate / "pom.xml").write_text("<project/>", encoding="utf-8")

    config = PipelineConfig(
        workload_id="wl-bl054",
        cobol_source_path=str(tmp_path / "src.cob"),
        java_candidate_path=str(candidate),
        java_entrypoint="Main",
    )
    pipeline = object.__new__(VerticalSlicePipeline)
    pipeline._config = config

    source_hash = ContentHash(digest="c" * 64)
    first = pipeline._compute_candidate_identity(source_hash)

    # A build writes a JAR under target/ (the Spring Boot adapter's
    # execute-findability workaround).  The identity must not change.
    target_dir = candidate / "target"
    target_dir.mkdir()
    (target_dir / "app.jar").write_bytes(b"jar-bytes-v1")
    second = pipeline._compute_candidate_identity(source_hash)

    # Rebuild produces a different JAR; identity still must not change.
    (target_dir / "app.jar").write_bytes(b"jar-bytes-v2-different")
    third = pipeline._compute_candidate_identity(source_hash)

    assert first.candidate_hash == second.candidate_hash
    assert first.candidate_hash == third.candidate_hash
    # Build outputs are excluded from the counted file set.
    assert first.file_count == 2  # Main.java + pom.xml
    assert second.file_count == 2
