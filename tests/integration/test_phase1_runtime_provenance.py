"""Phase 1 runtime provenance integration checks."""

from __future__ import annotations

import pytest

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
    assert adapter.docker_version


def test_spring_boot_adapter_reports_observed_runtime_identity():
    adapter = DockerSpringBootCandidateAdapter()
    if not adapter.available:
        pytest.skip("Spring Boot Docker runtime is not available with verified images")

    assert adapter.runtime_identity
    assert "@sha256:" in adapter.runtime_identity
    assert adapter.java_version
    assert "version" in adapter.java_version.lower()
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
