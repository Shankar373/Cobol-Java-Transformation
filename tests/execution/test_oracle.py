"""Tests for oracle adapter interface."""

import pytest

from engine.domain.identities import (
    AdapterStatus,
    ExecutionId,
    RunId,
)
from engine.oracle.adapter import (
    GnuCOBOLAdapter,
    OracleAdapterConfig,
    OracleExecutionResult,
)

# ---------------------------------------------------------------------------
# OracleAdapterConfig tests
# ---------------------------------------------------------------------------

class TestOracleAdapterConfig:
    def test_valid_config(self):
        config = OracleAdapterConfig(
            oracle_id="gnucobol-3.1.2",
            image_digest="sha256:" + "a" * 64,
            compiler_version="3.1.2.0",
        )
        assert config.validate() == []

    def test_invalid_oracle_id(self):
        config = OracleAdapterConfig(
            oracle_id="",
            image_digest="sha256:" + "a" * 64,
            compiler_version="3.1.2.0",
        )
        violations = config.validate()
        assert "oracle_id is required" in violations

    def test_invalid_image_digest(self):
        config = OracleAdapterConfig(
            oracle_id="gnucobol-3.1.2",
            image_digest="latest",
            compiler_version="3.1.2.0",
        )
        violations = config.validate()
        assert "image_digest must be sha256-pinned" in violations

    def test_invalid_compiler_version(self):
        config = OracleAdapterConfig(
            oracle_id="gnucobol-3.1.2",
            image_digest="sha256:" + "a" * 64,
            compiler_version="",
        )
        violations = config.validate()
        assert "compiler_version is required" in violations


# ---------------------------------------------------------------------------
# GnuCOBOLAdapter tests
# ---------------------------------------------------------------------------

class TestGnuCOBOLAdapter:
    def test_valid_creation(self):
        config = OracleAdapterConfig(
            oracle_id="gnucobol-3.1.2",
            image_digest="sha256:" + "a" * 64,
            compiler_version="3.1.2.0",
        )
        adapter = GnuCOBOLAdapter(config)
        assert adapter.config.oracle_id == "gnucobol-3.1.2"

    def test_invalid_oracle_id_raises(self):
        config = OracleAdapterConfig(
            oracle_id="wrong-oracle",
            image_digest="sha256:" + "a" * 64,
            compiler_version="3.1.2.0",
        )
        with pytest.raises(ValueError, match="gnucobol-3.1.2"):
            GnuCOBOLAdapter(config)

    def test_probe_available(self):
        config = OracleAdapterConfig(
            oracle_id="gnucobol-3.1.2",
            image_digest="sha256:" + "a" * 64,
            compiler_version="3.1.2.0",
        )
        adapter = GnuCOBOLAdapter(config)
        status = adapter.probe()
        assert status == AdapterStatus.AVAILABLE

    def test_probe_unavailable(self):
        config = OracleAdapterConfig(
            oracle_id="gnucobol-3.1.2",
            image_digest="",  # Invalid
            compiler_version="3.1.2.0",
        )
        adapter = GnuCOBOLAdapter(config)
        status = adapter.probe()
        assert status == AdapterStatus.UNAVAILABLE

    def test_execute(self):
        config = OracleAdapterConfig(
            oracle_id="gnucobol-3.1.2",
            image_digest="sha256:" + "a" * 64,
            compiler_version="3.1.2.0",
        )
        adapter = GnuCOBOLAdapter(config)
        result = adapter.execute(
            run_id=RunId(value="run-001"),
            source_path="/workspace/source",
        )
        assert result.status == AdapterStatus.SUCCEEDED
        assert result.exit_code == 0
        assert result.termination_status == "normal"

    def test_get_identity(self):
        config = OracleAdapterConfig(
            oracle_id="gnucobol-3.1.2",
            image_digest="sha256:" + "a" * 64,
            compiler_version="3.1.2.0",
            preprocessor_version="1.4",
        )
        adapter = GnuCOBOLAdapter(config)
        identity = adapter.get_identity()
        assert identity.oracle_id == "gnucobol-3.1.2"
        assert identity.compiler_version == "3.1.2.0"
        assert identity.preprocessor_version == "1.4"


# ---------------------------------------------------------------------------
# OracleExecutionResult tests
# ---------------------------------------------------------------------------

class TestOracleExecutionResult:
    def test_to_execution_evidence(self):
        result = OracleExecutionResult(
            execution_id=ExecutionId(value="exec-001"),
            run_id=RunId(value="run-001"),
            oracle_id="gnucobol-3.1.2",
            status=AdapterStatus.SUCCEEDED,
            exit_code=0,
            stdout=b"hello",
            stderr=b"",
            start_time="2026-09-14T00:00:00Z",
            end_time="2026-09-14T00:00:01Z",
            termination_status="normal",
            timeout_applied=False,
        )
        evidence = result.to_execution_evidence()
        assert evidence.exit_code == 0
        assert evidence.termination_status == "normal"
