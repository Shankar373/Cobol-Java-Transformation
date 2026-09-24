"""Regression tests for oracle source-format handling (free vs fixed).

GnuCOBOL defaults to fixed source format. The fixture estate mixes
free-format and fixed-format COBOL, so the oracle must select the format
flag per compilation unit. These tests pin:

1. format detection over representative real fixtures and directives;
2. the compile-flag contract (``-free`` only for all-free module sets);
3. Docker-gated proof that a free-format workload now compiles through the
   oracle compilation path while fixed-format workloads are unchanged.

No fixture is modified and no workload is special-cased.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from engine.oracle.adapter import OracleAdapterConfig
from engine.oracle.docker_adapter import DockerOracleAdapter

FIXTURES = Path("fixtures")


def _read(rel: str) -> str:
    return (FIXTURES / rel).read_text(encoding="utf-8", errors="ignore")


# ---------------------------------------------------------------------------
# Format detection
# ---------------------------------------------------------------------------

class TestSourceFormatDetection:
    def test_free_format_fixture(self) -> None:
        assert DockerOracleAdapter.detect_source_format(
            _read("workload-copybook/cobol/MAIN.cob")
        ) == "free"

    def test_fixed_format_fixture(self) -> None:
        assert DockerOracleAdapter.detect_source_format(
            _read("workload-arithmetic/cobol/ARITH.cob")
        ) == "fixed"

    def test_fixed_format_with_sequence_area(self) -> None:
        assert DockerOracleAdapter.detect_source_format(
            _read("workload-db2/cobol/ACCOUNT-DB2.cob")
        ) == "fixed"

    def test_source_directive_free_wins(self) -> None:
        text = ">>SOURCE FORMAT FREE\nIDENTIFICATION DIVISION.\n"
        assert DockerOracleAdapter.detect_source_format(text) == "free"

    def test_source_directive_fixed_wins(self) -> None:
        text = ">>SOURCE FORMAT FIXED\n       IDENTIFICATION DIVISION.\n"
        assert DockerOracleAdapter.detect_source_format(text) == "fixed"

    def test_comment_only_defaults_to_fixed(self) -> None:
        assert DockerOracleAdapter.detect_source_format("* c\n/ page\n") == "fixed"

    def test_free_comment_then_free_code(self) -> None:
        text = "IDENTIFICATION DIVISION.\n*> comment\n"
        assert DockerOracleAdapter.detect_source_format(text) == "free"


# ---------------------------------------------------------------------------
# Compile-flag contract
# ---------------------------------------------------------------------------

class TestCompileFormatFlag:
    def test_free_directory_gets_free_flag(self) -> None:
        flag = DockerOracleAdapter._compile_format_flag(
            FIXTURES / "workload-copybook" / "cobol", ["MAIN.cob"]
        )
        assert flag == "-free "

    def test_fixed_directory_gets_no_flag(self) -> None:
        flag = DockerOracleAdapter._compile_format_flag(
            FIXTURES / "workload-arithmetic" / "cobol", ["ARITH.cob"]
        )
        assert flag == ""

    def test_mixed_set_defaults_to_fixed(self, tmp_path: Path) -> None:
        (tmp_path / "FREE.cob").write_text(
            "IDENTIFICATION DIVISION.\n", encoding="utf-8"
        )
        (tmp_path / "FIXED.cob").write_text(
            "       IDENTIFICATION DIVISION.\n", encoding="utf-8"
        )
        flag = DockerOracleAdapter._compile_format_flag(
            tmp_path, ["FREE.cob", "FIXED.cob"]
        )
        assert flag == ""


# ---------------------------------------------------------------------------
# Docker-gated: real oracle compilation
# ---------------------------------------------------------------------------

def _docker_available() -> bool:
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


needs_docker = pytest.mark.skipif(
    not _docker_available(), reason="Docker not available"
)


def _make_adapter() -> DockerOracleAdapter:
    return DockerOracleAdapter(OracleAdapterConfig(
        oracle_id="gnucobol-3.1.2",
        image_digest=DockerOracleAdapter.V1_DIGEST,
        compiler_version="3.1.2.0",
        timeout_seconds=120,
    ))


@needs_docker
class TestDockerOracleFormats:
    def test_free_format_workload_compiles_and_runs(self) -> None:
        """BLOCKER A regression: free-format source compiles via the oracle."""
        from engine.domain.identities import RunId

        adapter = _make_adapter()
        outcome = adapter.execute(
            RunId(value="run-ora-free"),
            str(FIXTURES / "workload-copybook" / "cobol"),
        )
        stdout = outcome.stdout.decode(errors="replace")
        assert outcome.exit_code == 0, outcome.stderr.decode(errors="replace")[:800]
        assert "COPYBOOK DEMO STARTED" in stdout
        assert "INITIAL CLAIM-AMOUNT=000100" in stdout
        assert "FINAL CLAIM-AMOUNT=000100" in stdout

    def test_fixed_format_workload_still_compiles(self) -> None:
        """No regression: fixed-format source is not reinterpreted as free."""
        from engine.domain.identities import RunId

        adapter = _make_adapter()
        outcome = adapter.execute(
            RunId(value="run-ora-fixed"),
            str(FIXTURES / "workload-arithmetic" / "cobol"),
        )
        assert outcome.exit_code == 0, outcome.stderr.decode(errors="replace")[:800]
