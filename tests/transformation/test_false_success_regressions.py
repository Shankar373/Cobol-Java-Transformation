"""Oracle-pinned regressions for false-success translations.

Every case below was a *false success* at b79f348: ``TransformationProducer``
returned ``success=True`` for Java that compiled to different output than
GnuCOBOL 3.1.2 (the oracle image ``gnucobol-ocesql:latest``), did not compile,
or translated source that cobc itself rejects.  Each case now either matches
the oracle's stdout exactly or fails closed with a named diagnostic.

``EXPECTED_STDOUT`` values were produced by the oracle image, not written by
hand; ``test_oracle_pins_match_gnucobol`` re-derives them in the Docker lane
(``RUN_DOCKER_TESTS=1``) so a pin can never drift from real COBOL behaviour.
"""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest

from engine.transformation.producer import TransformationProducer

ORACLE_IMAGE = "gnucobol-ocesql:latest"


def _prog(data: str, proc: str, extra_paras: str = "") -> str:
    return (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. PROBE.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        f"{data}\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-PARA.\n"
        f"{proc}\n"
        "           STOP RUN.\n"
        f"{extra_paras}"
    )


def _bare(paragraphs: str) -> str:
    """A program whose procedure division is exactly ``paragraphs``."""
    return (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. PROBE.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01 WS-C PIC 9(3) VALUE 0.\n"
        "       PROCEDURE DIVISION.\n"
        f"{paragraphs}"
    )


def _tagged(source: str) -> str:
    """Fixed-format source with an identification tag in columns 73-80."""
    return "".join(
        f"{line.ljust(72)}SEQ{number:05d}\n"
        for number, line in enumerate(source.splitlines(), start=1)
    )


_GROUP = (
    "       01 WS-G.\n          05 WS-G1 PIC X(2) VALUE 'AB'.\n"
    "          05 WS-G2 PIC X(2) VALUE 'CD'."
)

