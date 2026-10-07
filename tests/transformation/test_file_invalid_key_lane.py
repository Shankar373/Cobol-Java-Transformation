"""Phase D Task 3 — VSAM/files lane: deterministic INVALID KEY proof boundary.

Scope (supported deterministic subset only):
- Single-file CLOSE, OPEN INPUT/OUTPUT/I-O/EXTEND.
- READ [NEXT] [KEY IS k] [INTO w] with AT END / NOT AT END / INVALID KEY /
  NOT INVALID KEY bodies closed by END-READ or the terminating period.
- WRITE / REWRITE [FROM f] with INVALID KEY / NOT INVALID KEY (END-WRITE,
  END-REWRITE).
- START file KEY IS [=, >, >=, <, <=] key with INVALID KEY / NOT INVALID
  KEY (END-START).
- DELETE file [RECORD] with INVALID KEY / NOT INVALID KEY (END-DELETE).

Explicitly NOT claimed (remain UNAVAILABLE / unsupported, fail-closed):
- VSAM/KSDS/RRDS equivalence: the Java runtime is a TreeMap-backed
  ``CobolFileIo`` emulation (``Java Map != VSAM``).  Status codes
  (00/10/22/23) and cursor positioning are proven; mainframe VSAM
  behavior is not.
- Alternate keys, multi-file CLOSE, relational-word START operators
  (GREATER/LESS/EQUAL): diagnosed UNSUPPORTED, never silently mapped.
- JCL/JES, DB2 runtime, CICS TS: untouched by this lane (separate lanes,
  ``SQLite != DB2``, ``Spring Batch != JES/zOS``, ``CICS seam != CICS TS``).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from engine.modernization.capability_analyzer import CapabilityLevel
from engine.transformation.cobol_parser import CobolParser
from engine.transformation.cobol_to_java_mapping import (
    map_cobol_program_to_java,
)
from engine.transformation.diagnostics import DiagnosticCode
from engine.transformation.file_io_support_template import COBOL_FILE_IO_JAVA
from engine.transformation.ir import (
    CloseStatement,
    DeleteStatement,
    DisplayStatement,
    OpenStatement,
    ReadStatement,
    RewriteStatement,
    StartStatement,
    WriteStatement,
)
from engine.transformation.java_ir import (
    JavaAssignment,
    JavaIf,
    JavaLiteral,
    JavaMethodCall,
)
from engine.transformation.semantic_capability import (
    IR_TYPE_TO_CONSTRUCT,
    ir_covers,
    scan_constructs,
)

FIXTURES = Path(__file__).parent.parent.parent / "fixtures"


def _parse_procedure_body(source: str):
    """Parse source and return the flat statement list of MAIN-PARA."""
    program = CobolParser().parse(source)
    assert program.paragraphs, "no paragraphs parsed"
    return program, program.paragraphs[0].statements


def _stmts_of_type(statements, cls):
    return [s for s in statements if isinstance(s, cls)]


def _walk_java(node, seen: list | None = None) -> list:
    """Collect every dataclass IR node in a Java AST subtree."""
    if seen is None:
        seen = []
    if isinstance(node, (list, tuple)):
        for item in node:
            _walk_java(item, seen)
        return seen
    if hasattr(node, "__dataclass_fields__"):
        seen.append(node)
        for field_name in node.__dataclass_fields__:
            _walk_java(getattr(node, field_name), seen)
        return seen
    return seen


def _literal_values(node) -> set:
    return {
        n.value
        for n in _walk_java(node)
        if isinstance(n, JavaLiteral)
    }


def _java_ifs(java_program) -> list:
    nodes = _walk_java(java_program.java_class.methods)
    return [n for n in nodes if isinstance(n, JavaIf)]


# ---------------------------------------------------------------------------
# Unit tests — parser populates the deterministic subset
# ---------------------------------------------------------------------------

class TestInvalidKeyParserUnit:
    def test_write_invalid_key_body(self):
        source = """IDENTIFICATION DIVISION.
PROGRAM-ID. T.
PROCEDURE DIVISION.
MAIN-PARA.
    WRITE IDX-REC
        INVALID KEY
            DISPLAY "DUP"
    END-WRITE.
    STOP RUN.
