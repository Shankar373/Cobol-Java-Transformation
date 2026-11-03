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
    def test_complete_config_validates_without_violations(self):
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
    def test_constructor_stores_supplied_config(self):
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

    def test_probe_fails_closed_instead_of_trusting_config(self):
        """audit D-6: config validation cannot prove a compiler exists.

        The old probe returned AVAILABLE whenever the config fields were
        non-empty — a host with neither Docker nor cobc read as ready.
        """
        config = OracleAdapterConfig(
            oracle_id="gnucobol-3.1.2",
            image_digest="sha256:" + "a" * 64,
            compiler_version="3.1.2.0",
        )
        adapter = GnuCOBOLAdapter(config)
        with pytest.raises(NotImplementedError, match="DockerOracleAdapter"):
            adapter.probe()

    def test_execute_fails_closed_not_fabricated_success(self):
        """audit D-6: the placeholder must not fabricate an oracle run."""
        config = OracleAdapterConfig(
            oracle_id="gnucobol-3.1.2",
            image_digest="sha256:" + "a" * 64,
            compiler_version="3.1.2.0",
        )
        adapter = GnuCOBOLAdapter(config)
        with pytest.raises(NotImplementedError, match="DockerOracleAdapter"):
            adapter.execute(
                run_id=RunId(value="run-001"),
                source_path="/workspace/source",
            )

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
