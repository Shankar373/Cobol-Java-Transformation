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
        entry, others = DockerOracleAdapter.select_modules(
            tmp_path, entry_program="A"
        )
        assert entry == "A.cob"
        assert others == ["B.cbl"]

    def test_uncalled_root_selects_entry(self, tmp_path: Path) -> None:
        # No main.* marker: the single program nothing CALLs is the entry,
        # even though it sorts after its callee.
        (tmp_path / "ZDRIVER.cob").write_text(
            MAIN_COB.replace("PROGRAM-ID. MAIN.", "PROGRAM-ID. ZDRIVER."),
            encoding="utf-8",
        )
        (tmp_path / "CLAIMS.cob").write_text(CLAIMS_COB, encoding="utf-8")
        (tmp_path / "COMMON.cpy").write_text(COMMON_CPY, encoding="utf-8")
        entry, others = DockerOracleAdapter.select_modules(tmp_path)
        assert entry == "ZDRIVER.cob"
        assert others == ["CLAIMS.cob"]

    def test_ambiguous_entry_selects_nothing(self, tmp_path: Path) -> None:
        # Two uncalled programs and no marker: never pick by file order.
        (tmp_path / "A.cob").write_text(HELLO_COB, encoding="utf-8")
        (tmp_path / "B.cob").write_text(
            HELLO_COB.replace("PROGRAM-ID. HELLO.", "PROGRAM-ID. OTHER."),
            encoding="utf-8",
        )
        entry, others = DockerOracleAdapter.select_modules(tmp_path)
        assert entry is None
        assert others == ["A.cob", "B.cob"]

    def test_duplicate_program_id_selects_nothing(self, tmp_path: Path) -> None:
        (tmp_path / "A.cob").write_text(HELLO_COB, encoding="utf-8")
        (tmp_path / "B.cob").write_text(HELLO_COB, encoding="utf-8")
        entry, others = DockerOracleAdapter.select_modules(
            tmp_path, entry_program="HELLO"
        )
        assert entry is None
        assert others == ["A.cob", "B.cob"]

    def test_unknown_explicit_entry_selects_nothing(self, tmp_path: Path) -> None:
        _write_multi(tmp_path)
        entry, others = DockerOracleAdapter.select_modules(
            tmp_path, entry_program="NOSUCH"
        )
        assert entry is None
        assert others == ["CLAIMS.cob", "MAIN.cob"]


