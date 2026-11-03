"""RETURN-CODE special register and program exit status (Phase 3).

GnuCOBOL 3.1.2, observed (pins below; the Docker tests re-derive them):

* RETURN-CODE is a signed register that displays as ``+000000004`` and
  takes part in MOVE / ADD / COMPUTE / IF like a ``PIC S9(9)`` item;
* the process exit status is ``RETURN-CODE & 0xFF`` whether the run unit
  ends with STOP RUN, GOBACK or by falling off the end (300 -> 44,
  -1 -> 255);
* a runtime error is different: ``libcob: error: ...`` on stderr, exit 1.

Previously the register was not modelled (``RETURN_CODE`` was an undeclared
Java name) and every nonzero oracle exit made the verdict UNAVAILABLE, so a
batch program signalling a warning through RETURN-CODE could never verify.

Now the parser declares the register for a program that uses it, the run
unit reports ``RUN_UNIT$EXIT_STATUS()`` and every host exits with it; the
oracle records a nonzero exit as ``return_code`` (program behaviour, compared
exactly through EXIT_STATUS) only when the compile succeeded, the program
uses RETURN-CODE and no libcob runtime error was reported.  A program that
CALLs or is CALLed fails closed: GnuCOBOL hands RETURN-CODE across CALL.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from engine.domain.identities import RunId, VerdictState
from engine.evidence.integrity import EvidenceIntegrityValidator, ViolationType
from engine.oracle.docker_adapter import classify_oracle_termination
from engine.transformation.producer import TransformationProducer
from engine.verdict.derivation import derive_verdict
from tests.verdict.test_j9_mixed_states import _exec, _manifest


def _program(program_id: str, procedure: str, data: str = "") -> str:
    return (
        "       IDENTIFICATION DIVISION.\n"
        f"       PROGRAM-ID. {program_id}.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01 WS-X PIC 9(3) VALUE 7.\n"
        f"{data}"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-PARA.\n"
        f"{procedure}"
    )


# name -> (source, stdout, exit status), all GnuCOBOL 3.1.2 output
CASES: dict[str, tuple[str, str, int]] = {
    "arithmetic_and_wrap": (
        _program("RC1", (
            "           DISPLAY 'RC=' RETURN-CODE.\n"
            "           MOVE 4 TO RETURN-CODE.\n"
            "           DISPLAY 'RC=' RETURN-CODE.\n"
            "           ADD WS-X TO RETURN-CODE.\n"
            "           COMPUTE RETURN-CODE = RETURN-CODE * 2.\n"
            "           DISPLAY 'RC=' RETURN-CODE.\n"
            "           IF RETURN-CODE > 20 DISPLAY 'BIG' END-IF.\n"
            "           MOVE -3 TO RETURN-CODE.\n"
            "           DISPLAY 'RC=' RETURN-CODE.\n"
            "           MOVE 300 TO RETURN-CODE.\n"
            "           STOP RUN.\n"
        )),
        "RC=+000000000\nRC=+000000004\nRC=+000000022\nBIG\nRC=-000000003\n",
        44,
    ),
    "goback": (
        _program("RC2", "           MOVE 8 TO RETURN-CODE.\n           GOBACK.\n"),
        "",
        8,
    ),
    "falls_off_the_end": (
        _program("RC3", "           MOVE 5 TO RETURN-CODE.\n           DISPLAY 'END'.\n"),
        "END\n",
        5,
    ),
    "negative": (
        _program("RC4", "           MOVE -1 TO RETURN-CODE.\n           STOP RUN.\n"),
        "",
        255,
    ),
    "zero_after_use": (
        _program("RC5", "           MOVE 0 TO RETURN-CODE.\n           STOP RUN.\n"),
        "",
        0,
    ),
}


def _transform(source: str, name: str = "PROBE"):
    return TransformationProducer().transform(source, name)


class TestTransformation:
    def test_register_is_declared_and_exit_status_reported(self) -> None:
        result = _transform(CASES["arithmetic_and_wrap"][0])
        assert result.success is True, result.errors
        java = result.generated_files[0].source_code
        assert "RETURN_CODE" in java
        assert "RUN_UNIT$EXIT_STATUS" in java

    def test_program_without_return_code_is_unchanged(self) -> None:
        result = _transform(_program("PLAIN", "           DISPLAY 'X'.\n           STOP RUN.\n"))
        assert result.success is True, result.errors
        java = result.generated_files[0].source_code
        assert "RUN_UNIT$EXIT_STATUS" not in java
        assert "System.exit" not in java

    def test_return_code_with_call_fails_closed(self) -> None:
        source = _program("CALLER", (
            "           CALL 'CALLEE'.\n"
            "           DISPLAY RETURN-CODE.\n"
            "           STOP RUN.\n"
        ))
        result = _transform(source)
        assert result.success is False
        assert any("RETURN-CODE" in e for e in result.errors), result.errors

    def test_return_code_in_called_program_fails_closed(self) -> None:
        source = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. CALLEE.\n"
            "       DATA DIVISION.\n"
            "       LINKAGE SECTION.\n"
            "       01 LK-A PIC 9(3).\n"
            "       PROCEDURE DIVISION USING LK-A.\n"
            "       MAIN-PARA.\n"
            "           MOVE 4 TO RETURN-CODE.\n"
            "           GOBACK.\n"
        )
        result = _transform(source)
        assert result.success is False
        assert any("RETURN-CODE" in e for e in result.errors), result.errors


@pytest.mark.parametrize("name", sorted(CASES))
def test_generated_java_matches_oracle(name: str, tmp_path: Path) -> None:
    if not (shutil.which("javac") and shutil.which("java")):
        if os.environ.get("RUN_DOCKER_TESTS") == "1":
            pytest.fail("javac/java not on PATH: the Docker lane requires a JDK")
        pytest.skip("javac/java not on PATH")
    source, stdout, status = CASES[name]
    result = _transform(source)
    assert result.success is True, result.errors
    for generated in result.generated_files:
        (tmp_path / generated.filename).write_text(generated.source_code, encoding="utf-8")
    compiled = subprocess.run(
        ["javac", "-nowarn", "-d", str(tmp_path),
         *[str(tmp_path / g.filename) for g in result.generated_files]],
        capture_output=True, timeout=120,
    )
    assert compiled.returncode == 0, compiled.stderr.decode(errors="replace")
    run = subprocess.run(
        ["java", "-Dline.separator=\n", "-cp", str(tmp_path),
         result.generated_files[0].class_name],
        capture_output=True, timeout=60, cwd=tmp_path,
    )
    assert run.stdout.decode() == stdout
    assert run.returncode == status, run.stderr.decode(errors="replace")


class TestOracleClassification:
    @pytest.mark.parametrize(
        ("exit_code", "compile_exit", "stderr", "uses_rc", "expected"),
        [
            (0, "0", b"", True, "normal"),
            (0, "0", b"", False, "normal"),
            (44, "0", b"", True, "return_code"),
            (4, "0", b"", False, "nonzero_exit"),  # nothing set a return code
            (1, "0", b"libcob: error: module 'X' not found\n", True, "nonzero_exit"),
            (1, "1", b"P.cob:3: error: syntax\n", True, "nonzero_exit"),  # compile failed
            (1, None, b"", True, "nonzero_exit"),  # no compile record
        ],
    )
    def test_table(self, exit_code, compile_exit, stderr, uses_rc, expected) -> None:
        assert classify_oracle_termination(exit_code, compile_exit, stderr, uses_rc) == expected


def _exit_status_comparison(run_id: RunId, result: str):
    from tests.common import make_hash
    from engine.evidence.models import ComparisonEvidence

    return ComparisonEvidence(
        comparison_id="comp-exit",
        run_id=run_id,
        oracle_artifact_id="art-oracle-exit",
        candidate_artifact_id="art-candidate-exit",
        artifact_type="EXIT_STATUS",
        comparator_id="EXIT_STATUS_COMPARATOR",
        comparator_version="1.0.0",
        result=result,
        normalization_applied=(),
        differences=() if result == "MATCH" else ("exit 44 != 0",),
        field_level_results=(),
        content_hash=make_hash("cmp"),
    )


def _exit_status_artifact(role: str, execution: str):
    from engine.domain.identities import ArtifactIdentity, ExecutionId
    from engine.evidence.models import ArtifactEvidence
    from tests.common import make_hash

    return ArtifactEvidence(
        artifact=ArtifactIdentity(
            artifact_id=f"art-{role.lower()}-exit", artifact_type="EXIT_STATUS",
            logical_name="exit-status", producer_role=role,
            content_hash=make_hash("44"), size_bytes=2,
        ),
        execution_id=ExecutionId(value=execution),
        capture_time="t1",
        content_hash=make_hash("44"),
        size_bytes=2,
    )


class TestVerdict:
    def _manifest(self, oracle_status: str, comparison: str):
        run_id = RunId(value="run-rc")
        oracle = replace(_exec(run_id, "o1", "oracle-gnucobol", oracle_status), exit_code=44)
        candidate = replace(_exec(run_id, "c1", "candidate-java", "nonzero_exit"), exit_code=44)
        manifest = _manifest(
            run_id, [oracle], [candidate], [_exit_status_comparison(run_id, comparison)]
        )
        return replace(manifest, artifact_evidence=(
            _exit_status_artifact("ORACLE", "o1"),
            _exit_status_artifact("CANDIDATE", "c1"),
        ))

    def test_matching_return_code_verifies(self) -> None:
        verdict = derive_verdict(self._manifest("return_code", "MATCH"))
        assert verdict.state == VerdictState.VERIFIED
        assert verdict.unavailable_count == 0

    def test_different_exit_status_fails(self) -> None:
        assert derive_verdict(self._manifest("return_code", "MISMATCH")).state == VerdictState.FAILED

    def test_unexplained_nonzero_oracle_exit_stays_unavailable(self) -> None:
        verdict = derive_verdict(self._manifest("nonzero_exit", "MATCH"))
        assert verdict.state == VerdictState.UNAVAILABLE

    def test_return_code_without_exit_status_comparison_is_an_integrity_violation(self) -> None:
        run_id = RunId(value="run-rc")
        oracle = replace(_exec(run_id, "o1", "oracle-gnucobol", "return_code"), exit_code=4)
        candidate = _exec(run_id, "c1", "candidate-java", "normal")
        violations = EvidenceIntegrityValidator()._validate_exit_status_completeness(
            _manifest(run_id, [oracle], [candidate])
        )
        assert any(v.violation_type == ViolationType.MISSING_EXIT_STATUS for v in violations)


# ---------------------------------------------------------------------------
# Docker lane: the real oracle and a real Spring Boot JAR
# ---------------------------------------------------------------------------

def _docker_lane() -> None:
    if os.environ.get("RUN_DOCKER_TESTS") != "1":
        pytest.skip("Docker lane test: set RUN_DOCKER_TESTS=1 to run it")


def _oracle(src: Path, entry: str):
    from engine.oracle.adapter import OracleAdapterConfig
    from engine.oracle.docker_adapter import DockerOracleAdapter

    return DockerOracleAdapter(OracleAdapterConfig(
        oracle_id="gnucobol-3.1.2", image_digest="", compiler_version="3.1.2.0",
        timeout_seconds=60,
    )).execute(RunId(value=f"run-{entry}"), str(src), entry_program=entry)


@pytest.mark.parametrize("name", sorted(CASES))
def test_oracle_pins_and_classification(name: str, tmp_path: Path) -> None:
    _docker_lane()
    source, stdout, status = CASES[name]
    entry = source.split("PROGRAM-ID. ", 1)[1].split(".", 1)[0]
    (tmp_path / f"{entry}.cob").write_text(source, encoding="utf-8")
    result = _oracle(tmp_path, entry)
    assert result.stdout.decode() == stdout
    assert result.exit_code == status
    assert result.termination_status == ("normal" if status == 0 else "return_code")


def test_oracle_runtime_error_is_not_a_return_code(tmp_path: Path) -> None:
    _docker_lane()
    (tmp_path / "CRASH.cob").write_text(_program("CRASH", (
        "           MOVE 4 TO RETURN-CODE.\n"
        "           CALL 'NOSUCHPROG'.\n"
        "           STOP RUN.\n"
    )), encoding="utf-8")
    result = _oracle(tmp_path, "CRASH")
    assert b"libcob: error" in result.stderr
    assert result.termination_status == "nonzero_exit"


def test_spring_boot_jar_exits_like_gnucobol(tmp_path: Path) -> None:
    _docker_lane()
    from engine.candidate.adapter import CandidateManifest
    from engine.candidate.docker_spring_boot_adapter import DockerSpringBootCandidateAdapter
    from tests.integration.test_spring_entry_semantics import SPRING_ENTRY, _spring_project

    source, stdout, status = CASES["arithmetic_and_wrap"]
    src = tmp_path / "src"
    src.mkdir()
    (src / "RC1.cob").write_text(source, encoding="utf-8")
    oracle = _oracle(src, "RC1")
    assert (oracle.stdout.decode(), oracle.exit_code) == (stdout, status)

    project = _spring_project(src, "RC1", tmp_path / "gen")
    manifest = CandidateManifest(
        candidate_id="rc-app", workload_id="wl-rc", source_hash="test",
        generated_files={"pom.xml": "test"}, entrypoint=SPRING_ENTRY,
    )
    adapter = DockerSpringBootCandidateAdapter()
    compilation = adapter.compile(str(project), manifest)
    assert compilation.success, compilation.compilation_errors
    candidate = adapter.execute(RunId(value="run-rc-spring"), str(project), manifest)
    assert candidate.stdout == oracle.stdout
    assert candidate.exit_code == oracle.exit_code == 44