# name -> (COBOL source, stdin, oracle stdout)
EXPECTED_STDOUT: dict[str, tuple[str, str, str]] = {
    "add_high_order_truncation": (
        _prog("       01 WS-A PIC 9(3) VALUE 5.", "           ADD 999 TO WS-A.\n           DISPLAY WS-A."),
        "", "004\n",
    ),
    "move_signed_truncation": (
        _prog("       01 WS-N PIC S9(3).", "           MOVE 1234 TO WS-N.\n           DISPLAY WS-N."),
        "", "+234\n",
    ),
    # ON SIZE ERROR (Phase 3, increment 8): 450 does not fit PIC 9, so the
    # receiver keeps its value and the phrase runs.  It used to be refused
    # (and before that was success=True with wrong behaviour).
    "divide_on_size_error": (
        _prog("       01 WS-A PIC 9(3) VALUE 900.\n       01 WS-Q PIC 9.",
              "           DIVIDE WS-A BY 2 GIVING WS-Q ON SIZE ERROR DISPLAY 'ERR'.\n           DISPLAY WS-Q."),
        "", "ERR\n0\n",
    ),
    "multiply_truncation": (
        _prog("       01 WS-R PIC 9(2) VALUE 50.", "           MULTIPLY 3 BY WS-R.\n           DISPLAY WS-R."),
        "", "50\n",
    ),
    "compute_keeps_intermediate_precision": (
        _prog("       01 WS-A PIC 9 VALUE 7.\n       01 WS-R PIC 9.",
              "           COMPUTE WS-R = WS-A / 2 * 2.\n           DISPLAY WS-R."),
        "", "7\n",
    ),
    "compute_rounded_integer_receiver": (
        _prog("       01 WS-A PIC 9 VALUE 7.\n       01 WS-R PIC 9.",
              "           COMPUTE WS-R ROUNDED = WS-A / 2.\n           DISPLAY WS-R."),
        "", "4\n",
    ),
    "compute_truncation": (
        _prog("       01 WS-A PIC 9(3) VALUE 600.\n       01 WS-R PIC 9(3).",
              "           COMPUTE WS-R = WS-A * 2.\n           DISPLAY WS-R."),
        "", "200\n",
    ),
    "divide_remainder_uses_truncated_quotient": (
        _prog("       01 WS-A PIC 9 VALUE 7.\n       01 WS-Q PIC 9V99.\n       01 WS-M PIC 9V99.",
              "           DIVIDE WS-A BY 3 GIVING WS-Q REMAINDER WS-M.\n           DISPLAY WS-Q ' ' WS-M."),
        "", "2.33 0.01\n",
    ),
    "divide_remainder_integer": (
        _prog("       01 WS-A PIC 99 VALUE 17.\n       01 WS-Q PIC 99.\n       01 WS-M PIC 99.",
              "           DIVIDE WS-A BY 5 GIVING WS-Q REMAINDER WS-M.\n           DISPLAY WS-Q ' ' WS-M."),
        "", "03 02\n",
    ),
    "perform_varying_leaves_field_value": (
        _prog("       01 WS-R PIC 9(3).",
              "           PERFORM VARYING WS-R FROM 1 BY 1 UNTIL WS-R > 3\n"
              "              DISPLAY WS-R\n           END-PERFORM.\n           DISPLAY WS-R."),
        "", "001\n002\n003\n004\n",
    ),
    "perform_thru_times": (
        _prog("       01 WS-B PIC 9(3) VALUE 3.", "           PERFORM P1 THRU P2 2 TIMES.",
              "       P1.\n           ADD 1 TO WS-B.\n       P2.\n           DISPLAY WS-B.\n"),
        "", "004\n005\n",
    ),
    "alphanumeric_equality_is_space_padded": (
        _prog("       01 WS-O PIC X(5) VALUE 'YES'.",
              "           IF WS-O = 'YES'\n              DISPLAY 'EQ'\n           ELSE\n"
              "              DISPLAY 'NE'\n           END-IF."),
        "", "EQ\n",
    ),
    "alphanumeric_not_equal_is_space_padded": (
        _prog("       01 WS-O PIC X(5) VALUE 'YES'.",
              "           IF WS-O NOT = 'YES'\n              DISPLAY 'NE'\n           ELSE\n"
              "              DISPLAY 'EQ'\n           END-IF."),
        "", "EQ\n",
    ),
    "alphanumeric_ordering": (
        _prog("       01 WS-G1 PIC X(2) VALUE 'AB'.",
              "           IF WS-G1 > 'AA'\n              DISPLAY 'GT'\n           END-IF."),
        "", "GT\n",
    ),
    "alphanumeric_compound_condition": (
        _prog("       01 WS-A PIC X(3).\n       01 WS-B PIC X(3).",
              "           MOVE 'X' TO WS-A.\n           MOVE 'Q' TO WS-B.\n"
              "           IF WS-A = 'X' OR WS-B = 'Y'\n              DISPLAY 'T'\n           ELSE\n"
              "              DISPLAY 'F'\n           END-IF."),
        "", "T\n",
    ),
    "alphanumeric_field_to_field": (
        _prog("       01 WS-A PIC X(3).\n       01 WS-B PIC X(5).",
              "           MOVE 'AB' TO WS-A.\n           MOVE 'AB' TO WS-B.\n"
              "           IF WS-A = WS-B\n              DISPLAY 'T'\n           ELSE\n"
              "              DISPLAY 'F'\n           END-IF."),
        "", "T\n",
    ),
    "alphanumeric_until_terminates": (
        _prog("       01 WS-A PIC X(3) VALUE 'N'.\n       01 WS-C PIC 9 VALUE 0.",
              "           PERFORM UNTIL WS-A = 'Y'\n              ADD 1 TO WS-C\n"
              "              IF WS-C > 2\n                 MOVE 'Y' TO WS-A\n              END-IF\n"
              "           END-PERFORM.\n           DISPLAY WS-C."),
        "", "3\n",
    ),
    "pic_on_continuation_line": (
        "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. PROBE.\n       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n       01 WS-A\n              PIC 9(3) VALUE 5.\n"
        "       PROCEDURE DIVISION.\n       MAIN-PARA.\n           ADD 1 TO WS-A.\n"
        "           DISPLAY WS-A.\n           STOP RUN.\n",
        "", "006\n",
    ),
    "value_on_continuation_line": (
        "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. PROBE.\n       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n       01 WS-A PIC X(5)\n              VALUE 'HELLO'.\n"
        "       PROCEDURE DIVISION.\n       MAIN-PARA.\n           DISPLAY WS-A.\n"
        "           STOP RUN.\n",
        "", "HELLO\n",
    ),
    "accept_from_stdin": (
        _prog("       01 WS-IN PIC X(5).", "           ACCEPT WS-IN.\n           DISPLAY '[' WS-IN ']'."),
        "HELLO\n", "[HELLO]\n",
    ),
    # --- paragraph fall-through: main runs the chain until STOP RUN/GOBACK
    "paragraph_fall_through": (
        _bare("       P1.\n           DISPLAY 'A'.\n       P2.\n           DISPLAY 'B'.\n           STOP RUN.\n"),
        "", "A\nB\n",
    ),
    "fall_through_to_end_of_program": (
        _bare("       P1.\n           DISPLAY 'A'.\n       P2.\n           DISPLAY 'B'.\n"),
        "", "A\nB\n",
    ),
    "fall_through_after_perform": (
        _bare("       P1.\n           PERFORM P2.\n       P2.\n           ADD 1 TO WS-C.\n"
              "           DISPLAY WS-C.\n       P3.\n           DISPLAY 'END'.\n           STOP RUN.\n"),
        "", "001\n002\nEND\n",
    ),
    # --- PERFORM header continued on following lines; separator period on
    # its own line (both used to fail closed as unparsed statements)
    "perform_varying_header_on_continuation_lines": (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. PROBE.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01 WS-I PIC 9(2) VALUE 0.\n"
        "       01 WS-T PIC 9(3) VALUE 0.\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-PARA.\n"
        "           PERFORM ADD-ONE\n"
        "               VARYING WS-I FROM 1 BY 2\n"
        "               UNTIL WS-I > 7\n"
        "           DISPLAY WS-T\n"
        "           IF WS-T > 5\n"
        "               DISPLAY 'BIG'\n"
        "           END-IF\n"
        "           .\n"
        "           DISPLAY 'DONE'.\n"
        "           STOP RUN.\n"
        "       ADD-ONE.\n"
        "           ADD WS-I TO WS-T.\n",
        "", "016\nBIG\nDONE\n",
    ),
    # --- SUBTRACT with several subtrahends (used to fail closed as unparsed)
    "subtract_multi_source_in_place": (
        _prog("       01 WS-A PIC 9(3) VALUE 10.\n       01 WS-B PIC 9(3) VALUE 25.\n"
              "       01 WS-C PIC 9(3) VALUE 100.",
              "           SUBTRACT WS-A WS-B FROM WS-C.\n           DISPLAY WS-C."),
        "", "065\n",
    ),
    "subtract_multi_source_with_literal_giving": (
        _prog("       01 WS-A PIC 9(3) VALUE 10.\n       01 WS-B PIC 9(3) VALUE 25.\n"
              "       01 WS-C PIC 9(3) VALUE 100.\n       01 WS-D PIC 9(3) VALUE 0.",
              "           SUBTRACT WS-A WS-B 5 FROM WS-C GIVING WS-D.\n"
              "           DISPLAY WS-C ' ' WS-D."),
        "", "100 060\n",
    ),
    "subtract_from_literal_minuend_giving": (
        _prog("       01 WS-A PIC 9(3) VALUE 10.\n       01 WS-B PIC 9(3) VALUE 25.\n"
              "       01 WS-R PIC 9(3) VALUE 0.",
              "           SUBTRACT WS-A WS-B FROM 200 GIVING WS-R.\n           DISPLAY WS-R."),
        "", "165\n",
    ),
    "subtract_multi_source_decimal_truncation_and_rounded": (
        _prog("       01 WS-A PIC 9V99 VALUE 1.25.\n       01 WS-B PIC 9V99 VALUE 0.50.\n"
              "       01 WS-C PIC 9(2)V9 VALUE 10.0.\n       01 WS-D PIC 9(2) VALUE 0.",
              "           SUBTRACT WS-A WS-B FROM WS-C.\n           DISPLAY WS-C.\n"
              "           SUBTRACT WS-A WS-B FROM 20.9 GIVING WS-D ROUNDED.\n"
              "           DISPLAY WS-D."),
        "", "08.2\n19\n",
    ),
    "subtract_multi_source_signed_and_unsigned_receivers": (
        _prog("       01 WS-A PIC 9(3) VALUE 50.\n       01 WS-B PIC 9(3) VALUE 70.\n"
              "       01 WS-C PIC S9(3) VALUE 100.\n       01 WS-U PIC 9(3) VALUE 100.",
              "           SUBTRACT WS-A, WS-B FROM WS-C.\n           DISPLAY WS-C.\n"
              "           SUBTRACT WS-A WS-B FROM WS-U.\n           DISPLAY WS-U."),
        "", "-020\n020\n",
    ),
    # --- clause keywords inside a VALUE literal are literal text (found by
    # the Phase 2 end-to-end run: workload_inventory's report header)
    "value_literal_containing_clause_keywords": (
        _prog("       01 WS-H PIC X(30) VALUE\n           \"QTY  PRICE   VALUE\".\n"
              "       01 WS-K PIC X(20) VALUE \"PIC 9 OCCURS 3\".",
              "           DISPLAY '[' WS-H ']'.\n           DISPLAY '[' WS-K ']'."),
        "", "[QTY  PRICE   VALUE            ]\n[PIC 9 OCCURS 3      ]\n",
    ),
    # --- fixed format: columns 73-80 are not program text
    "identification_area_columns_73_to_80_ignored": (
        _tagged(_prog(
            "       01 WS-A PIC X(4) VALUE 'AB'.\n       01 WS-B PIC 9(3) VALUE 7.",
            "           DISPLAY 'TAGGED' WS-A WS-B.\n           ADD 5 TO WS-B.\n"
            "           DISPLAY WS-B.",
        )),
        "", "TAGGEDAB  007\n012\n",
    ),
    "exit_program_in_main_program_is_no_op": (
        _bare("       P1.\n           DISPLAY 'A'.\n           IF WS-C = 0\n              EXIT PROGRAM\n"
              "           END-IF.\n           DISPLAY 'B'.\n           STOP RUN.\n"),
        "", "A\nB\n",
    ),
    # --- group items as views over DISPLAY-usage leaves
    "group_move_literal": (
        _prog(_GROUP, "           MOVE 'WXYZ' TO WS-G.\n           DISPLAY WS-G1 WS-G2."),
        "", "WXYZ\n",
    ),
    "group_move_spaces": (
        _prog(_GROUP, "           MOVE SPACES TO WS-G.\n           DISPLAY '[' WS-G ']'."),
        "", "[    ]\n",
    ),
    "group_display": (
        _prog(_GROUP, "           MOVE 'ZZ' TO WS-G1.\n           DISPLAY WS-G."),
        "", "ZZCD\n",
    ),
    "group_report_line_with_fillers": (
        _prog("       01 WS-LINE.\n          05 FILLER PIC X(6) VALUE 'TOTAL:'.\n"
              "          05 WS-AMT PIC 9(5) VALUE 42.\n          05 FILLER PIC X(2).\n"
              "          05 WS-NAME PIC X(4) VALUE 'ABC'.\n          05 FILLER PIC X VALUE '%'.",
              "           ADD 7 TO WS-AMT.\n           DISPLAY '[' WS-LINE ']'."),
        "", "[TOTAL:00049  ABC %]\n",
    ),
    "group_to_alphanumeric_field": (
        _prog(_GROUP + "\n       01 WS-T PIC X(6).\n       01 WS-U PIC X(3).",
              "           MOVE WS-G TO WS-T.\n           MOVE WS-G TO WS-U.\n"
              "           DISPLAY '[' WS-T '][' WS-U ']'."),
        "", "[ABCD  ][ABC]\n",
    ),
    "nested_group_with_numeric_leaf_to_field": (
        _prog("       01 WS-OUT.\n          05 WS-A PIC X(2) VALUE 'AB'.\n          05 WS-IN.\n"
              "             10 WS-B PIC X(3) VALUE 'CDE'.\n             10 WS-C PIC 9(2) VALUE 7.\n"
              "          05 WS-D PIC X VALUE 'Z'.\n       01 WS-T PIC X(8).",
              "           MOVE WS-OUT TO WS-T.\n           DISPLAY WS-T."),
        "", "ABCDE07Z\n",
    ),
}