"""
        _, statements = _parse_procedure_body(source)
        writes = _stmts_of_type(statements, WriteStatement)
        assert len(writes) == 1
        assert writes[0].record_name == "IDX-REC"
        assert writes[0].file_name == "IDX-FILE"
        assert len(writes[0].invalid_key_body) == 1
        assert isinstance(writes[0].invalid_key_body[0], DisplayStatement)

    def test_write_from_field_and_not_invalid_key(self):
        source = """IDENTIFICATION DIVISION.
PROGRAM-ID. T.
PROCEDURE DIVISION.
MAIN-PARA.
    WRITE IDX-REC FROM WS-REC
        NOT INVALID KEY
            DISPLAY "OK"
    END-WRITE.
    STOP RUN.
"""
        _, statements = _parse_procedure_body(source)
        writes = _stmts_of_type(statements, WriteStatement)
        assert len(writes) == 1
        assert writes[0].from_field == "WS-REC"
        assert len(writes[0].not_invalid_key_body) == 1
        assert writes[0].invalid_key_body == ()

    def test_read_key_next_into_and_both_clauses(self):
        source = """IDENTIFICATION DIVISION.
PROGRAM-ID. T.
PROCEDURE DIVISION.
MAIN-PARA.
    READ IDX-FILE NEXT RECORD KEY IS IDX-KEY INTO WS-REC
        AT END
            DISPLAY "EOF"
        INVALID KEY
            DISPLAY "BAD KEY"
    END-READ.
    STOP RUN.
"""
        _, statements = _parse_procedure_body(source)
        reads = _stmts_of_type(statements, ReadStatement)
        assert len(reads) == 1
        read = reads[0]
        assert read.file_name == "IDX-FILE"
        assert read.read_next is True
        assert read.key == "IDX-KEY"
        assert read.into_field == "WS-REC"
        assert len(read.at_end_body) == 1
        assert len(read.invalid_key_body) == 1

    def test_start_operators_and_invalid_key(self):
        for operator in ("=", ">", ">=", "<", "<="):
            source = f"""IDENTIFICATION DIVISION.
PROGRAM-ID. T.
PROCEDURE DIVISION.
MAIN-PARA.
    START IDX-FILE KEY {operator} IDX-KEY
        INVALID KEY
            DISPLAY "NO SUCH KEY"
    END-START.
    STOP RUN.
"""
            _, statements = _parse_procedure_body(source)
            starts = _stmts_of_type(statements, StartStatement)
            assert len(starts) == 1, operator
            assert starts[0].file_name == "IDX-FILE"
            assert starts[0].operator == operator, operator
            assert starts[0].key == "IDX-KEY", operator
            assert len(starts[0].invalid_key_body) == 1, operator

    def test_rewrite_and_delete_invalid_key(self):
        source = """IDENTIFICATION DIVISION.
PROGRAM-ID. T.
PROCEDURE DIVISION.
MAIN-PARA.
    REWRITE IDX-REC
        INVALID KEY
            DISPLAY "REWRITE BAD"
    END-REWRITE.
    DELETE IDX-FILE RECORD
        INVALID KEY
            DISPLAY "DELETE BAD"
    END-DELETE.
    STOP RUN.
"""
        _, statements = _parse_procedure_body(source)
        rewrites = _stmts_of_type(statements, RewriteStatement)
        deletes = _stmts_of_type(statements, DeleteStatement)
        assert len(rewrites) == 1
        assert rewrites[0].record_name == "IDX-REC"
        assert len(rewrites[0].invalid_key_body) == 1
        assert len(deletes) == 1
        assert deletes[0].file_name == "IDX-FILE"
        assert len(deletes[0].invalid_key_body) == 1

    def test_close_and_open_io_modes(self):
        source = """IDENTIFICATION DIVISION.
PROGRAM-ID. T.
PROCEDURE DIVISION.
MAIN-PARA.
    OPEN I-O IDX-FILE.
    CLOSE IDX-FILE.
    OPEN EXTEND IDX-FILE.
    STOP RUN.
