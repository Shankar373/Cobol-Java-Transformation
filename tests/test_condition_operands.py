"""Condition operands: signed literals, ZERO, sign conditions (Phase 3, increment 7).

Found while building the binary-values application (increment 4), then
audited form by form:

* ``WS-N IS NEGATIVE`` / ``IS POSITIVE`` were classified SUPPORTED but the
  parser read them as a condition-name and the Java compared with the
  undeclared name ``NEGATIVE`` (did not compile); ``IS NOT NEGATIVE`` was
  refused.  Sign conditions are now relations to ZERO
  (``engine/transformation/sign_conditions.py``).
* Signed and decimal literals (``> -1``, ``= +3``, ``< -1.25``, ``< 1.25``)
  were refused by the mapper's operand matcher.
* Any program comparing with ZERO/ZEROS/ZEROES was UNKNOWN: the analyzer's
  figurative walk never entered a Comparison (a Condition, not an
  Expression).
* ``A = ZERO`` on a PIC X item compares every character with '0'.

Every result below is GnuCOBOL 3.1.2's (Docker test), and the generated
Java must print the same.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from engine.modernization.capability_analyzer import CapabilityAnalyzer, CapabilityLevel
from engine.transformation.cobol_parser import CobolParser
from engine.transformation.ir import CobolApplication, CobolProgramUnit
from engine.transformation.producer import TransformationProducer
from engine.transformation.sign_conditions import rewrite_sign_conditions

ORACLE_IMAGE = "gnucobol-ocesql:latest"

#: (tag, condition, GnuCOBOL 3.1.2 truth); "--" is a MOVE -0 TO WS-Z step.
CASES = [
    ("A1", "WS-N > -1", "F"), ("A2", "WS-N < -2", "T"), ("A3", "-5 < WS-N", "T"),
    ("A4", "WS-N = -3", "T"), ("A5", "WS-U = +0", "T"), ("A6", "WS-D < -1.25", "T"),
    ("A7", "WS-D = -1.5", "T"), ("B1", "WS-N > ZERO", "F"), ("B2", "WS-U = ZERO", "T"),
    ("B3", "WS-U = ZEROS", "T"), ("B4", "WS-N NOT = ZEROES", "T"),
    ("B5", "WS-D < ZERO", "T"), ("B6", "WS-A = ZERO", "T"), ("B7", "WS-B = ZERO", "F"),
    ("C1", "WS-N IS NEGATIVE", "T"), ("C2", "WS-N IS POSITIVE", "F"),
    ("C3", "WS-U IS ZERO", "T"), ("C4", "WS-U IS POSITIVE", "F"),
    ("C5", "WS-N IS NOT NEGATIVE", "F"), ("C6", "WS-D IS NEGATIVE", "T"),
    ("C7", "WS-Z IS ZERO", "T"), ("C8", "WS-Z IS NOT POSITIVE", "T"),
    ("--", "MOVE", ""), ("C9", "WS-Z IS NEGATIVE", "F"), ("C10", "WS-Z IS ZERO", "T"),
    ("D1", "WS-N > -1 AND WS-U = ZERO", "F"),
    ("D2", "WS-N < 0 OR WS-D IS POSITIVE", "T"),
    ("D3", "WS-D > -2 AND WS-D < -1", "T"),
]


def _program() -> str:
    lines = [
        "       IDENTIFICATION DIVISION.",
        "       PROGRAM-ID. CONDS.",
        "       DATA DIVISION.",
        "       WORKING-STORAGE SECTION.",
        "       01  WS-N    PIC S9(4) VALUE -3.",
        "       01  WS-U    PIC 9(4) VALUE 0.",
        "       01  WS-D    PIC S9(3)V99 VALUE -1.50.",
        "       01  WS-Z    PIC S9(3)V99 VALUE 0.",
        "       01  WS-A    PIC X(4) VALUE '0000'.",
        "       01  WS-B    PIC X(4) VALUE '00 0'.",
        "       PROCEDURE DIVISION.",
        "       MAIN-LOGIC.",
    ]
    for tag, condition, _ in CASES:
        if tag == "--":
            lines.append("           MOVE -0 TO WS-Z")
            continue
        lines += [
            f"           IF {condition}",
            f"               DISPLAY '{tag} T'",
            "           ELSE",
            f"               DISPLAY '{tag} F'",
            "           END-IF",
        ]
    lines.append("           STOP RUN.")
    return "\n".join(lines) + "\n"


SOURCE = _program()
EXPECTED = "".join(f"{tag} {truth}\n" for tag, _, truth in CASES if tag != "--")


def _level(source: str) -> tuple[CapabilityLevel, str]:
    unit = CobolProgramUnit(program_id="C", source_path="C.cob",
                            program=CobolParser().parse(source), source_text=source)
    report = CapabilityAnalyzer(docker_available=True).analyze(
        CobolApplication(application_id="T", programs=(unit,)))
    program = next(c for c in report.components if c.component_type == "PROGRAM")
    return program.level, program.reason


class TestSignConditionRewrite:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("WS-N IS NEGATIVE", "WS-N < ZERO"),
            ("WS-N IS NOT NEGATIVE", "WS-N >= ZERO"),
            ("WS-N POSITIVE", "WS-N > ZERO"),
            ("WS-N IS NOT POSITIVE", "WS-N <= ZERO"),
            ("WS-N IS ZERO", "WS-N = ZERO"),
            ("WS-N IS NOT ZERO", "WS-N NOT = ZERO"),
            ("T(I) IS POSITIVE", "T(I) > ZERO"),
            ("A < 0 OR B IS POSITIVE", "A < 0 OR B > ZERO"),
        ],
    )
    def test_rewrites(self, text: str, expected: str) -> None:
        assert rewrite_sign_conditions(text) == expected

    @pytest.mark.parametrize(
        "text",
        ["WS-U = ZERO", "WS-N NOT = ZEROES", "A = 1 OR ZERO", "WS-A = 'X IS ZERO'"],
    )
    def test_relations_and_literals_are_left_alone(self, text: str) -> None:
        assert rewrite_sign_conditions(text) == text


class TestClassificationAndLowering:
    def test_probe_program_is_supported(self) -> None:
        level, reason = _level(SOURCE)
        assert level is CapabilityLevel.SUPPORTED, reason

    def test_sign_condition_never_reaches_java_as_a_name(self) -> None:
        result = TransformationProducer().transform(SOURCE, "CONDS")
        assert result.success is True, result.errors
        java = result.generated_files[0].source_code
        for word in ("NEGATIVE", "POSITIVE", '"+'):
            assert word not in java, word

    def test_comparison_with_zero_is_not_unknown(self) -> None:
        source = SOURCE.replace("           IF WS-N > -1\n", "           IF WS-U = ZERO\n", 1)
        assert _level(source)[0] is CapabilityLevel.SUPPORTED

    @pytest.mark.parametrize(
        "condition",
        [
            "WS-A > ZERO",       # ordering against an alphanumeric ZERO fill
            "WS-N = 1 OR 2",     # abbreviated combined relation
        ],
    )
    def test_uncertified_forms_fail_closed(self, condition: str) -> None:
        source = SOURCE.replace("           IF WS-N > -1\n", f"           IF {condition}\n", 1)
        assert TransformationProducer().transform(source, "CONDS").success is False


def test_generated_java_matches_oracle(tmp_path: Path) -> None:
    if not (shutil.which("javac") and shutil.which("java")):
        if os.environ.get("RUN_DOCKER_TESTS") == "1":
            pytest.fail("javac/java not on PATH: the Docker lane requires a JDK")
        pytest.skip("javac/java not on PATH")
    result = TransformationProducer().transform(SOURCE, "CONDS")
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
    assert run.returncode == 0, run.stderr.decode(errors="replace")
    assert run.stdout.decode() == EXPECTED


def test_oracle_pins(tmp_path: Path) -> None:
    if os.environ.get("RUN_DOCKER_TESTS") != "1":
        pytest.skip("Docker lane test: set RUN_DOCKER_TESTS=1 to run it")
    (tmp_path / "CONDS.cob").write_text(SOURCE, encoding="utf-8")
    os.chmod(tmp_path, 0o777)
    run = subprocess.run(
        ["docker", "run", "--rm", "--network", "none", "-v", f"{tmp_path}:/src",
         ORACLE_IMAGE, "sh", "-c", "cd /tmp && cobc -x /src/CONDS.cob -o c && ./c"],
        capture_output=True, timeout=300,
    )
    assert run.returncode == 0, run.stderr.decode(errors="replace")
    assert run.stdout.decode() == EXPECTED
