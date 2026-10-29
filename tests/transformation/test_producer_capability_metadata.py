"""Producer capability metadata truthfulness tests.

The producer's declared construct lists are an untrusted claim about language
coverage. These tests pin that claim to observable generator behaviour so the
metadata cannot silently drift away from the implementation again.

Classification contract (see engine/transformation/contracts.py):
    supported   — lowered to Java with full observable semantics
    partial     — lowered, but semantics are incomplete or degraded
    unsupported — no semantic Java lowering (comment-only or not parsed)
"""

from __future__ import annotations

from engine.transformation.contracts import TransformationResult
from engine.transformation.producers.internal_native import InternalNativeJavaProducer

MINIMAL = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. {pid}.\n"
    "       DATA DIVISION.\n"
    "       WORKING-STORAGE SECTION.\n"
    "       01 WS-A PIC 9(4) VALUE 1.\n"
    "       01 WS-B PIC 9(4) VALUE 2.\n"
    "       01 WS-S PIC X(20) VALUE SPACES.\n"
    "       PROCEDURE DIVISION.\n"
    "       MAIN-LOGIC.\n"
    "{body}"
    "           STOP RUN.\n"
)


def _transform(body: str, pid: str = "META") -> TransformationResult:
    return InternalNativeJavaProducer().transform(MINIMAL.format(pid=pid, body=body), program_id=pid)


class TestCapabilityListsAreDisjoint:
    """A construct must never be claimed by two capability lists."""

    def test_lists_are_pairwise_disjoint(self):
        result = _transform("           DISPLAY WS-A\n")
        supported = set(result.supported_constructs)
        unsupported = set(result.unsupported_constructs)
        partial = set(result.partial_constructs)

        assert not (supported & unsupported), sorted(supported & unsupported)
        assert not (supported & partial), sorted(supported & partial)
        assert not (unsupported & partial), sorted(unsupported & partial)

    def test_lists_have_no_internal_duplicates(self):
        result = _transform("           DISPLAY WS-A\n")
        for name, values in (
            ("supported", result.supported_constructs),
            ("unsupported", result.unsupported_constructs),
            ("partial", result.partial_constructs),
        ):
            assert len(values) == len(set(values)), f"duplicates in {name}: {values}"

    def test_declared_lists_are_non_empty(self):
        result = _transform("           DISPLAY WS-A\n")
        assert result.supported_constructs
        assert result.unsupported_constructs
        assert result.partial_constructs


class TestImplementedConstructsAreNotDeclaredUnsupported:
    """Constructs with a real semantic lowering must not be listed as
    unsupported (this was the original stale-metadata defect)."""

    def test_arithmetic_and_branching_constructs_are_supported(self):
        result = _transform("           DISPLAY WS-A\n")
        unsupported = set(result.unsupported_constructs)
        for construct in ("COMPUTE", "SUBTRACT", "MULTIPLY"):
            assert construct not in unsupported, construct
            assert construct in result.supported_constructs, construct

    def test_divide_by_giving_is_supported_and_divide_into_is_not(self):
        """Only the BY/GIVING form has a lowering; DIVIDE ... INTO is a
        hard parser rejection (UNSUPPORTED_CONSTRUCT), so it must never be
        claimed as supported."""
        result = _transform("           DISPLAY WS-A\n")
        assert "DIVIDE ... BY ... GIVING" in result.supported_constructs
        assert "DIVIDE ... INTO" in result.unsupported_constructs
        assert "DIVIDE" not in result.supported_constructs

    def test_divide_by_giving_is_actually_lowered(self):
        result = _transform(
            "           DIVIDE WS-A BY WS-B GIVING WS-A\n"
            "           DISPLAY WS-A\n"
        )
        assert result.status.value in ("SUCCESS", "PARTIAL")
        joined = "\n".join(f.source_code for f in result.generated_files)
        assert "WS_A = (WS_A / WS_B);" in joined

    def test_divide_into_fails_closed_with_unsupported_construct(self):
        result = _transform("           DIVIDE WS-A INTO WS-B\n")
        assert result.status.value == "FAILED"
        codes = {d["code"] for d in result.diagnostics}
        assert "UNSUPPORTED_CONSTRUCT" in codes, codes

    def test_evaluate_is_declared_partial_not_supported(self):
        """EVALUATE is only partially lowered: the subject form with arm
        bodies on their own lines is correct, but `EVALUATE TRUE` and
        same-line arm bodies are flattened into an invalid condition. It
        must therefore never be claimed as fully supported."""
        result = _transform("           DISPLAY WS-A\n")
        assert "EVALUATE" in result.partial_constructs
        assert "EVALUATE" not in result.supported_constructs
        assert "EVALUATE" not in result.unsupported_constructs

    def test_evaluate_subject_form_is_lowered(self):
        source = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. EVALSUBJ.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-ST PIC 9(2) VALUE 1.\n"
            "       01 WS-OUT PIC X(10).\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN.\n"
            "           EVALUATE WS-ST\n"
            "               WHEN 1\n"
            "                   MOVE 'ONE' TO WS-OUT\n"
            "               WHEN OTHER\n"
            "                   MOVE 'OTHER' TO WS-OUT\n"
            "           END-EVALUATE\n"
            "           DISPLAY WS-OUT\n"
            "           STOP RUN.\n"
        )
        result = InternalNativeJavaProducer().transform(
            source, program_id="EVALSUBJ"
        )
        assert result.status.value in ("SUCCESS", "PARTIAL")
        joined = "\n".join(f.source_code for f in result.generated_files)
        assert "if (WS_ST == 1)" in joined
        assert 'WS_OUT = "ONE";' in joined
        assert "} else {" in joined

    def test_static_call_is_supported_and_dynamic_call_is_not(self):
        result = _transform("           DISPLAY WS-A\n")
        assert any(c.startswith("CALL") for c in result.supported_constructs)
        assert "dynamic CALL" in result.unsupported_constructs
        assert "CALL" not in result.supported_constructs

    def test_compute_is_actually_lowered(self):
        """The claim is pinned to behaviour: COMPUTE produces no
        UNSUPPORTED_CONSTRUCT diagnostic."""
        result = _transform(
            "           COMPUTE WS-A = WS-A + WS-B\n"
            "           DISPLAY WS-A\n"
        )
        messages = [d["message"] for d in result.diagnostics]
        assert not [m for m in messages if "COMPUTE" in m], messages
        assert result.status.value in ("SUCCESS", "PARTIAL")