# name -> (COBOL source, diagnostic substring).  Each was translated with
# success=True and wrong behaviour; the deterministic lane now refuses it.
EXPECTED_FAIL_CLOSED: dict[str, tuple[str, str]] = {
    "stop_run_in_performed_paragraph": (
        _prog("       01 WS-B PIC 9 VALUE 1.", "           PERFORM P9.\n           DISPLAY 'AFTER'.",
              "       P9.\n           DISPLAY 'IN'.\n           STOP RUN.\n"),
        "STOP RUN inside non-driver paragraph",
    ),
    "level_66_renames": (
        _prog("       01 WS-B PIC 9(3) VALUE 3.\n       66 WS-X RENAMES WS-B.", "           DISPLAY WS-X."),
        "Level-66",
    ),
    "justified_right": (
        _prog("       01 WS-J PIC X(5) JUSTIFIED RIGHT.", "           MOVE 'AB' TO WS-J.\n           DISPLAY '[' WS-J ']'."),
        "JUSTIFIED",
    ),
    "blank_when_zero": (
        _prog("       01 WS-Z PIC 9(3) BLANK WHEN ZERO VALUE 0.", "           DISPLAY '[' WS-Z ']'."),
        "BLANK WHEN ZERO",
    ),
    "unexpanded_copy": (
        _prog("       COPY MISSINGCPY.\n       01 WS-B PIC 9 VALUE 1.", "           DISPLAY WS-B."),
        "COPY MISSINGCPY",
    ),
    "display_with_no_advancing": (
        _prog("       01 WS-B PIC 9 VALUE 1.", "           DISPLAY WS-B WITH NO ADVANCING.\n           DISPLAY 'X'."),
        "DISPLAY",
    ),
    "two_statements_on_one_line": (
        _prog("       01 WS-J PIC X(5).", "           MOVE 'AB' TO WS-J DISPLAY WS-J."),
        "MOVE",
    ),
    "stop_run_closing_a_performed_chain_paragraph": (
        _bare("       P1.\n           PERFORM P2.\n       P2.\n           DISPLAY 'B'.\n           STOP RUN.\n"),
        "STOP RUN inside non-driver paragraph",
    ),
    "conditional_stop_run_inside_fall_through_chain": (
        _bare("       P1.\n           DISPLAY 'A'.\n       P2.\n           IF WS-C = 0\n              STOP RUN\n"
              "           END-IF.\n       P3.\n           DISPLAY 'C'.\n           STOP RUN.\n"),
        "STOP RUN inside non-driver paragraph",
    ),
    "group_move_into_numeric_leaf": (
        _prog("       01 WS-G.\n          05 WS-G1 PIC X(2).\n          05 WS-N PIC 9(2).",
              "           MOVE 'ABCD' TO WS-G.\n           DISPLAY WS-G."),
        "named PIC X field",
    ),
    "group_with_signed_leaf": (
        _prog("       01 WS-S.\n          05 WS-S1 PIC S9(3) VALUE -5.", "           DISPLAY WS-S."),
        "unsigned integer",
    ),
    "string_into_group": (
        _prog(_GROUP, "           STRING 'XY' 'Z' DELIMITED BY SIZE INTO WS-G.\n           DISPLAY WS-G1 WS-G2."),
        "STRING references group item",
    ),
    "unstring_into_group": (
        _prog(_GROUP + "\n       01 WS-T PIC X(5) VALUE 'PQ,RS'.",
              "           UNSTRING WS-T DELIMITED BY ',' INTO WS-G.\n           DISPLAY WS-G1 WS-G2."),
        "UNSTRING references group item",
    ),
    "duplicate_data_name": (
        _prog(_GROUP + "\n       01 WS-H.\n          05 WS-G1 PIC X(2).", "           DISPLAY WS-G1."),
        "declared more than once",
    ),
    # SUBTRACT forms outside the parsed subset stay refused.
    "subtract_into_several_receivers": (
        _prog("       01 WS-A PIC 9(3) VALUE 1.\n       01 WS-B PIC 9(3) VALUE 5.\n"
              "       01 WS-C PIC 9(3) VALUE 9.",
              "           SUBTRACT WS-A FROM WS-B WS-C.\n           DISPLAY WS-B WS-C."),
        "Statement did not parse into IR: SUBTRACT",
    ),
    "subtract_literal_minuend_without_giving": (
        _prog("       01 WS-A PIC 9(3) VALUE 1.", "           SUBTRACT WS-A FROM 5.\n"
              "           DISPLAY WS-A."),
        "Statement did not parse into IR: SUBTRACT",
    ),
    # GnuCOBOL 3.1.2 rejects this source ("PROCEDURE DIVISION header
    # missing"); the section scanners used to translate it anyway.
    "working_storage_after_linkage": (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. PROBE.\n"
        "       DATA DIVISION.\n"
        "       LINKAGE SECTION.\n"
        "       01 LS-A PIC 9(4).\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01 WS-T PIC 9(4) VALUE 0.\n"
        "       PROCEDURE DIVISION USING LS-A.\n"
        "       MAIN-PARA.\n"
        "           DISPLAY WS-T.\n"
        "           GOBACK.\n",
        "WORKING-STORAGE SECTION is out of order",
    ),
}


