"""ASSIGN clause spellings bind the file (audit P0-1, oracle-pinned).

The SELECT parser used to recognise only ``ASSIGN TO "name"`` with double
quotes on the SELECT's own line.  ``ASSIGN TO 'name'``, ``ASSIGN 'name'``
and a literal continued on the next line left the file without a path, and
every OPEN/CLOSE became a comment while READ inlined its NOT AT END body —
the program "succeeded" without touching a file.

Every spelling must now generate exactly the reference (double-quoted)
Java, and an ASSIGN that names no literal file (data name, device word) is
refused instead of being treated as a console.  The stdout pin is GnuCOBOL
3.1.2 output; the Docker lane re-derives it for every spelling.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from engine.transformation.producer import TransformationProducer

ORACLE_IMAGE = "gnucobol-ocesql:latest"

_TEMPLATE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROBE.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
{select}
               ORGANIZATION IS LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  DATA-FILE.
       01  DATA-REC PIC X(8).
       WORKING-STORAGE SECTION.
       01 WS-EOF PIC X VALUE "N".
       01 WS-N PIC 9 VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN OUTPUT DATA-FILE.
           MOVE "ALPHA" TO DATA-REC.
           WRITE DATA-REC.
           MOVE "BETA" TO DATA-REC.
           WRITE DATA-REC.
           CLOSE DATA-FILE.
           OPEN INPUT DATA-FILE.
           PERFORM UNTIL WS-EOF = "Y"
               READ DATA-FILE
                   AT END MOVE "Y" TO WS-EOF
                   NOT AT END
                       ADD 1 TO WS-N
                       DISPLAY "[" DATA-REC "]"
               END-READ
           END-PERFORM.
           CLOSE DATA-FILE.
           DISPLAY "N=" WS-N.
           STOP RUN.
"""

REFERENCE = '           SELECT DATA-FILE ASSIGN TO "AS.DAT"'
SPELLINGS = {
    "single_quotes": "           SELECT DATA-FILE ASSIGN TO 'AS.DAT'",
    "without_to": '           SELECT DATA-FILE ASSIGN "AS.DAT"',
    "literal_on_next_line": '           SELECT DATA-FILE ASSIGN TO\n               "AS.DAT"',
    "assign_on_next_line": "           SELECT DATA-FILE\n               ASSIGN TO 'AS.DAT'",
}
EXPECTED_STDOUT = "[ALPHA   ]\n[BETA    ]\nN=2\n"


def _source(select: str, *, data_name: str = "") -> str:
    """The probe program; ``data_name`` declares a WORKING-STORAGE item of that name."""
    source = _TEMPLATE.format(select=select)
    if data_name:
        source = source.replace(
            "       PROCEDURE DIVISION.",
            f"       01 {data_name} PIC X(20).\n       PROCEDURE DIVISION.",
        )
    return source


def _transform(source: str):
    return TransformationProducer().transform(source, "PROBE")


def _java(source: str) -> str:
    result = _transform(source)
    assert result.success is True, result.errors
    return result.generated_files[0].source_code


def test_reference_spelling_performs_real_file_io() -> None:
    java = _java(_source(REFERENCE))
    assert 'CobolFileIo.open("AS.DAT", "OUTPUT"' in java
    assert 'CobolFileIo.readNext("AS.DAT")' in java
    assert "no file path" not in java


@pytest.mark.parametrize("name", sorted(SPELLINGS))
def test_every_spelling_generates_the_reference_java(name: str) -> None:
    assert _java(_source(SPELLINGS[name])) == _java(_source(REFERENCE))


@pytest.mark.parametrize("target", ["WS-FILE-NAME", "DISK", "KEYBOARD"])
def test_non_literal_assign_fails_closed(target: str) -> None:
    # WS-FILE-NAME is declared, so GnuCOBOL reads it as a variable file name (dynamic
    # assignment); DISK and KEYBOARD are device words. None is a plain ddname.
    result = _transform(_source(f"           SELECT DATA-FILE ASSIGN TO {target}", data_name=target))
    assert result.success is False
    assert any("DATA-FILE" in e and "ASSIGN" in e for e in result.errors), result.errors


