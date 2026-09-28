"""Focused regression tests for capability truthfulness.

These tests pin the boundary between what the IR represents and what the
current deterministic Java mapper can actually preserve.
"""

from __future__ import annotations

from engine.modernization.capability_analyzer import CapabilityAnalyzer, CapabilityLevel
from engine.transformation.ir import (
    CobolApplication,
    CobolProgram,
    CobolProgramUnit,
    DataItem,
    Paragraph,
    PicType,
    UnstringStatement,
    MoveStatement,
)


def _unit(program: CobolProgram) -> CobolProgramUnit:
    return CobolProgramUnit(
        program_id=program.program_id,
        source_path=f"{program.program_id}.cob",
        program=program,
    )


def _report(program: CobolProgram):
    app = CobolApplication(
        application_id="capability-truthfulness",
        programs=(_unit(program),),
    )
    return CapabilityAnalyzer(docker_available=True).analyze(app)


def test_unstring_is_not_reported_as_fully_supported() -> None:
    program = CobolProgram(
        program_id="UNSTRING-DEMO",
        paragraphs=(
            Paragraph(
                name="MAIN",
                statements=(
                    UnstringStatement(
                        source="WS-INPUT",
                        delimiter="|",
                        targets=("WS-A", "WS-B"),
                    ),
                ),
            ),
        ),
    )

    report = _report(program)
    capability = next(
        c for c in report.components
        if c.component_type == "PROGRAM"
    )

    assert capability.level == CapabilityLevel.UNSUPPORTED
    assert "UNSTRING" in capability.reason
    assert "semantic Java lowering" in capability.reason


def test_data_semantics_are_reported_partial_not_supported() -> None:
    program = CobolProgram(
        program_id="DATA-SEMANTICS-DEMO",
        working_storage=(
            DataItem(
                name="WS-TABLE-ITEM",
                pic_type=PicType.NUMERIC,
                pic_length=4,
                occurs=5,
            ),
            DataItem(
                name="WS-REDEF",
                pic_type=PicType.ALPHANUMERIC,
                pic_length=4,
                redefines="WS-TABLE-ITEM",
            ),
            DataItem(
                name="WS-COMP3",
                pic_type=PicType.NUMERIC,
                pic_length=6,
                usage="COMP-3",
            ),
            DataItem(
                name="WS-DECIMAL",
                pic_type=PicType.NUMERIC,
                pic_length=6,
                decimal_places=2,
            ),
            DataItem(
                name="WS-STATUS-OK",
                level=88,
                value="OK",
            ),
        ),
        paragraphs=(
            Paragraph(
                name="MAIN",
                statements=(
                    MoveStatement(source="1", target="WS-TABLE-ITEM"),
                ),
            ),
        ),
    )

    report = _report(program)
    capability = next(
        c for c in report.components
        if c.component_type == "PROGRAM"
    )

    assert capability.level == CapabilityLevel.PARTIAL
    assert "OCCURS" in capability.reason
    assert "REDEFINES" in capability.reason
    assert "COMP-3" in capability.reason
    assert "fixed-point precision/scale" in capability.reason
    assert "level-88" in capability.reason


def test_plain_supported_program_remains_supported() -> None:
    program = CobolProgram(
        program_id="PLAIN-DEMO",
        working_storage=(
            DataItem(
                name="WS-N",
                pic_type=PicType.NUMERIC,
                pic_length=4,
                value="0",
            ),
        ),
        paragraphs=(
            Paragraph(
                name="MAIN",
                statements=(
                    MoveStatement(source="1", target="WS-N"),
                ),
            ),
        ),
    )

    report = _report(program)
    capability = next(
        c for c in report.components
        if c.component_type == "PROGRAM"
    )

    assert capability.level == CapabilityLevel.SUPPORTED
    assert capability.reason == "All constructs supported"