"""
        _, statements = _parse_procedure_body(source)
        opens = _stmts_of_type(statements, OpenStatement)
        closes = _stmts_of_type(statements, CloseStatement)
        assert [o.mode for o in opens] == ["I-O", "EXTEND"]
        assert [o.file_name for o in opens] == ["IDX-FILE", "IDX-FILE"]
        assert len(closes) == 1
        assert closes[0].file_name == "IDX-FILE"

    def test_quoted_invalid_key_literal_is_not_a_clause(self):
        """Regression: DISPLAY "… INVALID KEY …" bodies must be preserved.

        The header scanner masks quoted literals; otherwise the body line is
        misclassified as a clause header and silently dropped.
        """
        source = """IDENTIFICATION DIVISION.
PROGRAM-ID. T.
PROCEDURE DIVISION.
MAIN-PARA.
    START IDX-FILE KEY = IDX-KEY
        INVALID KEY
            DISPLAY "START = K999 INVALID KEY STATUS=" WS-FILE-STATUS
    END-START.
    STOP RUN.
"""
        _, statements = _parse_procedure_body(source)
        starts = _stmts_of_type(statements, StartStatement)
        assert len(starts) == 1
        body = starts[0].invalid_key_body
        assert len(body) == 1
        assert isinstance(body[0], DisplayStatement)
        assert "WS-FILE-STATUS" in body[0].parts

    def test_inline_invalid_key_on_verb_line(self):
        source = """IDENTIFICATION DIVISION.
PROGRAM-ID. T.
PROCEDURE DIVISION.
MAIN-PARA.
    WRITE IDX-REC INVALID KEY DISPLAY "DUP".
    STOP RUN.
"""
        program, statements = _parse_procedure_body(source)
        del program
        writes = _stmts_of_type(statements, WriteStatement)
        assert len(writes) == 1
        assert len(writes[0].invalid_key_body) == 1


# ---------------------------------------------------------------------------
# Semantic tests — mapper emits the status-code branches
# ---------------------------------------------------------------------------

_FILE_PROGRAM = """IDENTIFICATION DIVISION.
PROGRAM-ID. SEM.
ENVIRONMENT DIVISION.
INPUT-OUTPUT SECTION.
FILE-CONTROL.
    SELECT IDX-FILE ASSIGN TO "SEM.DAT"
        ORGANIZATION IS INDEXED
        RECORD KEY IS IDX-KEY
        ACCESS MODE IS DYNAMIC
        FILE STATUS IS WS-STATUS.
DATA DIVISION.
FILE SECTION.
FD IDX-FILE.
01 IDX-REC.
   05 IDX-KEY PIC X(4).
   05 IDX-DATA PIC X(20).
