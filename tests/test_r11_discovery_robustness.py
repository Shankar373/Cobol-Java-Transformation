"""R11 discovery robustness regression tests (E-C).

Covers:
- sibling ``jcl/`` tree is visible to ingestion discovery
- uppercase source extensions (``.COB``/``.CBL``/``.JCL``) are discovered
- nested ``cobol/`` source root with ``COPY`` resolves on disk
"""

from pathlib import Path

from engine.transformation.application_discovery import ApplicationDiscovery
from engine.transformation.jcl_discovery import JclDiscovery


_MAIN = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MAINPROG.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO "IN.DAT"
               ORGANIZATION IS LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-REC   PIC X(80).
       COPY CUSTREC.
       PROCEDURE DIVISION.
           OPEN INPUT IN-FILE.
           READ IN-FILE.
           CLOSE IN-FILE.
           STOP RUN.
"""

_CPY = "      01  WS-DATE    PIC 9(8).\n"

_JCL = """//MYJOB    JOB (ACCT),'TEST'
//STEP1    EXEC PGM=MAINPROG
//IN.DD    DD DSN=TEST.DATA,DISP=SHR
"""


def _tree(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    (root / "cobol").mkdir(parents=True)
    (root / "copybooks").mkdir(parents=True)
    (root / "jcl").mkdir(parents=True)
    (root / "cobol" / "MAIN.COB").write_text(_MAIN)
    (root / "copybooks" / "CUSTREC.cpy").write_text(_CPY)
    (root / "jcl" / "JOB1.JCL").write_text(_JCL)
    return root


def test_discovery_from_workspace_root_finds_uppercase_cobol(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    app = ApplicationDiscovery().discover(root, application_id="r11")
    program_ids = {p.program_id for p in app.programs}
    assert "MAINPROG" in program_ids


def test_sibling_jcl_tree_visible_from_workspace_root(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    jcl_app = JclDiscovery().discover(root)
    assert any(j.name == "MYJOB" for j in jcl_app.jobs)


def test_nested_copy_resolves_via_workspace_root_dirs(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    app = ApplicationDiscovery().discover(root, application_id="r11")
    assert app.copybooks == ("CUSTREC",)
    unit = next(p for p in app.programs if p.program_id == "MAINPROG")
    assert unit.copybooks and unit.copybooks[0].copybook_name == "CUSTREC"


def test_uppercase_cobol_fixture_still_parses(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    app = ApplicationDiscovery().discover(root)
    unit = next(p for p in app.programs if p.program_id == "MAINPROG")
    assert not unit.parse_error
