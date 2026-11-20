"""COBOL scanner: positions, formats, COPY/CALL, files and VSAM, embedded SQL/CICS/DLI, IMS, MQ, dialect signals."""

from __future__ import annotations

import pytest

from enterprise.discovery.cobol_text import detect_format, logical_lines, tokenize
from enterprise.discovery.scan_cobol import scan_cobol
from tests.discovery.helpers import _fixed


def _free(*lines: str) -> str:
    return ">>SOURCE FORMAT FREE\n" + "\n".join(lines) + "\n"


def refs(scan, relation=None, kind=None):
    return [r for r in scan.refs if (relation is None or r.relation == relation) and (kind is None or r.target_kind == kind)]


def facts(scan, category):
    return [f for f in scan.facts if f.category == category]


def targets(scan, relation, kind=None):
    return sorted(r.target for r in refs(scan, relation, kind))


# --- reference format ---------------------------------------------------------------------------------------------------


def test_fixed_format_ignores_sequence_and_identification_area_and_comments() -> None:
    text = ("000100 IDENTIFICATION DIVISION.                                              SEQ00010\n"
            "000200*COMMENT PROGRAM-ID. HIDDEN.\n"
            "000300 PROGRAM-ID. REALPGM.                                                  SEQ00030\n")
    scan = scan_cobol("a.cbl", text)
    assert [f.name for f in facts(scan, "program-id")] == ["REALPGM"]
    assert scan.source_format == "fixed"


def test_free_format_directive_and_inline_comments() -> None:
    text = ">>SOURCE FORMAT FREE\nIDENTIFICATION DIVISION.\nPROGRAM-ID. FREEPGM. *> trailing comment CALL 'NOPE'\nPROCEDURE DIVISION.\nCALL 'REAL' USING X.\n"
    scan = scan_cobol("f.cbl", text)
    assert scan.source_format == "free"
    assert targets(scan, "calls") == ["REAL"]


def test_free_format_detected_without_directive_when_code_starts_in_column_one() -> None:
    assert detect_format("IDENTIFICATION DIVISION.\nPROGRAM-ID. X.\n") == "free"
    assert detect_format("       IDENTIFICATION DIVISION.\n") == "fixed"


def test_format_switch_mid_file_is_reported_as_mixed() -> None:
    fmt, lines, directives = logical_lines("       PROGRAM-ID. A.\n>>SOURCE FORMAT FREE\nCALL 'B'.\n")
    assert fmt == "mixed" and directives and any("B" in line.text for line in lines)


def test_continuation_line_joins_an_alphanumeric_literal() -> None:
    head = "           CALL '"
    filler = "A" * (72 - len(head))  # the literal runs to column 72, so no padding is inserted
    text = ("       PROGRAM-ID. P.\n"
            "       PROCEDURE DIVISION.\n"
            f"{head}{filler}\n"
            "      -    'BCD' USING X.\n")
    scan = scan_cobol("p.cbl", text)
    assert targets(scan, "calls") == [filler + "BCD"]
    assert refs(scan, "calls")[0].line == 3  # anchored at the first physical line


def test_text_beyond_column_72_is_not_program_text() -> None:
    line = "           CALL 'REAL' USING X." + " " * 40 + "CALL 'HIDDEN' USING Y."
    scan = scan_cobol("p.cbl", "       PROGRAM-ID. P.\n" + line + "\n")
    assert targets(scan, "calls") == ["REAL"]


def test_unterminated_literal_is_reported_not_swallowed() -> None:
    scan = scan_cobol("p.cbl", _fixed("PROGRAM-ID. P.", "PROCEDURE DIVISION.", "    DISPLAY 'OPEN"))
    assert [p.code for p in scan.problems] == ["UNTERMINATED_LITERAL"]


def test_tokens_carry_exact_line_and_column() -> None:
    _, lines, _ = logical_lines("       PROGRAM-ID. P.\n           CALL 'X'.\n")
    token = next(t for t in tokenize(lines) if t.kind == "literal")
    assert (token.line, token.column) == (2, 17)


# --- program structure --------------------------------------------------------------------------------------------------