def _transform(source: str):
    return TransformationProducer().transform(source, "PROBE")


@pytest.mark.parametrize("name", sorted(EXPECTED_FAIL_CLOSED))
def test_unfaithful_translation_fails_closed(name):
    source, diagnostic = EXPECTED_FAIL_CLOSED[name]
    result = _transform(source)
    assert result.success is False
    assert any(diagnostic in error for error in result.errors), result.errors


@pytest.mark.parametrize("name", sorted(EXPECTED_STDOUT))
def test_supported_translation_succeeds(name):
    source, _, _ = EXPECTED_STDOUT[name]
    result = _transform(source)
    assert result.success is True, result.errors


def test_same_source_yields_identical_java():
    """Generated names must not depend on how many programs were mapped before."""
    source = _prog(
        "       01 WS-B PIC 9(3) VALUE 0.",
        "           PERFORM 2 TIMES\n              ADD 1 TO WS-B\n           END-PERFORM.",
    )
    first = _transform(source).java_source_tree
    _transform(EXPECTED_STDOUT["perform_thru_times"][0])
    second = _transform(source).java_source_tree
    assert first == second


def _require_jdk() -> None:
    if shutil.which("javac") and shutil.which("java"):
        return
    if os.environ.get("RUN_DOCKER_TESTS") == "1":
        pytest.fail("javac/java not on PATH: the Docker lane requires a JDK")
    pytest.skip("javac/java not on PATH")