class TestUnsupportedConstructsAreNotClaimedSupported:
    """Constructs with no semantic lowering must not be listed as supported."""

    def test_comment_only_construct_is_unsupported(self):
        result = _transform("           DISPLAY WS-A\n")
        supported = set(result.supported_constructs)
        assert "GO TO" not in supported
        assert "GO TO" in result.unsupported_constructs

    def test_unparsed_constructs_are_unsupported(self):
        result = _transform("           DISPLAY WS-A\n")
        supported = set(result.supported_constructs)
        for construct in ("SORT", "ACCEPT", "CLOSE", "INDEXED files", "RELATIVE files"):
            assert construct not in supported, construct
            assert construct in result.unsupported_constructs, construct

    def test_goto_is_emitted_as_comment_only(self):
        """GO TO has no control-flow lowering — it becomes a Java comment."""
        source = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. GOTODEMO.\n"
            "       PROCEDURE DIVISION.\n"
            "       FIRST-PARA.\n"
            "           DISPLAY 1\n"
            "           GO TO LAST-PARA.\n"
            "       LAST-PARA.\n"
            "           STOP RUN.\n"
        )
        result = InternalNativeJavaProducer().transform(source, program_id="GOTODEMO")
        joined = "\n".join(f.source_code for f in result.generated_files)
        assert "// GO TO LAST-PARA" in joined
        assert "GO TO" in result.unsupported_constructs


class TestPartialConstructsAreNotOverclaimed:
    """Constructs with degraded semantics must not be declared supported."""

    def test_occurs_and_string_are_partial(self):
        result = _transform("           DISPLAY WS-A\n")
        supported = set(result.supported_constructs)
        for construct in ("OCCURS", "STRING"):
            assert construct not in supported, construct
            assert construct in result.partial_constructs, construct

    def test_partial_constructs_are_not_declared_unsupported(self):
        result = _transform("           DISPLAY WS-A\n")
        unsupported = set(result.unsupported_constructs)
        for construct in ("OCCURS", "STRING", "UNSTRING"):
            assert construct not in unsupported, construct


UNSTRING_FILE_SOURCE = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. UNSTRDEMO.\n"
    "       ENVIRONMENT DIVISION.\n"
    "       INPUT-OUTPUT SECTION.\n"
    "       FILE-CONTROL.\n"
    '           SELECT INFILE ASSIGN TO "fixtures/input.dat".\n'
    "       DATA DIVISION.\n"
    "       FILE SECTION.\n"
    "       FD INFILE.\n"
    "       01 IN-REC PIC X(20).\n"
    "       WORKING-STORAGE SECTION.\n"
    "       01 WS-ID PIC X(5).\n"
    "       PROCEDURE DIVISION.\n"
    "       MAIN.\n"
    '           UNSTRING IN-REC DELIMITED BY "|" INTO WS-ID\n'
    "           DISPLAY WS-ID\n"
    "           STOP RUN.\n"
)


class TestUnstringIsPartial:
    """UNSTRING is lowered only for input-record splitting; other forms fail
    closed. It must therefore be declared PARTIAL, never SUPPORTED."""

    def test_declared_partial(self):
        result = InternalNativeJavaProducer().transform(
            UNSTRING_FILE_SOURCE, program_id="UNSTRDEMO"
        )
        assert "UNSTRING" in result.partial_constructs
        assert "UNSTRING" not in result.supported_constructs
        assert "UNSTRING" not in result.unsupported_constructs

    def test_record_unstring_is_lowered_to_delimited_split(self):
        result = InternalNativeJavaProducer().transform(
            UNSTRING_FILE_SOURCE, program_id="UNSTRDEMO"
        )
        assert result.generated_files
        joined = "\n".join(f.source_code for f in result.generated_files)
        assert "line.split(" in joined
        assert "WS_ID = rec[1]" in joined

    def test_unstring_without_input_file_fails_closed(self):
        """No input record to split from -> explicit failure, never a silent
        comment-only lowering."""
        result = _transform("           UNSTRING WS-S DELIMITED BY ' ' INTO WS-A\n")
        assert result.status.value == "FAILED"
        messages = [d["message"] for d in result.diagnostics]
        assert any("MISSING_REQUIRED_SEMANTIC" in m for m in messages), messages