def test_program_ids_nested_programs_and_end_program() -> None:
    text = _fixed(
        "IDENTIFICATION DIVISION.", "PROGRAM-ID. OUTER.", "PROCEDURE DIVISION.",
        "IDENTIFICATION DIVISION.", "PROGRAM-ID. INNER IS COMMON.", "PROCEDURE DIVISION.", "END PROGRAM INNER.",
        "END PROGRAM OUTER.",
        "IDENTIFICATION DIVISION.", "PROGRAM-ID. SECOND.", "END PROGRAM SECOND.")
    scan = scan_cobol("m.cbl", text)
    ids = {f.name: dict(f.detail) for f in facts(scan, "program-id")}
    assert set(ids) == {"OUTER", "INNER", "SECOND"}
    assert ids["INNER"]["nested"] == "yes" and ids["INNER"]["attributes"] == "COMMON"
    assert ids["OUTER"]["nested"] == "no" and ids["SECOND"]["nested"] == "no"
    assert not scan.problems


def test_end_program_without_open_program_is_a_problem() -> None:
    scan = scan_cobol("m.cbl", _fixed("PROGRAM-ID. A.", "END PROGRAM A.", "END PROGRAM B."))
    assert "END_PROGRAM_MISMATCH" in {p.code for p in scan.problems}


def test_cobol_file_without_program_id_is_flagged() -> None:
    scan = scan_cobol("m.cbl", _fixed("PROCEDURE DIVISION.", "    STOP RUN."))
    assert [p.code for p in scan.problems] == ["NO_PROGRAM_ID"]


def test_copybook_without_program_id_is_not_flagged() -> None:
    assert not scan_cobol("c.cpy", _fixed("01 A PIC X."), copybook=True).problems


def test_cbl_option_cards_before_identification_division() -> None:
    text = "CBL XREF,SQL,LIB\n       IDENTIFICATION DIVISION.\n       PROGRAM-ID. P.\n"
    options = {f.name for f in facts(scan_cobol("p.cbl", text), "compiler-option")}
    assert {"XREF", "SQL", "LIB"} <= options


# --- COPY / includes ----------------------------------------------------------------------------------------------------


def test_copy_forms_with_library_and_replacing() -> None:
    text = _fixed("PROGRAM-ID. P.", "    COPY CUSTREC.", "    COPY ACCTREC OF MYLIB.",
                  "    COPY PAYREC REPLACING ==:T:== BY ==WS==.", "    EXEC SQL INCLUDE EMPDCL END-EXEC.")
    scan = scan_cobol("p.cbl", text)
    assert targets(scan, "copies") == ["ACCTREC", "CUSTREC", "EMPDCL", "PAYREC"]
    by_name = {r.target: r for r in refs(scan, "copies")}
    assert by_name["ACCTREC"].qualifier == "MYLIB"
    assert dict(by_name["PAYREC"].detail)["replacing"] == "yes"
    assert by_name["EMPDCL"].clause == "EXEC SQL INCLUDE"


def test_copy_replacing_records_words_and_refuses_literals_with_the_generation_code() -> None:
    """Word operands are recorded; a literal operand is refused under generation's code.

    Criterion 8: discovery and generation refuse the literal-operand COPY the
    same way — the problem code here is exactly the code the materializer
    reports for the same statement.
    """
    text = _fixed("PROGRAM-ID. P.", "    COPY A REPLACING WS-OLD BY WS-NEW.",
                  "    COPY B REPLACING 'X' BY 'Y'.")
    scan = scan_cobol("p.cbl", text)
    by_name = {r.target: r for r in refs(scan, "copies")}
    assert dict(by_name["A"].detail)["replacing_pairs"] == "WS-OLD BY WS-NEW"
    assert "replacing_pairs" not in dict(by_name["B"].detail)
    problems = [p for p in scan.problems if p.code.startswith("COPY")]
    assert [p.code for p in problems] == ["COPYBOOK_REPLACING_UNSUPPORTED"]
    assert "REPLACING" in problems[0].message


def test_copy_replacing_leading_is_reported_and_never_guessed() -> None:
    text = _fixed("PROGRAM-ID. P.", "    COPY A REPLACING LEADING ==:T:== BY ==WS==.")
    scan = scan_cobol("p.cbl", text)
    assert [p.code for p in scan.problems] == ["COPYBOOK_REPLACING_UNSUPPORTED"]
    info = dict(refs(scan, "copies")[0].detail)
    # The clause is refused before its first pair is read: nothing is guessed.
    assert info["replacing"] == "yes" and "replacing_pairs" not in info


