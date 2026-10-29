"""Invalid source must never escape the parser as a usable semantic model."""

import pytest

from engine.transformation.application_discovery import ApplicationDiscovery
from engine.transformation.cobol_parser import CobolParseError, CobolParser
from engine.transformation.diagnostics import DiagnosticCode, DiagnosticCollector
from engine.transformation.producers.internal_native import InternalNativeJavaProducer
from engine.modernization.modernization_planner import ModernizationPlanner


HEADER = "IDENTIFICATION DIVISION.\nPROGRAM-ID. VALID.\nPROCEDURE DIVISION.\nMAIN.\n"


@pytest.mark.parametrize("source", [
    "not COBOL", "", "IDENTIFICATION DIVISION.\nPROGRAM-ID. INCOMPLETE.",
    "PROCEDURE DIVISION.\nDISPLAY 'NO ID'.",
    HEADER + "MOVE 1.\n", HEADER + "ADD 1.\n", HEADER + "COMPUTE X.\n",
    HEADER + "SUBTRACT X.\n", HEADER + "MULTIPLY X.\n",
    HEADER + "MOVE 1 TO .\n", HEADER + "OPEN INPUT .\n",
    HEADER + "COMPUTE X =\nSTOP RUN.\n",
    HEADER + "MOVE.\n", HEADER + "ADD\n", HEADER + "DISPLAY.\n",
    HEADER + "ADD AMOUNT.\nTO TOTAL\n", HEADER + "MOVE AMOUNT.\nTO TOTAL\n",
    HEADER + "IF X > 1\n", HEADER + "PERFORM 3 TIMES\nDISPLAY 'X'\n",
    HEADER + 'DISPLAY "UNCLOSED.\n',
    HEADER + "PROGRAM-ID. SECOND.\nSTOP RUN.\n",
])
def test_failure_is_authoritative_and_preserves_structured_diagnostics(source, tmp_path):
    collector = DiagnosticCollector()
    with pytest.raises(CobolParseError) as caught:
        CobolParser(collector).parse(source, source_name="bad.cob")
    assert caught.value.diagnostics == collector.all
    assert any(d.level.value == "ERROR" and d.message for d in caught.value.diagnostics)
    (tmp_path / "bad.cob").write_text(source, encoding="utf-8")
    app = ApplicationDiscovery().discover(tmp_path)
    assert not app.discovery_complete
    assert app.programs[0].program is None
    assert app.programs[0].status == "PARSE_FAILED"
    plan = ModernizationPlanner(docker_available=True).plan(tmp_path)
    assert not plan.discovery_complete
    assert plan.overall_status.value == "BLOCKED"


def test_parser_reuse_does_not_inherit_previous_failure():
    collector = DiagnosticCollector()
    parser = CobolParser(collector)
    with pytest.raises(CobolParseError):
        parser.parse("invalid")
    previous = collector.all
    program = parser.parse(HEADER + "DISPLAY 'OK'.\nSTOP RUN.\n")
    assert program.program_id == "VALID"
    assert collector.all == previous


def test_malformed_statement_reports_original_line():
    with pytest.raises(CobolParseError) as caught:
        CobolParser().parse(HEADER + "* comment\n\nMOVE 1.\n", source_name="bad.cob")
    assert caught.value.diagnostics[-1].location == "bad.cob:7"


def test_producer_retains_parser_error_and_never_generates(monkeypatch):
    producer = InternalNativeJavaProducer()

    def forbidden(*args, **kwargs):
        pytest.fail("Invalid parser output reached generation")

    monkeypatch.setattr(producer._generator, "generate", forbidden)
    result = producer.transform(HEADER + "MOVE 1.\n")
    assert result.status.value == "FAILED"
    assert not result.generated_files
    assert result.diagnostics[0]["code"] == "SYNTAX_ERROR"
    assert result.diagnostics[0]["location"]


def test_valid_continued_add_preserves_operands():
    program = CobolParser().parse(HEADER + "ADD AMOUNT\n TO TOTAL\nSTOP RUN.\n")
    statement = program.paragraphs[0].statements[0]
    assert statement.source == "AMOUNT"
    assert statement.target == "TOTAL"


def test_valid_parse_cannot_hide_later_failure():
    collector = DiagnosticCollector()
    parser = CobolParser(collector)
    assert parser.parse(HEADER + "STOP RUN.").program_id == "VALID"
    with pytest.raises(CobolParseError) as caught:
        parser.parse(HEADER + "MOVE 1.", source_name="invalid.cob")
    assert caught.value.diagnostics == collector.all
    assert caught.value.diagnostics[-1].location == "invalid.cob:5"


def test_continued_compute_and_move_preserve_operands_and_following_statement():
    program = CobolParser().parse(HEADER + "COMPUTE TOTAL =\n A * B\nMOVE TOTAL\n TO RESULT\nSTOP RUN.")
    compute, move, stop = program.paragraphs[0].statements
    assert compute.target == "TOTAL"
    assert compute.expression == "A * B"
    assert move.source == "TOTAL"
    assert move.target == "RESULT"
    assert type(stop).__name__ == "StopRunStatement"


@pytest.mark.parametrize("mode", ["INPUT", "OUTPUT", "I-O", "EXTEND"])
def test_valid_open_modes_retain_required_file(mode):
    program = CobolParser().parse(HEADER + f"OPEN {mode} DATA-FILE.\nSTOP RUN.")
    statement = program.paragraphs[0].statements[0]
    assert statement.mode == mode
    assert statement.file_name == "DATA-FILE"


def test_error_diagnostics_override_a_returned_model_with_valid_identity():
    collector = DiagnosticCollector()

    class ParserWithFatalDiagnostic(CobolParser):
        def _validate_program_structure(self, program, source):
            super()._validate_program_structure(program, source)
            collector.error(DiagnosticCode.SYNTAX_ERROR, "fatal diagnostic", "source:5")

    with pytest.raises(CobolParseError) as caught:
        ParserWithFatalDiagnostic(collector).parse(HEADER + "STOP RUN.")
    assert caught.value.diagnostics == collector.all
    assert caught.value.diagnostics[-1].message == "fatal diagnostic"


def test_warning_diagnostic_is_not_misclassified_as_fatal():
    collector = DiagnosticCollector()

    class ParserWithWarning(CobolParser):
        def _validate_program_structure(self, program, source):
            super()._validate_program_structure(program, source)
            collector.warning(DiagnosticCode.PARTIAL_SUPPORT, "warning", "source:5")

    program = ParserWithWarning(collector).parse(HEADER + "STOP RUN.")
    assert program.program_id == "VALID"
    assert collector.has_warnings and not collector.has_errors


def test_unsupported_valid_form_is_not_reported_as_malformed_syntax():
    with pytest.raises(CobolParseError) as caught:
        CobolParser().parse(HEADER + "DIVIDE 2 INTO TOTAL.\n")
    assert caught.value.diagnostics[-1].code == DiagnosticCode.UNSUPPORTED_CONSTRUCT
    assert caught.value.diagnostics[-1].location == "source:5"
