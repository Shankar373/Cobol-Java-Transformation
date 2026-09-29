"""Focused fixed-point numeric semantic contract tests."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest

from engine.candidate.docker_java_adapter import DockerJavaCandidateAdapter
from engine.candidate.docker_spring_boot_adapter import CandidateManifest
from engine.domain.identities import RunId
from engine.oracle.adapter import OracleAdapterConfig
from engine.oracle.docker_adapter import DockerOracleAdapter
from engine.transformation.cobol_parser import CobolParser
from engine.transformation.cobol_to_java_mapping import map_cobol_program_to_java
from engine.transformation.java_generator import JavaGenerator


COBOL = """>>SOURCE FORMAT FREE
IDENTIFICATION DIVISION.
PROGRAM-ID. NUMERIC-DEMO.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-A PIC 9(3)V99 VALUE 123.45.
01 WS-B PIC 9(3)V99 VALUE 2.00.
01 WS-C PIC 9(3)V99 VALUE 0.
PROCEDURE DIVISION.
MAIN.
    ADD WS-A TO WS-B GIVING WS-C.
    DISPLAY WS-C.
    STOP RUN.
"""


def _parse():
    return CobolParser().parse(COBOL)


def test_parser_and_ir_preserve_fixed_point_scale():
    program = _parse()
    items = {item.name: item for item in program.working_storage}
    assert items["WS-A"].decimal_places == 2
    assert items["WS-A"].pic_length == 5
    assert items["WS-A"].value == "123.45"
    assert items["WS-B"].value == "2.00"

    from engine.transformation.ir import bind_program_semantics
    bound = bind_program_semantics(program)
    add = bound.paragraphs[0].statements[0]
    assert add.source_expr is not None
    assert add.source_expr.semantic_type is not None
    assert add.source_expr.semantic_type.decimal_places == 2


def test_mapping_preserves_bigdecimal_and_scale():
    java = map_cobol_program_to_java(_parse())
    fields = {field.name: field for field in java.java_class.fields}
    assert fields["WS_A"].java_type.class_name == "BigDecimal"
    assert fields["WS_A"].decimal_places == 2

    assignment = next(
        stmt for method in java.java_class.methods
        for stmt in method.body_statements
        if getattr(stmt, "target", "") == "WS_C"
    )
    assert getattr(assignment.expression, "method_name", "") == "setScale"
    assert assignment.expression.arguments[1].name == "RoundingMode.DOWN"


def test_generated_java_uses_exact_fixed_point_operations():
    generated = JavaGenerator().generate(_parse())[0].source_code
    assert "import java.math.BigDecimal;" in generated
    assert "import java.math.RoundingMode;" in generated
    assert ".add(" in generated
    assert ".setScale(2, RoundingMode.DOWN)" in generated
    assert "longValueExact()" in generated
    assert 'String.format("%05d"' in generated


@pytest.mark.skipif(not shutil.which("docker"), reason="Docker unavailable")
def test_oracle_and_generated_java_match_fixed_point_behavior(tmp_path: Path):
    oracle = DockerOracleAdapter(OracleAdapterConfig(
        oracle_id="numeric-contract-probe",
        image_digest=DockerOracleAdapter.V1_DIGEST,
        compiler_version="3.1.2.0",
    ))
    if oracle.probe().value == "UNAVAILABLE":
        pytest.skip("GnuCOBOL oracle image unavailable")

    program = _parse()
    generated = JavaGenerator().generate(program)[0]

    cobol_dir = tmp_path / "cobol"
    cobol_dir.mkdir()
    (cobol_dir / "NUMERIC-DEMO.cob").write_text(COBOL, encoding="utf-8")

    java_dir = tmp_path / "java"
    java_dir.mkdir()
    (java_dir / generated.filename).write_text(generated.source_code, encoding="utf-8")

    manifest = CandidateManifest(
        candidate_id="numeric-contract",
        workload_id="numeric-contract",
        source_hash=hashlib.sha256(COBOL.encode()).hexdigest(),
        generated_files={generated.filename: hashlib.sha256(generated.source_code.encode()).hexdigest()},
        entrypoint=generated.class_name,
    )
    candidate = DockerJavaCandidateAdapter()
    if not candidate.available:
        pytest.skip("Docker Java candidate image unavailable")

    run_id = RunId(value="numeric-contract")
    compiled = candidate.compile(str(java_dir), manifest)
    assert compiled.success, compiled.compilation_errors
    candidate_result = candidate.execute(run_id, str(java_dir), manifest)
    candidate_stdout = candidate_result.stdout.decode(errors="replace")

    oracle_result = oracle.execute(
        run_id=run_id,
        source_path=str(cobol_dir),
        entry_program="NUMERIC-DEMO",
    )
    assert oracle_result.status.value == "SUCCEEDED"
    oracle_stdout = oracle_result.stdout.decode(errors="replace")

    assert "125.45" in oracle_stdout
    assert oracle_stdout == candidate_stdout