def test_sqlca_and_sqlda_includes_are_builtin_not_copybooks() -> None:
    scan = scan_cobol("p.cbl", _fixed("PROGRAM-ID. P.", "    EXEC SQL INCLUDE SQLCA END-EXEC."))
    assert not refs(scan, "copies")
    assert dict(facts(scan, "sql-include")[0].detail)["builtin"] == "yes"


def test_panvalet_and_librarian_include_cards() -> None:
    scan = scan_cobol("p.cbl", "       PROGRAM-ID. P.\n-INC EMPREC\n++INCLUDE DEPTREC\n")
    assert targets(scan, "copies") == ["DEPTREC", "EMPREC"]


# --- CALL ----------------------------------------------------------------------------------------------------------------


def test_static_call_cancel_and_argument_count() -> None:
    text = _fixed("PROGRAM-ID. P.", "PROCEDURE DIVISION.", "    CALL 'SUBA' USING X Y Z.", "    CANCEL 'SUBA'.")
    scan = scan_cobol("p.cbl", text)
    clauses = sorted((r.clause, r.target) for r in refs(scan, "calls"))
    assert clauses == [("CALL", "SUBA"), ("CANCEL", "SUBA")]
    assert dict(refs(scan, "calls")[0].detail)["arguments"] == "3"


def test_dynamic_call_is_followed_through_value_and_move() -> None:
    text = _fixed("PROGRAM-ID. P.", "WORKING-STORAGE SECTION.", "01  WS-PGM PIC X(8) VALUE 'FIRST'.",
                  "PROCEDURE DIVISION.", "    MOVE 'SECOND' TO WS-PGM.", "    CALL WS-PGM.")
    calls = refs(scan_cobol("p.cbl", text), "calls")
    assert sorted((c.target, c.dynamic, dict(c.detail)["value_source"]) for c in calls) == [
        ("FIRST", True, "value"), ("SECOND", True, "move")]


def test_dynamic_call_with_no_known_value_is_kept_as_an_unresolvable_target() -> None:
    calls = refs(scan_cobol("p.cbl", _fixed("PROGRAM-ID. P.", "PROCEDURE DIVISION.", "    CALL WS-UNKNOWN.")), "calls")
    assert [(c.target, c.dynamic, c.variable) for c in calls] == [("", True, "WS-UNKNOWN")]


def test_entry_point_alias_is_recorded() -> None:
    scan = scan_cobol("p.cbl", _fixed("PROGRAM-ID. P.", "PROCEDURE DIVISION.", "    ENTRY 'ALTENTRY' USING X."))
    assert [f.name for f in facts(scan, "entry-point")] == ["ALTENTRY"]


# --- files, VSAM, SORT ---------------------------------------------------------------------------------------------------


def test_select_records_organisation_keys_status_and_ddname() -> None:
    text = _fixed("PROGRAM-ID. P.", "FILE-CONTROL.", "    SELECT CUST ASSIGN TO CUSTDD ORGANIZATION IS INDEXED",
                  "      ACCESS MODE IS DYNAMIC RECORD KEY IS C-ID", "      ALTERNATE RECORD KEY IS C-NAME WITH DUPLICATES",
                  "      FILE STATUS IS FS1.", "    SELECT LOG ASSIGN TO UT-S-LOGDD.",
                  "    SELECT FLAT ASSIGN TO 'data/in.dat'", "      ORGANIZATION LINE SEQUENTIAL.",
                  "    SELECT REL ASSIGN TO RELDD", "      ORGANIZATION IS RELATIVE.")
    selects = {f.name: dict(f.detail) for f in facts(scan_cobol("p.cbl", text), "file-select")}
    assert selects["CUST"]["vsam_candidate"] == "yes" and selects["CUST"]["record_key"] == "C-ID"
    assert selects["CUST"]["alternate_keys"] == "C-NAME" and selects["CUST"]["file_status"] == "FS1"
    assert selects["LOG"]["ddname"] == "LOGDD" and selects["LOG"]["vsam_candidate"] == "no"
    assert selects["FLAT"]["literal_assign"] == "yes" and selects["FLAT"]["organization"] == "LINE SEQUENTIAL"
    assert selects["REL"]["vsam_candidate"] == "yes"