WORKING-STORAGE SECTION.
01 WS-STATUS PIC X(2) VALUE "00".
PROCEDURE DIVISION.
MAIN-PARA.
"""


def _map_body_tail(tail: str):
    program = CobolParser().parse(_FILE_PROGRAM + tail + "\n    STOP RUN.\n")
    return map_cobol_program_to_java(program)


class TestInvalidKeyMapperSemantic:
    def test_write_emits_duplicate_key_branch(self):
        java_program = _map_body_tail(
            '    WRITE IDX-REC\n'
            '        INVALID KEY\n'
            '            DISPLAY "DUP"\n'
            '    END-WRITE.'
        )
        branches = [
            node for node in _java_ifs(java_program)
            if "22" in _literal_values(node.condition)
        ]
        assert branches, "expected a JavaIf branch on status 22 (duplicate key)"
        fail_text = repr(branches[0].then_body)
        assert "DUP" in fail_text

    def test_read_key_miss_emits_not_found_branch(self):
        java_program = _map_body_tail(
            '    READ IDX-FILE KEY IS IDX-KEY\n'
            '        INVALID KEY\n'
            '            DISPLAY "MISS"\n'
            '    END-READ.'
        )
        assignments = [
            node for node in _walk_java(java_program.java_class.methods)
            if isinstance(node, JavaAssignment)
        ]
        miss = [
            a for a in assignments
            if getattr(a.target, "__str__", lambda: "")() == "WS_STATUS"
            and "23" in _literal_values(a.expression)
        ]
        assert miss, "expected FILE STATUS assignment of 23 on key miss"
        fail_ifs = [
            node for node in _java_ifs(java_program)
            if "MISS" in repr(node)
        ]
        assert fail_ifs, "expected the INVALID KEY body in the failure branch"

    def test_start_miss_emits_not_found_branch(self):
        java_program = _map_body_tail(
            '    START IDX-FILE KEY = IDX-KEY\n'
            '        INVALID KEY\n'
            '            DISPLAY "NOPE"\n'
            '    END-START.'
        )
        branches = [
            node for node in _java_ifs(java_program)
            if "23" in _literal_values(node.condition)
        ]
        assert branches, "expected a JavaIf branch on status 23 (START miss)"
        assert "NOPE" in repr(branches[0].then_body)

    def test_delete_miss_emits_not_found_branch(self):
        java_program = _map_body_tail(
            '    DELETE IDX-FILE RECORD\n'
            '        INVALID KEY\n'
            '            DISPLAY "GONE"\n'
            '    END-DELETE.'
        )
        branches = [
            node for node in _java_ifs(java_program)
            if "23" in _literal_values(node.condition)
        ]
        assert branches, "expected a JavaIf branch on status 23 (DELETE miss)"
        assert "GONE" in repr(branches[0].then_body)

    def test_no_invalid_key_means_no_status_branch(self):
        """A clause-less WRITE must not gain a synthetic 22 branch."""
        java_program = _map_body_tail("    WRITE IDX-REC.")
        branches = [
            node for node in _java_ifs(java_program)
            if "22" in _literal_values(node.condition)
        ]
        assert branches == []


# ---------------------------------------------------------------------------
# Negative tests — fail-closed boundaries, no fake equivalence
# ---------------------------------------------------------------------------

class TestInvalidKeyNegative:
    def test_start_relational_word_is_unsupported_and_fail_closed(self):
        source = """IDENTIFICATION DIVISION.
PROGRAM-ID. T.
PROCEDURE DIVISION.
MAIN-PARA.
    START IDX-FILE KEY IS GREATER THAN IDX-KEY
        INVALID KEY
            DISPLAY "X"
    END-START.
    STOP RUN.
"""
        parser = CobolParser()
        program = parser.parse(source)
        starts = [
            s for s in program.paragraphs[0].statements
            if isinstance(s, StartStatement)
        ]
        assert len(starts) == 1
        # Never silently normalised to "=": the operator passes through so the
        # runtime yields status 23 (observable INVALID KEY).
        assert starts[0].operator not in ("=", ">", ">=", "<", "<=", "")
        warnings = [
            d for d in parser.diagnostics.warnings
            if d.code is DiagnosticCode.UNSUPPORTED_CONSTRUCT
        ]
        assert any("RELATIONAL-WORD" in d.message.upper() for d in warnings)

    def test_unclosed_clause_warns_and_keeps_partial_body(self):
        # No terminating period and no END-WRITE: the clause stays open to
        # end-of-input, which must warn (fail-closed visibility).
        source = """IDENTIFICATION DIVISION.
PROGRAM-ID. T.
PROCEDURE DIVISION.
MAIN-PARA.
    WRITE IDX-REC
        INVALID KEY
            DISPLAY "PARTIAL"
    STOP RUN"""
        parser = CobolParser()
        program = parser.parse(source)
        writes = [
            s for s in program.paragraphs[0].statements
            if isinstance(s, WriteStatement)
        ]
        assert len(writes) == 1
        # Fail-closed: the partial body is kept (never silently completed).
        # NOTE: the period rule (pre-existing collector semantics, same as
        # AT END) places the period-terminated STOP RUN inside the open
        # clause; the UNSUPPORTED_CONSTRUCT warning makes the loss visible.
        body = writes[0].invalid_key_body
        assert isinstance(body[0], DisplayStatement)
        assert body[0].parts == ('"PARTIAL"',)
        warnings = [
            d for d in parser.diagnostics.warnings
            if d.code is DiagnosticCode.UNSUPPORTED_CONSTRUCT
        ]
        assert any("END-WRITE" in d.message for d in warnings)

    def test_multi_file_close_warns_and_closes_first_only(self):
        source = """IDENTIFICATION DIVISION.
