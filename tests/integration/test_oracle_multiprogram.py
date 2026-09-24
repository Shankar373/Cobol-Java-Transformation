"""Oracle multi-program execution tests (M6 oracle workstream).

Proves the GnuCOBOL oracle compiles/links/runs a discovered multi-program
application from its separate source modules (never concatenated):

    MAIN.cob --CALL--> CLAIMS.cob  (+ shared COMMON.cpy)

    => MAIN-START / CLAIMS-CALLED / MAIN-END, exit 0

Docker-free selection tests always run; Docker-gated runtime tests skip
cleanly when Docker is unavailable.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from engine.oracle.docker_adapter import DockerOracleAdapter

MAIN_COB = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. MAIN.\n"
    "       DATA DIVISION.\n"
    "       WORKING-STORAGE SECTION.\n"
    "       COPY COMMON.\n"
    "       01 WS-FLAG PIC X(1) VALUE 'N'.\n"
    "       PROCEDURE DIVISION.\n"
    "       MAIN-PARA.\n"
    '           DISPLAY "MAIN-START".\n'
    "           MOVE 'X' TO WS-FLAG.\n"
    "           CALL 'CLAIMS'.\n"
    '           DISPLAY "MAIN-END".\n'
    "           STOP RUN.\n"
)

CLAIMS_COB = (
    # NOTE: the callee ends by falling off PROCEDURE DIVISION (implicit
    # return to the caller). An explicit EXIT PROGRAM line would be
    # swallowed into the preceding DISPLAY by the parser's continuation
    # rule (same defect class as CALL); STOP RUN would kill the run unit.
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. CLAIMS.\n"
    "       DATA DIVISION.\n"
    "       WORKING-STORAGE SECTION.\n"
    "       COPY COMMON.\n"
    "       01 WS-DUMMY PIC X(1) VALUE 'N'.\n"
    "       PROCEDURE DIVISION.\n"
    "       CLAIM-PARA.\n"
    '           DISPLAY "CLAIMS-CALLED".\n'
)

COMMON_CPY = "       01 COMMON-REC PIC X(20).\n"

HELLO_COB = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. HELLO.\n"
    "       PROCEDURE DIVISION.\n"
    "       MAIN-PARA.\n"
    '           DISPLAY "HELLO-ORACLE".\n'
    "           STOP RUN.\n"
)

EXPECTED_CHAIN = ["MAIN-START", "CLAIMS-CALLED", "MAIN-END"]


def _write_multi(tmp_path: Path) -> Path:
    (tmp_path / "MAIN.cob").write_text(MAIN_COB, encoding="utf-8")
    (tmp_path / "CLAIMS.cob").write_text(CLAIMS_COB, encoding="utf-8")
    (tmp_path / "COMMON.cpy").write_text(COMMON_CPY, encoding="utf-8")
    return tmp_path


# ---------------------------------------------------------------------------
# Docker-free: module selection contract
# ---------------------------------------------------------------------------

class TestModuleSelection:
    def test_single_module_unchanged(self, tmp_path: Path) -> None:
        (tmp_path / "HELLO.cob").write_text(HELLO_COB, encoding="utf-8")
        entry, others = DockerOracleAdapter.select_modules(tmp_path)
        assert entry == "HELLO.cob"
        assert others == []

    def test_main_convention_selects_entry(self, tmp_path: Path) -> None:
        _write_multi(tmp_path)
        entry, others = DockerOracleAdapter.select_modules(tmp_path)
        assert entry == "MAIN.cob"
        assert others == ["CLAIMS.cob"]

    def test_explicit_entry_by_program_id(self, tmp_path: Path) -> None:
        _write_multi(tmp_path)
        entry, others = DockerOracleAdapter.select_modules(
            tmp_path, entry_program="CLAIMS"
        )
        assert entry == "CLAIMS.cob"
        assert others == ["MAIN.cob"]

    def test_copybooks_never_modules(self, tmp_path: Path) -> None:
        _write_multi(tmp_path)
        entry, others = DockerOracleAdapter.select_modules(tmp_path)
        assert "COMMON.cpy" not in others
        assert entry != "COMMON.cpy"

    def test_empty_dir_has_no_entry(self, tmp_path: Path) -> None:
        entry, others = DockerOracleAdapter.select_modules(tmp_path)
        assert entry is None
        assert others == []

    def test_cob_precedence_over_cbl(self, tmp_path: Path) -> None:
        (tmp_path / "B.cbl").write_text(HELLO_COB, encoding="utf-8")
        (tmp_path / "A.cob").write_text(HELLO_COB, encoding="utf-8")
        entry, others = DockerOracleAdapter.select_modules(tmp_path)
        assert entry == "A.cob"
        assert others == ["B.cbl"]


# ---------------------------------------------------------------------------
# Docker-gated: real multi-program oracle execution
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
    from engine.oracle.adapter import OracleAdapterConfig
    return DockerOracleAdapter(OracleAdapterConfig(
        oracle_id="gnucobol-3.1.2",
        image_digest=DockerOracleAdapter.V1_DIGEST,
        compiler_version="3.1.2.0",
        timeout_seconds=120,
    ))


@needs_docker
class TestDockerOracleExecution:
    def test_single_program_still_works(self, tmp_path: Path) -> None:
        from engine.domain.identities import RunId

        (tmp_path / "HELLO.cob").write_text(HELLO_COB, encoding="utf-8")
        outcome = _make_adapter().execute(RunId(value="run-ora-single"), str(tmp_path))

        assert outcome.exit_code == 0
        assert outcome.stdout.decode(errors="replace").splitlines() == ["HELLO-ORACLE"]

    def test_main_reaches_claims(self, tmp_path: Path) -> None:
        from engine.domain.identities import RunId

        _write_multi(tmp_path)
        outcome = _make_adapter().execute(RunId(value="run-ora-multi"), str(tmp_path))

        assert outcome.exit_code == 0, outcome.stderr.decode(errors="replace")[:500]
        assert outcome.stdout.decode(errors="replace").splitlines() == EXPECTED_CHAIN

    def test_explicit_entry_selects_callee(self, tmp_path: Path) -> None:
        from engine.domain.identities import RunId

        _write_multi(tmp_path)
        outcome = _make_adapter().execute(
            RunId(value="run-ora-entry"), str(tmp_path), entry_program="CLAIMS"
        )

        assert outcome.exit_code == 0
        assert outcome.stdout.decode(errors="replace").splitlines() == ["CLAIMS-CALLED"]

    def test_sources_not_concatenated(self, tmp_path: Path) -> None:
        from engine.domain.identities import RunId

        _write_multi(tmp_path)
        before = {
            p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()
        }
        outcome = _make_adapter().execute(RunId(value="run-ora-nocat"), str(tmp_path))

        assert outcome.exit_code == 0
        after = {
            p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()
        }
        assert before == after
        assert "CLAIMS" not in (tmp_path / "MAIN.cob").read_text(encoding="utf-8").replace(
            "CALL 'CLAIMS'.", ""
        )
        assert outcome.source_tree_hash_before == outcome.source_tree_hash_after

    def test_oracle_independent_from_java(self, tmp_path: Path) -> None:
        from engine.domain.identities import RunId

        _write_multi(tmp_path)
        assert not list(tmp_path.rglob("*.java"))
        assert not list(tmp_path.rglob("*.jar"))

        outcome = _make_adapter().execute(RunId(value="run-ora-indep"), str(tmp_path))

        assert outcome.exit_code == 0
        assert outcome.oracle_id == "gnucobol-3.1.2"
        assert outcome.stdout.decode(errors="replace").splitlines() == EXPECTED_CHAIN