def test_literal_assign_becomes_an_external_file_reference() -> None:
    text = _fixed("PROGRAM-ID. P.", "FILE-CONTROL.", "    SELECT F ASSIGN TO 'data/in.dat'.")
    assert targets(scan_cobol("p.cbl", text), "assigns-file", "external-file") == ["data/in.dat"]


def test_sort_and_merge_verbs_are_utility_dependencies() -> None:
    text = _fixed("PROGRAM-ID. P.", "PROCEDURE DIVISION.", "    SORT SORT-FILE ON ASCENDING KEY K USING IN GIVING OUT.")
    scan = scan_cobol("p.cbl", text)
    assert targets(scan, "runs-utility") == ["SORT"] and facts(scan, "sort-verb")


# --- EXEC SQL ------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("sql, expected", [
    ("SELECT A INTO :X FROM HR.EMP E, HR.DEPT D WHERE E.D = D.ID", ["HR.DEPT", "HR.EMP"]),
    ("INSERT INTO HR.AUDIT (A) VALUES (:X)", ["HR.AUDIT"]),
    ("UPDATE HR.PAY SET G = 0 WHERE ID = :I", ["HR.PAY"]),
    ("DELETE FROM HR.OLD WHERE ID = :I", ["HR.OLD"]),
    ("SELECT A INTO :X FROM T1 INNER JOIN T2 ON T1.K = T2.K", ["T1", "T2"]),
    ("DECLARE C1 CURSOR FOR SELECT A FROM HR.CUR", ["HR.CUR"]),
    ("DECLARE HR.DECL TABLE (A INTEGER)", ["HR.DECL"]),
    ("SELECT A INTO :X FROM T1 WHERE B IN (SELECT B FROM T2)", ["T1", "T2"]),
    ("MERGE INTO HR.TGT USING HR.SRC ON 1=1 WHEN MATCHED THEN DELETE", ["HR.TGT"]),
    ("LOCK TABLE HR.LOCKED IN SHARE MODE", ["HR.LOCKED"]),
])
def test_exec_sql_tables(sql: str, expected: list[str]) -> None:
    scan = scan_cobol("p.cbl", _free("PROGRAM-ID. P.", "PROCEDURE DIVISION.", f"EXEC SQL {sql} END-EXEC."))
    assert sorted({r.target for r in refs(scan, "accesses-table")}) == expected


def test_exec_sql_operation_and_position() -> None:
    scan = scan_cobol("p.cbl", _fixed("PROGRAM-ID. P.", "PROCEDURE DIVISION.", "    EXEC SQL DELETE FROM HR.OLD END-EXEC."))
    ref = refs(scan, "accesses-table")[0]
    assert dict(ref.detail)["operation"] == "DELETE" and ref.line == 3 and ref.column > 1


def test_dynamic_sql_is_reported_as_a_dynamic_table_reference() -> None:
    scan = scan_cobol("p.cbl", _fixed("PROGRAM-ID. P.", "PROCEDURE DIVISION.",
                                      "    EXEC SQL PREPARE S1 FROM :STMT END-EXEC."))
    ref = refs(scan, "accesses-table")[0]
    assert ref.dynamic and ref.target == "" and facts(scan, "dynamic-sql")


def test_exec_sql_call_is_a_stored_procedure_reference() -> None:
    scan = scan_cobol("p.cbl", _fixed("PROGRAM-ID. P.", "PROCEDURE DIVISION.", "    EXEC SQL CALL HR.PAYPROC(:A) END-EXEC."))
    assert targets(scan, "calls", "stored-procedure") == ["HR.PAYPROC"]


def test_exec_without_end_exec_is_reported() -> None:
    scan = scan_cobol("p.cbl", _fixed("PROGRAM-ID. P.", "PROCEDURE DIVISION.", "    EXEC SQL SELECT 1 FROM T"))
    assert "EXEC_NOT_CLOSED" in {p.code for p in scan.problems}


def test_a_period_inside_exec_does_not_split_the_statement() -> None:
    scan = scan_cobol("p.cbl", _free("PROGRAM-ID. P.", "PROCEDURE DIVISION.",
                                     "EXEC SQL SELECT A INTO :X FROM HR.EMP WHERE B = 'A.B' END-EXEC."))
    assert targets(scan, "accesses-table") == ["HR.EMP"]


