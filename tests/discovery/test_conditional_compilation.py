"""Layer 4 criterion 5: the supported ``>>DEFINE``/``>>IF`` subset is evaluated by the single reader.

A gated dead branch is dropped before tokenising — its statements never reach discovery facts, the
dependency graph or the generated Java — and every conditional directive outside that subset refuses
by name (``CONDITIONAL_COMPILATION_UNEVALUATED``), never a silent default and never a guess.
"""

from __future__ import annotations

from engine.transformation.producer import TransformationProducer
from enterprise.discovery.cobol_text import read_source
from enterprise.discovery.discover import scan_file
from enterprise.discovery.dialect_profile import build_profiles
from enterprise.discovery.resolve import build_graph
from tests.discovery.test_compilers_applications import records
from tests.discovery.test_resolve_graph import program

#: ``ENABLED`` is defined as ``1``, so the ``>>ELSE`` branch is dead.  In fixed format CDF lines start
#: at column 8 (GnuCOBOL Programmer's Guide 2.1); the reader takes them wherever they are.
GATED = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. GATED.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-NAME PIC X(8).
       PROCEDURE DIVISION.
       >>DEFINE ENABLED AS 1
       >>IF ENABLED = 1
           CALL 'LIVEPGM' USING WS-NAME.
       >>ELSE
           CALL 'DEADPGM' USING WS-NAME.
       >>END-IF
           GOBACK.
"""

#: The condition names a variable nobody defines: neither branch can be decided, so both are kept
#: and the file is refused by name.
UNDECIDABLE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. UNDEC.
       PROCEDURE DIVISION.
       >>IF MYSTERY = 1
           DISPLAY 'A'.
       >>END-IF
           GOBACK.
"""


def test_a_gated_dead_branch_never_reaches_the_graph_nor_the_ir() -> None:
    """Criterion 5: an evaluated ``>>IF``/``>>ELSE`` drops the dead branch on both faces of the reader."""
    read = read_source(GATED)
    assert read.conditional == "evaluated"
    assert [number for number, kind in read.skipped if kind == "dead-branch"] == [11]

    scan = scan_file("src/GATED.cbl", "cobol", GATED)
    assert scan is not None
    assert scan.conditional == "evaluated"
    assert not [p for p in scan.problems if p.code == "CONDITIONAL_COMPILATION_UNEVALUATED"]
    assert {ref.target for ref in scan.refs if ref.relation == "calls"} == {"LIVEPGM"}

    build = build_graph(records({"src/GATED.cbl": GATED}))
    nodes = {edge.src for edge in build.graph.edges()} | {edge.dst for edge in build.graph.edges()}
    assert any("LIVEPGM" in node for node in nodes)
    assert not any("DEADPGM" in node for node in nodes)

    (profile,) = build_profiles(records({"src/GATED.cbl": GATED}))
    assert profile.directive_state == "evaluated"
    assert profile.unsupported == ()

    result = TransformationProducer().transform(GATED, "GATED")
    assert result.success is True, result.errors
    java = next(iter(result.java_source_tree.values())).upper()
    assert "LIVEPGM" in java
    assert "DEADPGM" not in java


def test_an_unevaluable_conditional_refuses_by_name_and_keeps_both_branches() -> None:
    """Criterion 5 fail-closed half: undecided means nothing is dropped and the refusal names the line."""
    read = read_source(UNDECIDABLE)
    assert read.conditional == "unevaluated" and read.conditional_line == 4
    assert not [kind for _number, kind in read.skipped if kind == "dead-branch"]

    scan = scan_file("src/UNDEC.cbl", "cobol", UNDECIDABLE)
    assert scan is not None
    assert scan.conditional == "unevaluated"
    assert [p for p in scan.problems if p.code == "CONDITIONAL_COMPILATION_UNEVALUATED"]

    (profile,) = build_profiles(records({"src/UNDEC.cbl": UNDECIDABLE}))
    assert profile.directive_state == "unevaluated"
    assert "CONDITIONAL_COMPILATION_UNEVALUATED" in profile.unsupported


def test_a_micro_focus_dollar_conditional_refuses_by_name() -> None:
    """GnuCOBOL also reads Micro Focus ``$IF``/``$DEFINE`` directives; they are never evaluated here."""
    text = "$IF X = 1\n" + program("D")
    read = read_source(text)
    assert read.conditional == "unevaluated" and read.conditional_line == 1

    scan = scan_file("src/D.cbl", "cobol", text)
    assert scan is not None
    assert [p for p in scan.problems if p.code == "CONDITIONAL_COMPILATION_UNEVALUATED"]