@pytest.mark.parametrize("name", sorted(EXPECTED_STDOUT))
def test_generated_java_matches_oracle_stdout(name, tmp_path):
    _require_jdk()
    source, stdin, expected = EXPECTED_STDOUT[name]
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
        ["java", "-cp", str(tmp_path), result.generated_files[0].class_name],
        input=stdin.encode(), capture_output=True, timeout=60, cwd=tmp_path,
    )
    assert run.returncode == 0, run.stderr.decode(errors="replace")
    assert run.stdout.decode().replace("\r\n", "\n") == expected


@pytest.mark.parametrize("name", sorted(EXPECTED_STDOUT))
def test_oracle_pins_match_gnucobol(name, tmp_path):
    """Docker lane: every pinned stdout is what GnuCOBOL really prints."""
    source, stdin, expected = EXPECTED_STDOUT[name]
    (tmp_path / "P.cob").write_text(source, encoding="utf-8", newline="\n")
    os.chmod(tmp_path, 0o755)
    os.chmod(tmp_path / "P.cob", 0o644)
    run = subprocess.run(
        ["docker", "run", "--rm", "-i", "--network", "none",
         "-v", f"{tmp_path}:/src:ro", ORACLE_IMAGE, "sh", "-c",
         "cd /tmp && cobc -x /src/P.cob -o p && ./p"],
        input=stdin.encode(), capture_output=True, timeout=180,
    )
    assert run.returncode == 0, run.stderr.decode(errors="replace")
    assert run.stdout.decode().replace("\r\n", "\n") == expected