# --- EXEC CICS -----------------------------------------------------------------------------------------------------------


def test_exec_cics_commands_programs_files_maps_transactions_queues() -> None:
    text = _fixed("PROGRAM-ID. P.", "PROCEDURE DIVISION.",
                  "    EXEC CICS LINK PROGRAM('SUBPGM') COMMAREA(X) END-EXEC.",
                  "    EXEC CICS XCTL PROGRAM('NEXTPGM') END-EXEC.",
                  "    EXEC CICS READ FILE('CUSTFILE') INTO(R) RIDFLD(K) END-EXEC.",
                  "    EXEC CICS SEND MAP('MAP1') MAPSET('SET1') END-EXEC.",
                  "    EXEC CICS RETURN TRANSID('TRN1') END-EXEC.",
                  "    EXEC CICS WRITEQ TS QUEUE('TSQ1') FROM(R) END-EXEC.",
                  "    EXEC CICS START TRANSID('TRN2') END-EXEC.")
    scan = scan_cobol("p.cbl", text)
    assert targets(scan, "cics-link") == ["SUBPGM"] and targets(scan, "cics-xctl") == ["NEXTPGM"]
    assert targets(scan, "uses-cics-file") == ["CUSTFILE"]
    assert targets(scan, "uses-map") == ["SET1"]
    assert targets(scan, "starts-transaction") == ["TRN1", "TRN2"]
    assert targets(scan, "uses-queue") == ["TSQ1"]
    assert {f.name for f in facts(scan, "cics-command")} >= {"LINK", "XCTL", "READ", "SEND MAP", "RETURN", "WRITEQ TS"}


def test_cics_program_held_in_a_variable_follows_value() -> None:
    text = _fixed("PROGRAM-ID. P.", "WORKING-STORAGE SECTION.", "01  WS-NEXT PIC X(8) VALUE 'ROUTED'.",
                  "PROCEDURE DIVISION.", "    EXEC CICS LINK PROGRAM(WS-NEXT) END-EXEC.")
    link = refs(scan_cobol("p.cbl", text), "cics-link")[0]
    assert (link.target, link.dynamic) == ("ROUTED", True)


def test_cics_handle_does_not_invent_program_references() -> None:
    text = _fixed("PROGRAM-ID. P.", "PROCEDURE DIVISION.", "    EXEC CICS HANDLE ABEND PROGRAM('ABENDH') END-EXEC.")
    assert not refs(scan_cobol("p.cbl", text), "cics-link")


# --- IMS, MQ, runtime ----------------------------------------------------------------------------------------------------


def test_ims_calls_and_exec_dli() -> None:
    text = _fixed("PROGRAM-ID. P.", "WORKING-STORAGE SECTION.", "01  FUNC-GU PIC X(4) VALUE 'GU  '.",
                  "PROCEDURE DIVISION.", "    CALL 'CBLTDLI' USING FUNC-GU DB-PCB IO-AREA SSA1.",
                  "    EXEC DLI SCHD PSB(PAYPSB) END-EXEC.", "    EXEC DLI GU SEGMENT(EMPSEG) INTO(X) END-EXEC.")
    scan = scan_cobol("p.cbl", text)
    ims = {r.target_kind + ":" + r.target for r in refs(scan, "uses-ims")}
    assert {"ims-interface:CBLTDLI", "ims-psb:PAYPSB", "ims-segment:EMPSEG"} <= ims
    call = next(r for r in refs(scan, "uses-ims") if r.target == "CBLTDLI")
    assert dict(call.detail)["function_value"] == "GU  " and dict(call.detail)["pcb"] == "DB-PCB"


def test_mq_calls_and_queue_names() -> None:
    text = _fixed("PROGRAM-ID. P.", "PROCEDURE DIVISION.", "    MOVE 'PAY.REQUEST.Q' TO MQOD-OBJECTNAME.",
                  "    CALL 'MQOPEN' USING HCONN MQOD OPTS HOBJ CC RC.", "    CALL 'MQGET' USING HCONN HOBJ.")
    scan = scan_cobol("p.cbl", text)
    assert targets(scan, "uses-mq") == ["MQGET", "MQOPEN"]
    assert targets(scan, "uses-queue", "mq-queue") == ["PAY.REQUEST.Q"]


