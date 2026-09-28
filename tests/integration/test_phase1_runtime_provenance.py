"""Phase 1 runtime provenance integration checks."""

from __future__ import annotations

import pytest
from pathlib import Path

from engine.candidate.adapter import CandidateManifest
from engine.candidate.docker_java_adapter import DockerJavaCandidateAdapter
from engine.candidate.docker_spring_boot_adapter import DockerSpringBootCandidateAdapter
from engine.oracle.adapter import OracleAdapterConfig
from engine.oracle.docker_adapter import DockerOracleAdapter


def test_docker_java_adapter_reports_observed_runtime_identity():
    adapter = DockerJavaCandidateAdapter()
    if not adapter.available:
        pytest.skip("Docker Java runtime is not available with an immutable image identity")

    assert adapter.resolved_digest
    assert "sha256:" in adapter.resolved_digest
    assert adapter.java_version
    assert "version" in adapter.java_version.lower()
    assert "21." in adapter.java_version
    assert adapter.docker_version


def test_spring_boot_adapter_reports_observed_runtime_identity():
    adapter = DockerSpringBootCandidateAdapter()
    if not adapter.available:
        pytest.skip("Spring Boot Docker runtime is not available with verified images")

    assert adapter.runtime_identity
    assert "@sha256:" in adapter.runtime_identity
    assert adapter.java_version
    assert "version" in adapter.java_version.lower()
    assert "21." in adapter.java_version
    assert adapter.maven_version
    assert adapter.docker_version


def test_oracle_adapter_requires_verified_runtime_identity():
    adapter = DockerOracleAdapter(
        OracleAdapterConfig(
            oracle_id="gnucobol-3.1.2",
            image_digest="sha256:" + "f" * 64,
            compiler_version="3.1.2.0",
        )
    )
    assert adapter.probe().value == "UNAVAILABLE"

def test_docker_java_execution_evidence_contains_observed_identity():
    adapter = DockerJavaCandidateAdapter()
    if not adapter.available:
        pytest.skip("Docker Java runtime is not available with an immutable image identity")

    fixture = (
        Path(__file__).resolve().parents[2]
        / "fixtures" / "workload-arithmetic" / "java-candidate"
    )
    manifest = CandidateManifest(
        candidate_id="phase1-candidate",
        workload_id="phase1-runtime",
        source_hash="phase1-source",
        generated_files={"Arithmetic.java": "fixture-hash"},
        entrypoint="Arithmetic",
        producer_identity="internal-native-java-producer",
        producer_version="1.0.0",
        java_version=adapter.java_version,
    )
    compilation = adapter.compile(str(fixture), manifest)
    assert compilation.success

    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        for name, bytecode in compilation.class_files.items():
            target = Path(tmpdir) / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(bytecode)
        result = adapter.execute(
            run_id=__import__("engine.domain.identities", fromlist=["RunId"]).RunId("phase1-runtime"),
            compiled_path=tmpdir,
            manifest=manifest,
        )

    evidence = result.to_execution_evidence()
    assert evidence.java_version == adapter.java_version
    assert evidence.image_digest == adapter.resolved_digest
    assert evidence.producer_identity == manifest.producer_identity
    assert evidence.producer_version == manifest.producer_version
    assert evidence.provenance_hash is not None