PROGRAM-ID. T.
PROCEDURE DIVISION.
MAIN-PARA.
    CLOSE FILE-A FILE-B.
    STOP RUN.
"""
        parser = CobolParser()
        program = parser.parse(source)
        closes = [
            s for s in program.paragraphs[0].statements
            if isinstance(s, CloseStatement)
        ]
        assert len(closes) == 1
        assert closes[0].file_name == "FILE-A"
        warnings = [
            d for d in parser.diagnostics.warnings
            if d.code is DiagnosticCode.UNSUPPORTED_CONSTRUCT
        ]
        assert any("MULTIPLE FILES" in d.message.upper() for d in warnings)

    def test_sequential_rewrite_fails_closed_with_status_23(self):
        """Sequential REWRITE has no CobolFileIo path: status 23, no silence."""
        source = """IDENTIFICATION DIVISION.
PROGRAM-ID. T.
ENVIRONMENT DIVISION.
INPUT-OUTPUT SECTION.
FILE-CONTROL.
    SELECT SEQ-FILE ASSIGN TO "SEQ.DAT"
        ORGANIZATION IS SEQUENTIAL
        FILE STATUS IS WS-S.
DATA DIVISION.
FILE SECTION.
FD SEQ-FILE.
01 SEQ-REC PIC X(10).
WORKING-STORAGE SECTION.
01 WS-S PIC X(2).
PROCEDURE DIVISION.
MAIN-PARA.
    REWRITE SEQ-REC
        INVALID KEY
            DISPLAY "BAD"
    END-REWRITE.
    STOP RUN.
"""
        program = CobolParser().parse(source)
        java_program = map_cobol_program_to_java(program)
        nodes = _walk_java(java_program.java_class.methods)
        assigns_23 = [
            n for n in nodes
            if isinstance(n, JavaAssignment) and "23" in _literal_values(n.expression)
        ]
        assert assigns_23, "sequential REWRITE must surface status 23"
        calls = [
            n for n in nodes
            if isinstance(n, JavaMethodCall) and n.method_name == "rewrite"
        ]
        assert calls == [], "sequential REWRITE must not call CobolFileIo.rewrite"


# ---------------------------------------------------------------------------
# Runtime proof — the shipped CobolFileIo template on a real JVM.
# NOT VSAM equivalence: proves the documented status/cursor contract of the
# TreeMap-backed emulation only (00 ok / 22 duplicate / 23 not-found /
# null at EOF-or-missing).
# ---------------------------------------------------------------------------

_DRIVER = r"""
public class FileIoProof {
    static int failures = 0;

    static void check(String label, Object actual, Object expected) {
        boolean ok = actual == null ? expected == null : actual.equals(expected);
        System.out.println(label + " actual=" + actual + " expected=" + expected
            + " " + (ok ? "OK" : "FAIL"));
        if (!ok) {
            failures++;
        }
    }