def test_runtime_library_calls_are_not_program_edges() -> None:
    text = _fixed("PROGRAM-ID. P.", "PROCEDURE DIVISION.", "    CALL 'CEEDATE' USING A B C.",
                  "    CALL 'CBL_OPEN_FILE' USING A.", "    CALL 'SYSTEM' USING 'ls -l'.", "    CALL 'DSNTIAR' USING SQLCA.")
    scan = scan_cobol("p.cbl", text)
    assert not refs(scan, "calls")
    assert targets(scan, "uses-runtime") == ["CBL_OPEN_FILE", "CEEDATE", "DSNTIAR", "SYSTEM"]
    assert [f.name for f in facts(scan, "os-command")] == ["ls -l"]


def test_environment_access_is_recorded() -> None:
    scan = scan_cobol("p.cbl", _fixed("PROGRAM-ID. P.", "PROCEDURE DIVISION.", "    ACCEPT X FROM ENVIRONMENT 'DB_HOST'."))
    assert [f.name for f in facts(scan, "environment")] == ["DB_HOST"]


# --- dialects ------------------------------------------------------------------------------------------------------------


def test_dialect_signals_are_recorded_with_hints() -> None:
    text = _fixed("PROGRAM-ID. P.", "DATA DIVISION.", "WORKING-STORAGE SECTION.", "01 N PIC S9(4) COMP-5.",
                  "PROCEDURE DIVISION.", "    ALTER P1 TO PROCEED TO P2.", "    GOBACK.")
    signals = {f.name: dict(f.detail)["hint"] for f in facts(scan_cobol("p.cbl", text), "dialect-signal")}
    assert signals["ALTER"] == "legacy-cobol74" and signals["COMP-5"] == "extension" and "GOBACK" in signals


def test_scanner_is_deterministic_and_input_order_independent() -> None:
    text = _fixed("PROGRAM-ID. P.", "PROCEDURE DIVISION.", "    CALL 'B'.", "    CALL 'A'.", "    COPY Z.", "    COPY Y.")
    first, second = scan_cobol("p.cbl", text), scan_cobol("p.cbl", text)
    assert first.refs == second.refs and first.facts == second.facts
    assert first.refs == sorted(first.refs)


# --- access modes: the relation names the entity, the mode names the operation (Layer 3) ---------------


@pytest.mark.parametrize("sql, mode", [
    ("SELECT A FROM HR.RD", "read"),
    ("INSERT INTO HR.INS (A) VALUES (1)", "write"),
    ("UPDATE HR.WR SET A = 0", "write"),
    ("DELETE FROM HR.DL WHERE A = 1", "write"),
    ("MERGE INTO HR.MG USING HR.SRC ON 1=1 WHEN MATCHED THEN DELETE", "read-write"),
    ("LOCK TABLE HR.LK IN SHARE MODE", "update"),
])
def test_exec_sql_sets_the_mode_of_the_table_it_touches(sql: str, mode: str) -> None:
    scan = scan_cobol("p.cbl", _free("PROGRAM-ID. P.", "PROCEDURE DIVISION.", f"EXEC SQL {sql} END-EXEC."))
    found = refs(scan, "accesses-table")
    assert found and {r.mode for r in found} == {mode}, [(r.target, r.mode) for r in found]


def test_a_statement_that_touches_no_rows_carries_no_mode_rather_than_a_guessed_one() -> None:
    scan = scan_cobol("p.cbl", _free("PROGRAM-ID. P.", "PROCEDURE DIVISION.",
                                      "EXEC SQL DECLARE HR.CUR CURSOR FOR SELECT A FROM HR.RD END-EXEC."))
    found = refs(scan, "accesses-table")
    assert found and {r.mode for r in found} == {""}


def test_host_variables_become_bind_edges_to_the_data_item() -> None:
    text = _free("PROGRAM-ID. P.", "PROCEDURE DIVISION.",
                 "EXEC SQL SELECT A INTO :WS-A FROM HR.EMP WHERE B = :WS-B END-EXEC.")
    binds = refs(scan_cobol("p.cbl", text), "sql-binds-hostvar")
    assert [(r.target, r.target_kind, r.mode) for r in binds] == [("WS-A", "data-item", "bind"),
                                                                  ("WS-B", "data-item", "bind")]
    assert all(r.clause.startswith("EXEC SQL SELECT") for r in binds)


