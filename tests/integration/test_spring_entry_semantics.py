"""Spring Boot application entry = COBOL run-unit entry (oracle-backed).

The generated Spring Boot runner used to call the entry service's first
method, i.e. only the driver paragraph: paragraph fall-through was lost and
EXIT PROGRAM in the entry program returned early.  Every program now exposes
``RUN_UNIT$ENTRY`` (driver paragraph lowered as for a program that was not
CALLed, then its fall-through chain) and the runner calls that.

The Docker classes build each generated project with Maven, run the JAR and
run the same sources on GnuCOBOL 3.1.2 with the same entry program; stdout
and exit status must be identical, and equal to the pinned oracle output.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from engine.transformation.control_flow import RUN_UNIT_ENTRY_METHOD

SPRING_ENTRY = "com.generated.app.Application"


def _cob(program_id: str, procedure: str, data: str = "", linkage: str = "",
         using: str = "") -> str:
    text = (
        "       IDENTIFICATION DIVISION.\n"
        f"       PROGRAM-ID. {program_id}.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01 WS-C PIC 9(3) VALUE 0.\n"
        f"{data}"
    )
    if linkage:
        text += "       LINKAGE SECTION.\n" + linkage
    text += f"       PROCEDURE DIVISION{(' USING ' + using) if using else ''}.\n"
    return text + procedure


# name -> (entry program, {file: source}, oracle stdout)
CASES: dict[str, tuple[str, dict[str, str], str]] = {
    "fall_through_chain": (
        "FALL",
        {"FALL.cob": _cob("FALL", (
            "       P1.\n           DISPLAY 'A'.\n"
            "       P2.\n           DISPLAY 'B'.\n"
            "       P3.\n           DISPLAY 'C'.\n           STOP RUN.\n"
        ))},
        "A\nB\nC\n",
    ),
    "fall_through_after_perform": (
        "FALLP",
        {"FALLP.cob": _cob("FALLP", (
            "       P1.\n           PERFORM P2.\n"
            "       P2.\n           ADD 1 TO WS-C.\n           DISPLAY WS-C.\n"
            "       P3.\n           DISPLAY 'END'.\n           STOP RUN.\n"
        ))},
        "001\n002\nEND\n",
    ),
    "exit_program_in_entry_program_is_no_op": (
        "EXITP",
        {"EXITP.cob": _cob("EXITP", (
            "       P1.\n           DISPLAY 'A'.\n"
            "           IF WS-C = 0\n              EXIT PROGRAM\n           END-IF.\n"
            "           DISPLAY 'B'.\n           STOP RUN.\n"
        ))},
        "A\nB\n",
    ),
    "call_linkage_callee_with_chain_and_exit_program_callee": (
        "DRIVER",
        {
            "DRIVER.cob": _cob("DRIVER", (
                "       D1.\n           DISPLAY 'M1'.\n"
                "           CALL 'SUBLK' USING WS-X.\n"
                "           CALL 'SUBEX'.\n"
                "           DISPLAY WS-X.\n"
                "       D2.\n           DISPLAY 'M2'.\n           STOP RUN.\n"
            ), data="       01 WS-X PIC X(3) VALUE 'ZZZ'.\n"),
            "SUBLK.cob": _cob("SUBLK", (
                "       S1.\n           MOVE 'ABC' TO LK-X.\n           DISPLAY 'S1'.\n"
                "       S2.\n           DISPLAY 'S2'.\n           GOBACK.\n"
            ), linkage="       01 LK-X PIC X(3).\n", using="LK-X"),
            "SUBEX.cob": _cob("SUBEX", (
                "       E1.\n           DISPLAY 'X'.\n"
                "           IF WS-C = 0\n              EXIT PROGRAM\n           END-IF.\n"
                "           DISPLAY 'NOT-REACHED'.\n           GOBACK.\n"
            )),
        },
        "M1\nS1\nS2\nX\nABC\nM2\n",
    ),
}


def _spring_project(src: Path, entry: str, out: Path) -> Path:
    from engine.transformation.application_discovery import ApplicationDiscovery
    from engine.transformation.cobol_to_java_mapping import (
        map_cobol_programs_to_application,
    )
    from engine.transformation.java_to_spring_mapping import (
        map_java_application_to_spring_boot,
    )
    from engine.transformation.spring_boot_generator import SpringBootGenerator

    discovered = ApplicationDiscovery().discover(str(src), application_id="entry-app")
    programs = tuple(u.program for u in discovered.programs if u.program is not None)
    java_app = map_cobol_programs_to_application(
        programs=programs,
        application_id=discovered.application_id,
        copybooks=discovered.copybooks,
        edges=discovered.edges,
    )
    spring_app = map_java_application_to_spring_boot(java_app, entry_program=entry)
    assert spring_app.validate() == []
    for f in SpringBootGenerator().generate_project(spring_app):
        target = out / Path(*(Path(f.path or f.filename).parts))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f.source_code, encoding="utf-8")
    return out


def _write_case(tmp_path: Path, name: str) -> tuple[str, Path, str]:
    entry, files, expected = CASES[name]
    src = tmp_path / "src"
    src.mkdir()
    for fname, text in files.items():
        (src / fname).write_text(text, encoding="utf-8")
    return entry, src, expected


def _entry_source(project: Path) -> str:
    return (project / "src/main/java/com/generated/app/Application.java").read_text(
        encoding="utf-8"
    )


@pytest.mark.parametrize("name", sorted(CASES))
def test_runner_enters_run_unit_entry(tmp_path: Path, name: str) -> None:
    entry, src, _ = _write_case(tmp_path, name)
    project = _spring_project(src, entry, tmp_path / "gen")
    field = entry[0].lower() + entry[1:].lower()
    assert f"{field}.{RUN_UNIT_ENTRY_METHOD}();" in _entry_source(project)


from tests.docker_probe import docker_daemon_available as _docker_available


@pytest.mark.skipif(not _docker_available(), reason="Docker not available")
@pytest.mark.parametrize("name", sorted(CASES))
def test_spring_app_matches_gnucobol(tmp_path: Path, name: str) -> None:
    from engine.candidate.adapter import CandidateManifest
    from engine.candidate.docker_spring_boot_adapter import (
        DockerSpringBootCandidateAdapter,
    )
    from engine.domain.identities import RunId
    from engine.oracle.adapter import OracleAdapterConfig
    from engine.oracle.docker_adapter import DockerOracleAdapter

    entry, src, expected = _write_case(tmp_path, name)

    oracle = DockerOracleAdapter(OracleAdapterConfig(
        oracle_id="gnucobol-3.1.2",
        image_digest="",
        compiler_version="3.1.2.0",
        timeout_seconds=60,
    )).execute(RunId(value=f"run-{name}"), str(src), entry_program=entry)
    assert oracle.exit_code == 0, oracle.stderr
    assert oracle.stdout.decode() == expected

    project = _spring_project(src, entry, tmp_path / "gen")
    manifest = CandidateManifest(
        candidate_id="entry-app",
        workload_id="wl-entry",
        source_hash="test",
        generated_files={"pom.xml": "test"},
        entrypoint=SPRING_ENTRY,
    )
    adapter = DockerSpringBootCandidateAdapter()
    compilation = adapter.compile(str(project), manifest)
    assert compilation.success, compilation.compilation_errors
    candidate = adapter.execute(RunId(value=f"run-{name}"), str(project), manifest)

    assert candidate.stdout == oracle.stdout
    assert candidate.exit_code == oracle.exit_code