class TestModuleDirectory:
    """Uploaded ZIPs keep their layout; the oracle must find nested programs.

    Before this, ``app/MAIN.cob`` or ``cobol/MAIN.cob`` uploads ran the
    oracle on the workspace root, which has no top-level module, so every
    such run ended "No COBOL source file found" and UNAVAILABLE.
    """

    def test_top_level_modules_keep_root(self, tmp_path: Path) -> None:
        _write_multi(tmp_path)
        (tmp_path / "nested").mkdir()
        (tmp_path / "nested" / "OTHER.cob").write_text(HELLO_COB, encoding="utf-8")
        assert DockerOracleAdapter.module_directory(tmp_path) == (tmp_path, [])

    def test_single_nested_directory_is_used(self, tmp_path: Path) -> None:
        app = tmp_path / "cobol"
        app.mkdir()
        _write_multi(app)
        (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
        assert DockerOracleAdapter.module_directory(tmp_path) == (app, [])
        assert DockerOracleAdapter.select_modules(app) == ("MAIN.cob", ["CLAIMS.cob"])

    def test_nested_copybook_cbl_is_not_a_program(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "HELLO.cob").write_text(HELLO_COB, encoding="utf-8")
        (tmp_path / "copy").mkdir()
        (tmp_path / "copy" / "REC.cbl").write_text(COMMON_CPY, encoding="utf-8")
        assert DockerOracleAdapter.module_directory(tmp_path) == (tmp_path / "src", [])

    def test_programs_in_several_directories_are_refused(self, tmp_path: Path) -> None:
        for name in ("a", "b"):
            (tmp_path / name).mkdir()
            (tmp_path / name / "HELLO.cob").write_text(HELLO_COB, encoding="utf-8")
        assert DockerOracleAdapter.module_directory(tmp_path) == (
            None, ["a/HELLO.cob", "b/HELLO.cob"],
        )

    def test_copybook_dirs_lists_sibling_directories(self, tmp_path: Path) -> None:
        (tmp_path / "cobol").mkdir()
        (tmp_path / "copy").mkdir()
        (tmp_path / "cobol" / "MAIN.cob").write_text(MAIN_COB, encoding="utf-8")
        (tmp_path / "copy" / "COMMON.cpy").write_text(COMMON_CPY, encoding="utf-8")
        (tmp_path / "README.md").write_text("demo", encoding="utf-8")
        assert DockerOracleAdapter.copybook_dirs(tmp_path, tmp_path / "cobol") == [".", "copy"]

    def test_flat_layout_adds_no_include_dirs(self, tmp_path: Path) -> None:
        _write_multi(tmp_path)
        assert DockerOracleAdapter.copybook_dirs(tmp_path, tmp_path) == []

    def test_no_programs_keeps_root(self, tmp_path: Path) -> None:
        (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
        assert DockerOracleAdapter.module_directory(tmp_path) == (tmp_path, [])


# ---------------------------------------------------------------------------
# Docker-gated: real multi-program oracle execution
# ---------------------------------------------------------------------------

from tests.docker_probe import docker_daemon_available as _docker_available


needs_docker = pytest.mark.skipif(
    not _docker_available(), reason="Docker not available"
)


def _make_adapter() -> DockerOracleAdapter:
    from engine.oracle.adapter import OracleAdapterConfig
    return DockerOracleAdapter(OracleAdapterConfig(
        oracle_id="gnucobol-3.1.2",
        image_digest="",
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

    def test_nested_upload_layout_runs(self, tmp_path: Path) -> None:
        from engine.domain.identities import RunId

        app = tmp_path / "my app"
        app.mkdir()
        _write_multi(app)
        (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
        outcome = _make_adapter().execute(RunId(value="run-ora-nested"), str(tmp_path))

        assert outcome.exit_code == 0, outcome.stderr.decode(errors="replace")[:500]
        assert outcome.stdout.decode(errors="replace").splitlines() == EXPECTED_CHAIN

    def test_nested_copybooks_in_sibling_directory_resolve(self, tmp_path: Path) -> None:
        # Audit V9: app/cobol + app/copy - generation found COMMON.cpy, the
        # oracle (cd app/cobol, no -I) did not, so the run was UNAVAILABLE.
        from engine.domain.identities import RunId

        (tmp_path / "app" / "cobol").mkdir(parents=True)
        (tmp_path / "app" / "copy").mkdir()
        (tmp_path / "app" / "cobol" / "MAIN.cob").write_text(MAIN_COB, encoding="utf-8")
        (tmp_path / "app" / "cobol" / "CLAIMS.cob").write_text(CLAIMS_COB, encoding="utf-8")
        (tmp_path / "app" / "copy" / "COMMON.cpy").write_text(COMMON_CPY, encoding="utf-8")
        outcome = _make_adapter().execute(RunId(value="run-ora-copy-dir"), str(tmp_path))

        assert outcome.exit_code == 0, outcome.stderr.decode(errors="replace")[:500]
        assert outcome.stdout.decode(errors="replace").splitlines() == EXPECTED_CHAIN

    def test_spread_programs_fail_closed(self, tmp_path: Path) -> None:
        from engine.domain.identities import RunId

        for name in ("a", "b"):
            (tmp_path / name).mkdir()
            (tmp_path / name / "HELLO.cob").write_text(HELLO_COB, encoding="utf-8")
        outcome = _make_adapter().execute(RunId(value="run-ora-spread"), str(tmp_path))

        assert outcome.exit_code is None
        assert outcome.stdout == b""
        assert b"span several directories" in outcome.stderr

    def test_nested_return_code_is_compared_not_error(self, tmp_path: Path) -> None:
        # A nonzero exit reads the modules back to look for RETURN-CODE; in a
        # nested layout they live under the module directory, and reading
        # src/<name> raised, turning a real program exit into "error".
        from engine.domain.identities import RunId

        app = tmp_path / "app"
        app.mkdir()
        (app / "RC.cob").write_text(
            HELLO_COB.replace("PROGRAM-ID. HELLO.", "PROGRAM-ID. RC.").replace(
                "           STOP RUN.\n",
                "           MOVE 3 TO RETURN-CODE.\n           STOP RUN.\n",
            ),
            encoding="utf-8",
        )
        outcome = _make_adapter().execute(RunId(value="run-ora-nested-rc"), str(tmp_path))

        assert outcome.exit_code == 3, outcome.stderr.decode(errors="replace")[:500]
        assert outcome.termination_status != "error"
        assert outcome.stdout.decode(errors="replace").splitlines() == ["HELLO-ORACLE"]

    def test_nested_compile_failure_keeps_diagnostics(self, tmp_path: Path) -> None:
        from engine.domain.identities import RunId

        app = tmp_path / "app"
        app.mkdir()
        (app / "BAD.cob").write_text(
            HELLO_COB.replace("PROGRAM-ID. HELLO.", "PROGRAM-ID. BAD.").replace(
                'DISPLAY "HELLO-ORACLE".', "DISPLAY UNDECLARED-ITEM."
            ),
            encoding="utf-8",
        )
        outcome = _make_adapter().execute(RunId(value="run-ora-nested-bad"), str(tmp_path))

        assert outcome.exit_code not in (0, None)
        assert outcome.termination_status != "error"
        assert outcome.compilation_diagnostics.get("exit_code") not in (None, "0")

    def test_oracle_independent_from_java(self, tmp_path: Path) -> None:
        from engine.domain.identities import RunId

        _write_multi(tmp_path)
        assert not list(tmp_path.rglob("*.java"))
        assert not list(tmp_path.rglob("*.jar"))

        outcome = _make_adapter().execute(RunId(value="run-ora-indep"), str(tmp_path))

        assert outcome.exit_code == 0
        assert outcome.oracle_id == "gnucobol-3.1.2"
        assert outcome.stdout.decode(errors="replace").splitlines() == EXPECTED_CHAIN
