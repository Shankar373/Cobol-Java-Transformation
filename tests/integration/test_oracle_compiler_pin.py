"""The oracle's compiler version is observed, not assumed (audit V5/V6).

``OracleIdentity.compiler_version`` was a config literal: a rebuilt oracle
image carrying another GnuCOBOL would still be recorded as 3.1.2.0 in sealed
evidence.  The adapter now runs ``cobc --version`` inside the pinned image
(once per immutable identity) and refuses to execute any program when it
differs from the declared version.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from engine.domain.identities import RunId
from engine.oracle.adapter import AdapterStatus, OracleAdapterConfig
from engine.oracle.docker_adapter import DockerOracleAdapter, parse_cobc_version

HELLO = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. HELLO.\n"
    "       PROCEDURE DIVISION.\n"
    "       MAIN-PARA.\n"
    '           DISPLAY "HELLO-ORACLE".\n'
    "           STOP RUN.\n"
)


def test_parse_cobc_version() -> None:
    banner = (
        "cobc (GnuCOBOL) 3.1.2.0\n"
        "Copyright (C) 2020 Free Software Foundation, Inc.\n"
    )
    assert parse_cobc_version(banner) == "3.1.2.0"
    assert parse_cobc_version("cobc (OpenCOBOL) 1.1.0\n") == ""
    assert parse_cobc_version("") == ""


def _adapter(compiler_version: str) -> DockerOracleAdapter:
    if os.environ.get("RUN_DOCKER_TESTS") != "1":
        pytest.skip("Docker lane test: set RUN_DOCKER_TESTS=1 to run it")
    return DockerOracleAdapter(OracleAdapterConfig(
        oracle_id="gnucobol-3.1.2",
        image_digest="",
        compiler_version=compiler_version,
        timeout_seconds=120,
    ))


def test_declared_version_mismatch_refuses_before_running(tmp_path: Path) -> None:
    (tmp_path / "HELLO.cob").write_text(HELLO, encoding="utf-8")
    outcome = _adapter("9.9.9").execute(RunId(value="run-pin-mismatch"), str(tmp_path))

    assert outcome.status == AdapterStatus.UNAVAILABLE
    assert outcome.exit_code is None
    assert outcome.stdout == b""
    stderr = outcome.stderr.decode()
    assert "compiler version mismatch" in stderr
    assert "declared 9.9.9" in stderr and "observed 3.1.2.0" in stderr


def test_matching_version_runs_and_records_observed_version(tmp_path: Path) -> None:
    (tmp_path / "HELLO.cob").write_text(HELLO, encoding="utf-8")
    adapter = _adapter("3.1.2.0")
    outcome = adapter.execute(RunId(value="run-pin-match"), str(tmp_path))

    assert outcome.exit_code == 0, outcome.stderr.decode(errors="replace")
    assert outcome.stdout.decode().splitlines() == ["HELLO-ORACLE"]
    assert adapter.get_identity().compiler_version == "3.1.2.0"