def test_read_without_a_file_path_fails_closed() -> None:
    # A console-style literal (no real file behind it) must not let READ
    # "succeed" by running its NOT AT END body unconditionally.
    result = _transform(_source('           SELECT DATA-FILE ASSIGN TO "SYSOUT"'))
    assert result.success is False
    assert any("READ" in e for e in result.errors), result.errors


@pytest.mark.parametrize("name", ["reference", *sorted(SPELLINGS)])
def test_oracle_pin_matches_gnucobol(name: str, tmp_path: Path) -> None:
    """Docker lane: GnuCOBOL accepts every spelling and prints the pin."""
    if os.environ.get("RUN_DOCKER_TESTS") != "1":
        pytest.skip("Docker lane test: set RUN_DOCKER_TESTS=1 to run it")
    select = REFERENCE if name == "reference" else SPELLINGS[name]
    (tmp_path / "P.cob").write_text(_source(select), encoding="utf-8", newline="\n")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    os.chmod(run_dir, 0o777)
    run = subprocess.run(
        ["docker", "run", "--rm", "--network", "none",
         "-v", f"{tmp_path}:/src", ORACLE_IMAGE, "sh", "-c",
         "cobc -x /src/P.cob -o /tmp/p && cd /src/run && /tmp/p"],
        capture_output=True, timeout=180,
    )
    assert run.returncode == 0, run.stderr.decode(errors="replace")
    assert run.stdout.decode() == EXPECTED_STDOUT
    assert (run_dir / "AS.DAT").read_bytes() == b"ALPHA\nBETA\n"


# The API path (capability analysis, plan, generation) must agree with the
# producer: a literal spelling generates, a non-literal ASSIGN never does.

def _pipeline(select: str, tmp_path: Path, *, data_name: str = ""):
    from engine.modernization.pipeline import (
        ModernizationConfig,
        UniversalModernizationPipeline,
    )

    src = tmp_path / "src"
    src.mkdir()
    (src / "PROBE.cob").write_text(_source(select, data_name=data_name), encoding="utf-8")
    return UniversalModernizationPipeline(
        ModernizationConfig(
            source_dir=str(src),
            output_dir=str(tmp_path / "out"),
            application_id="assign-probe",
            entrypoint="PROBE",
            docker_available=True,
        )
    ).execute()


@pytest.mark.parametrize("name", sorted(SPELLINGS))
def test_pipeline_generates_every_literal_spelling(name: str, tmp_path: Path) -> None:
    report = _pipeline(SPELLINGS[name], tmp_path)
    assert report.generation_success is True, report.generation_errors
    project = Path(report.generated_project_dir)
    java = "\n".join(p.read_text(encoding="utf-8") for p in project.rglob("*.java"))
    assert 'CobolFileIo.readNext("AS.DAT")' in java


def test_pipeline_refuses_non_literal_assign(tmp_path: Path) -> None:
    report = _pipeline("           SELECT DATA-FILE ASSIGN TO WS-FILE-NAME", tmp_path, data_name="WS-FILE-NAME")
    assert report.generation_success is False
    project = report.generated_project_dir
    assert not project or not list(Path(project).rglob("*.java"))


def test_pipeline_refuses_output_with_fail_closed_symbols(tmp_path: Path) -> None:
    # The producer refuses Java carrying UNSUPPORTED_*$ symbols; the API's
    # generation path must refuse the same output and leave no project.
    report = _pipeline('           SELECT DATA-FILE ASSIGN TO "SYSOUT"', tmp_path)
    assert report.generation_success is False
    assert any("UNSUPPORTED_FILE$READ$DATA_FILE" in e for e in report.generation_errors), (
        report.generation_errors
    )
    assert report.generated_project_dir == ""


def test_an_undeclared_name_is_a_ddname_not_a_refusal() -> None:
    # No data item of that name exists, so libcob resolves it from the environment
    # (DD_<name>) exactly like any other ddname (tests/integration/test_ddname_oracle.py).
    result = _transform(_source("           SELECT DATA-FILE ASSIGN TO WS-FILE-NAME"))
    assert result.success is True, result.errors
    assert 'CobolFileIo.open("WS-FILE-NAME"' in result.generated_files[0].source_code