    public static void main(String[] args) throws Exception {
        String base = args[0];
        String idx = base + "/idx.dat";
        check("openOut", CobolFileIo.open(idx, "OUTPUT", 4), "00");
        check("writeK1", CobolFileIo.write(idx, "K001DATA-ONE", 4), "00");
        check("writeK2", CobolFileIo.write(idx, "K002DATA-TWO", 4), "00");
        check("writeDup", CobolFileIo.write(idx, "K001DATA-DUP", 4), "22");
        check("close1", CobolFileIo.close(idx), "00");
        check("openIO", CobolFileIo.open(idx, "I-O", 4), "00");
        String hit = CobolFileIo.readKey(idx, "K001");
        check("readKeyHit", hit != null && hit.startsWith("K001"), true);
        check("readKeyMiss", CobolFileIo.readKey(idx, "K999"), null);
        check("startHit", CobolFileIo.start(idx, "=", "K002"), "00");
        check("startMiss", CobolFileIo.start(idx, "=", "K999"), "23");
        check("startGe", CobolFileIo.start(idx, ">=", "K002"), "00");
        check("rewriteHit", CobolFileIo.rewrite(idx, "K002DATA-2NEW", 4), "00");
        check("rewriteMiss", CobolFileIo.rewrite(idx, "K999DATA-NONE", 4), "23");
        check("deleteHit", CobolFileIo.delete(idx, "K001", 4), "00");
        check("deleteMiss", CobolFileIo.delete(idx, "K001", 4), "23");
        check("close2", CobolFileIo.close(idx), "00");

        String rel = base + "/rel.dat";
        check("relOpen", CobolFileIo.open(rel, "OUTPUT", -1), "00");
        check("relWrite1", CobolFileIo.write(rel, "REL-ONE", 1), "00");
        check("relWrite2", CobolFileIo.write(rel, "REL-TWO", 2), "00");
        check("relRead", CobolFileIo.readRelative(rel, 2), "REL-TWO");
        check("relReadMiss", CobolFileIo.readRelative(rel, 9), null);
        check("relRewrite", CobolFileIo.rewrite(rel, "REL-2NEW", 2), "00");
        check("relRewriteMiss", CobolFileIo.rewrite(rel, "X", 9), "23");
        check("relDelete", CobolFileIo.deleteRelative(rel, 1), "00");
        check("relDeleteMiss", CobolFileIo.deleteRelative(rel, 1), "23");

        String seq = base + "/seq.dat";
        check("seqOpenOut", CobolFileIo.open(seq, "OUTPUT", 0), "00");
        check("seqWrite", CobolFileIo.write(seq, "LINE-1", 0), "00");
        check("seqClose", CobolFileIo.close(seq), "00");
        check("seqOpenIn", CobolFileIo.open(seq, "INPUT", 0), "00");
        check("seqRead", CobolFileIo.read(seq), "LINE-1");
        check("seqEof", CobolFileIo.read(seq), null);
        check("seqClose2", CobolFileIo.close(seq), "00");
        check("missingOpen", CobolFileIo.open(base + "/nope.dat", "INPUT", 0), "23");

        if (failures > 0) {
            System.out.println("FAILURES=" + failures);
            System.exit(1);
        }
        System.out.println("ALL-RUNTIME-CHECKS-OK");
    }
}
"""


class TestInvalidKeyJavaRuntime:
    def test_shipped_template_status_contract_on_jvm(self, tmp_path):
        javac = shutil.which("javac")
        java = shutil.which("java")
        if not javac or not java:
            pytest.skip("no JVM toolchain available for runtime proof")
        (tmp_path / "CobolFileIo.java").write_text(
            COBOL_FILE_IO_JAVA, encoding="utf-8"
        )
        (tmp_path / "FileIoProof.java").write_text(_DRIVER, encoding="utf-8")
        compile_proc = subprocess.run(
            [javac, "-encoding", "UTF-8", "CobolFileIo.java", "FileIoProof.java"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert compile_proc.returncode == 0, compile_proc.stderr
        run_proc = subprocess.run(
            [java, "FileIoProof", str(tmp_path)],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert run_proc.returncode == 0, run_proc.stdout + run_proc.stderr
        assert "ALL-RUNTIME-CHECKS-OK" in run_proc.stdout
        assert "FAIL" not in run_proc.stdout.replace("FAILURES", "")
        # Spot-check the load-bearing status boundaries in the runtime log.
        assert "writeDup actual=22 expected=22 OK" in run_proc.stdout
        assert "startMiss actual=23 expected=23 OK" in run_proc.stdout
        assert "deleteMiss actual=23 expected=23 OK" in run_proc.stdout
        assert "seqEof actual=null expected=null OK" in run_proc.stdout


# ---------------------------------------------------------------------------
# Integration + evidence — fixtures cross the proof boundary
# ---------------------------------------------------------------------------

def _ir_keys_and_scopes(program) -> tuple[set, set]:
    from engine.transformation.ir import (
        DeleteStatement as _Del,
        ReadStatement as _Read,
        RewriteStatement as _Rw,
        StartStatement as _Start,
        WriteStatement as _Write,
    )

    seen: set = set()
    keys: set = set()

    def _walk(stmt) -> None:
        name = type(stmt).__name__
        seen.add(name)
        key = IR_TYPE_TO_CONSTRUCT.get(name)
        if key is not None:
            keys.add(key)
        for attr in ("invalid_key_body", "not_invalid_key_body"):
            if getattr(stmt, attr, None):
                seen.add("InvalidKeyScope")
                break
        if isinstance(stmt, _Read):
            nested = (
                stmt.at_end_body + stmt.not_at_end_body
                + stmt.invalid_key_body + stmt.not_invalid_key_body
            )
        elif isinstance(stmt, (_Write, _Start, _Rw, _Del)):
            nested = stmt.invalid_key_body + stmt.not_invalid_key_body
        else:
            nested = getattr(stmt, "body", ()) or ()
            if isinstance(nested, tuple):
                pass
            else:
                nested = ()
            nested = nested + tuple(getattr(stmt, "then_body", ()) or ())
            nested = nested + tuple(getattr(stmt, "else_body", ()) or ())
        for child in nested:
            _walk(child)

    for paragraph in program.paragraphs:
        for statement in paragraph.statements:
            _walk(statement)
    return keys, seen


class TestInvalidKeyIntegrationEvidence:
    @pytest.mark.parametrize(
        "fixture,expected_verbs",
        [
            (
                "workload-start-invalidkey/cobol/MAIN.cob",
                {"READ", "WRITE", "OPEN", "CLOSE", "START", "DELETE"},
            ),
            (
                "workload-indexed-rewrite-delete-start/cobol/MAIN.cob",
                {"READ", "WRITE", "OPEN", "CLOSE", "START", "DELETE", "REWRITE"},
            ),
        ],
    )
    def test_fixture_verbs_reach_ir_with_invalid_key_scope(
        self, fixture, expected_verbs
    ):
        source = (FIXTURES / fixture).read_text()
        assert "INVALID KEY" in scan_constructs(source)
        program = CobolParser().parse(source)
        keys, seen = _ir_keys_and_scopes(program)
        assert expected_verbs <= keys, f"verbs dropped: {expected_verbs - keys}"
        assert ir_covers("INVALID KEY", keys | seen), (
            "INVALID KEY source has no InvalidKeyScope IR — the clause was dropped"
        )

    def test_capability_levels_are_ir_backed_not_source_only(self):
        """Every file verb in the fixture must resolve to the registry IR
        level (SUPPORTED), never to the source-only UNSUPPORTED fallback."""
        from engine.transformation.semantic_capability import CONSTRUCT_REGISTRY

        source = (
            FIXTURES / "workload-indexed-rewrite-delete-start/cobol/MAIN.cob"
        ).read_text()
        program = CobolParser().parse(source)
        keys, seen = _ir_keys_and_scopes(program)
        for construct in ("READ", "WRITE", "OPEN", "CLOSE", "START",
                          "REWRITE", "DELETE"):
            assert construct in keys, f"{construct} has no IR"
            assert CONSTRUCT_REGISTRY[construct].level is CapabilityLevel.SUPPORTED
        assert ir_covers("INVALID KEY", keys | seen)

    def test_other_lanes_untouched(self):
        """This lane changes nothing about JCL/DB2/CICS/external boundaries."""
        from engine.sql.dialect import Db2CompatibilityLevel
        from engine.transformation.semantic_capability import CONSTRUCT_REGISTRY

        assert CONSTRUCT_REGISTRY["EXEC CICS"].level is CapabilityLevel.UNSUPPORTED
        assert CONSTRUCT_REGISTRY["EXEC SQL"].level is CapabilityLevel.UNSUPPORTED
        assert CONSTRUCT_REGISTRY["SORT"].level is CapabilityLevel.UNSUPPORTED
        # DB2 runtime proof remains a strictly stronger, unavailable-by-design
        # claim above portable SQLite execution (SQLite != DB2).
        assert (
            Db2CompatibilityLevel.DB2_RUNTIME_VERIFIED.rank
            > Db2CompatibilityLevel.PORTABLE_EXECUTABLE.rank
        )