def test_a_host_variable_in_an_include_is_not_a_bind_edge() -> None:
    scan = scan_cobol("p.cbl", _free("PROGRAM-ID. P.", "PROCEDURE DIVISION.",
                                      "EXEC SQL INCLUDE SQLCA END-EXEC."))
    assert not refs(scan, "sql-binds-hostvar")


def test_mq_calls_carry_the_operation_they_perform_on_the_queue() -> None:
    text = _fixed("PROGRAM-ID. P.", "PROCEDURE DIVISION.",
                  "    CALL 'MQPUT' USING HCONN HOBJ.", "    CALL 'MQGET' USING HCONN HOBJ.",
                  "    CALL 'MQOPEN' USING HCONN OD.", "    CALL 'MQCLOSE' USING HCONN HOBJ.")
    modes = {r.target: r.mode for r in refs(scan_cobol("p.cbl", text), "uses-mq")}
    assert modes == {"MQPUT": "put", "MQGET": "get", "MQOPEN": "allocate", "MQCLOSE": "delete"}


def test_cics_commands_carry_the_operation_performed_on_the_resource() -> None:
    text = _fixed("PROGRAM-ID. P.", "PROCEDURE DIVISION.",
                  "    EXEC CICS READ FILE('F1') INTO(R) END-EXEC.",
                  "    EXEC CICS WRITE FILE('F2') FROM(R) END-EXEC.",
                  "    EXEC CICS REWRITE FILE('F3') FROM(R) END-EXEC.",
                  "    EXEC CICS READNEXT FILE('F4') INTO(R) END-EXEC.",
                  "    EXEC CICS WRITEQ TS QUEUE('Q1') FROM(R) END-EXEC.",
                  "    EXEC CICS READQ TS QUEUE('Q2') INTO(R) END-EXEC.",
                  "    EXEC CICS SEND MAP('M1') MAPSET('S1') END-EXEC.",
                  "    EXEC CICS RETURN TRANSID('T1') END-EXEC.")
    scan = scan_cobol("p.cbl", text)
    assert {r.target: r.mode for r in refs(scan, "uses-cics-file")} == {"F1": "read", "F2": "write",
                                                                       "F3": "update", "F4": "read"}
    assert {r.target: r.mode for r in refs(scan, "uses-queue")} == {"Q1": "put", "Q2": "get"}
    assert {r.target: r.mode for r in refs(scan, "uses-map")} == {"S1": "send"}
    assert {r.target: r.mode for r in refs(scan, "starts-transaction")} == {"T1": "execute"}


def test_dli_verbs_carry_the_operation_performed_on_the_segment() -> None:
    text = _fixed("PROGRAM-ID. P.", "PROCEDURE DIVISION.",
                  "    EXEC DLI GU SEGMENT(EMPR) INTO(X) END-EXEC.",
                  "    EXEC DLI ISRT SEGMENT(EMPW) INTO(X) END-EXEC.",
                  "    EXEC DLI REPL SEGMENT(EMU) INTO(X) END-EXEC.",
                  "    EXEC DLI DLET SEGMENT(EMPD) END-EXEC.")
    modes = {r.target: r.mode for r in refs(scan_cobol("p.cbl", text), "uses-ims", "ims-segment")}
    assert modes == {"EMPR": "read", "EMPW": "create", "EMU": "update", "EMPD": "delete"}


def test_a_mode_is_never_invented_for_a_relation_that_carries_no_operation() -> None:
    text = _fixed("PROGRAM-ID. P.", "PROCEDURE DIVISION.", "    CALL 'OTHERPGM'.", "    GOBACK.")
    assert {r.mode for r in refs(scan_cobol("p.cbl", text), "calls")} == {""}


def test_fixed_format_inline_star_gt_comment_creates_no_copy_edge() -> None:
    source = _fixed(
        "       IDENTIFICATION DIVISION.",
        "       PROGRAM-ID. A.",
        "       DATA DIVISION.",
        "       WORKING-STORAGE SECTION.",
        "       *> COPY NOPE.",
        "       01 X PIC X.  *> COPY ALSONOPE.",
        "       COPY REAL.",
    )
    scan = scan_cobol("a.cbl", source)
    assert targets(scan, "copies") == ["REAL"]
