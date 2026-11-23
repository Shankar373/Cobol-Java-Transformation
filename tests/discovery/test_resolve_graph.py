"""Reference resolution and the dependency graph: resolved/external/ambiguous/unresolved, DD binding, invariants."""

from __future__ import annotations

import hashlib
import json
import random

import pytest

from enterprise.discovery.classify import classify
from enterprise.discovery.discover import scan_file
from enterprise.discovery.graph import UNRESOLVED_REASONS, DependencyGraph, Edge, Node
from enterprise.discovery.inventory import FileRecord
from enterprise.discovery.resolve import build_graph
from tests.discovery.helpers import _fixed

PROGRAM = _fixed("IDENTIFICATION DIVISION.", "PROGRAM-ID. {name}.", "PROCEDURE DIVISION.", "{body}")


def program(name: str, *body: str) -> str:
    return _fixed("IDENTIFICATION DIVISION.", f"PROGRAM-ID. {name}.", "PROCEDURE DIVISION.", *(f"    {b}" for b in body),
                  "    GOBACK.")


def records(files: dict[str, str]) -> list[FileRecord]:
    out = []
    for path, text in files.items():
        cls = classify(path, text).cls
        out.append(FileRecord(path, hashlib.sha256(text.encode()).hexdigest(), len(text), cls, scan=scan_file(path, cls, text)))
    return out


def edges(build, relation=None, src=None):
    return [e for e in build.graph.edges() if (relation is None or e.relation == relation) and (src is None or e.src == src)]


def one(build, relation, target):
    found = [e for e in edges(build, relation) if e.dst.split(":", 1)[1] == target]
    assert len(found) == 1, found
    return found[0]


# --- copybooks --------------------------------------------------------------------------------------------------------


def test_copybook_resolution_states() -> None:
    cpy = _fixed("01 A PIC X.")
    build = build_graph(records({
        "src/P.cbl": program("P", "COPY GOOD.", "COPY GONE.", "COPY DFHAID.", "COPY TWIN.", "COPY OTHER OF LIBB."),
        "cpy/GOOD.cpy": cpy, "cpy/TWIN.cpy": cpy, "alt/TWIN.cpy": cpy,
        "liba/OTHER.cpy": cpy, "libb/OTHER.cpy": cpy,
    }))
    assert one(build, "copies", "GOOD").resolution == "resolved"
    gone = one(build, "copies", "GONE")
    assert (gone.resolution, gone.reason) == ("unresolved", "missing-copybook") and UNRESOLVED_REASONS[gone.reason]
    assert one(build, "copies", "DFHAID").resolution == "external"
    twin = one(build, "copies", "TWIN")
    assert twin.resolution == "ambiguous" and set(twin.candidates) == {"cpy/TWIN.cpy", "alt/TWIN.cpy"}
    assert one(build, "copies", "OTHER").resolution == "resolved"  # the library qualifier picks libb


def test_a_copybook_in_the_same_directory_beats_one_elsewhere() -> None:
    cpy = _fixed("01 A PIC X.")
    build = build_graph(records({"a/P.cbl": program("P", "COPY C1."), "a/C1.cpy": cpy, "b/C1.cpy": cpy}))
    edge = one(build, "copies", "C1")
    assert edge.resolution == "resolved" and build.graph.nodes[edge.dst].path == "a/C1.cpy"


def test_nested_copybook_references_are_edges_from_the_copybook() -> None:
    build = build_graph(records({"c/OUTER.cpy": _fixed("01 A.", "    COPY INNER."), "c/INNER.cpy": _fixed("05 B PIC X.")}))
    edge = one(build, "copies", "INNER")
    assert edge.resolution == "resolved" and edge.file == "c/OUTER.cpy"


def test_a_program_file_used_as_a_copybook_resolves_by_name() -> None:
    build = build_graph(records({"s/P.cbl": program("P", "COPY SHARED."), "s/SHARED.cbl": program("SHARED")}))
    edge = one(build, "copies", "SHARED")
    assert edge.resolution == "resolved" and dict(edge.detail)["matched_by"] == "program-file-used-as-copybook"


# --- programs ---------------------------------------------------------------------------------------------------------


def test_call_resolution_states() -> None:
    build = build_graph(records({
        "a/MAIN.cbl": program("MAIN", "CALL 'SUB1'.", "CALL 'MISSING1'.", "CALL 'ASMUTIL'.", "CALL 'CEEDATE' USING X.",
                              "CALL 'DUP'."),
        "a/SUB1.cbl": program("SUB1"), "asm/ASMUTIL.asm": "ASMUTIL CSECT\n BR 14\n",
        "x/DUP.cbl": program("DUP"), "y/DUP2.cbl": program("DUP"),
    }))
    assert one(build, "calls", "SUB1").resolution == "resolved"
    assert one(build, "calls", "ASMUTIL").resolution == "resolved"
    assert one(build, "calls", "DUP").resolution == "ambiguous"
    missing = one(build, "calls", "MISSING1")
    assert (missing.resolution, missing.reason) == ("unresolved", "missing-program")
    assert one(build, "uses-runtime", "CEEDATE").resolution == "external"


def test_dynamic_call_candidates_are_edges_marked_dynamic_and_unknown_ones_are_tracked() -> None:
    src = _fixed("IDENTIFICATION DIVISION.", "PROGRAM-ID. DYN.", "WORKING-STORAGE SECTION.",
                 "01  WS-P PIC X(8) VALUE 'TARGET'.", "PROCEDURE DIVISION.", "    CALL WS-P.", "    CALL WS-NOPE.")
    build = build_graph(records({"d/DYN.cbl": src, "d/TARGET.cbl": program("TARGET")}))
    target = one(build, "calls", "TARGET")
    assert target.resolution == "resolved" and target.dynamic and target.variable == "WS-P"
    unknown = [e for e in edges(build, "calls") if e.dst == "dynamic:WS-NOPE"]
    assert unknown[0].reason == "dynamic-target" and not UNRESOLVED_REASONS["dynamic-target"]


def test_nested_programs_do_not_make_a_call_ambiguous() -> None:
    nested = _fixed("PROGRAM-ID. OUTER.", "PROGRAM-ID. HELPER.", "END PROGRAM HELPER.", "END PROGRAM OUTER.")
    build = build_graph(records({"n/OUTER.cbl": nested, "n/HELPER.cbl": program("HELPER"), "n/M.cbl": program("M", "CALL 'HELPER'.")}))
    assert one(build, "calls", "HELPER").resolution == "resolved"


def test_defines_edges_tie_files_to_programs_with_positions() -> None:
    build = build_graph(records({"a/P.cbl": program("P")}))
    edge = one(build, "defines", "P")
    assert (edge.src, edge.file, edge.line) == ("file:a/P.cbl", "a/P.cbl", 2)


# --- JCL ------------------------------------------------------------------------------------------------------------


def test_jcl_step_resolution_states() -> None:
    jcl = ("//J JOB\n//S1 EXEC PGM=PAYROLL\n//S2 EXEC PGM=IDCAMS\n//S3 EXEC PGM=NOSUCH\n//S4 EXEC PROC=MYPROC\n"
           "//S5 EXEC PROC=NOPROC\n//S6 EXEC PROC=IGYWCL\n//  INCLUDE MEMBER=GONE\n//  INCLUDE MEMBER=COMMON\n")
    build = build_graph(records({"j/J.jcl": jcl, "s/PAYROLL.cbl": program("PAYROLL"),
                                 "p/MYPROC.prc": "//MYPROC PROC\n//X EXEC PGM=IEFBR14\n// PEND\n", "j/COMMON.jcl": "//C EXEC PGM=IEFBR14\n"}))
    assert one(build, "executes", "PAYROLL").resolution == "resolved"
    assert one(build, "executes", "IDCAMS").resolution == "external"
    assert one(build, "executes", "NOSUCH").reason == "missing-program"
    assert one(build, "executes", "MYPROC").resolution == "resolved"
    assert one(build, "executes", "NOPROC").reason == "missing-procedure"
    assert one(build, "executes", "IGYWCL").resolution == "external"
    assert one(build, "includes", "GONE").reason == "missing-include"
    assert one(build, "includes", "COMMON").resolution == "resolved"


# --- DD binding and VSAM ----------------------------------------------------------------------------------------------


COBOL_WITH_FILES = _fixed("IDENTIFICATION DIVISION.", "PROGRAM-ID. FILER.", "ENVIRONMENT DIVISION.", "FILE-CONTROL.",
                          "    SELECT CUST ASSIGN TO CUSTDD ORGANIZATION IS INDEXED", "      RECORD KEY IS K.",
                          "    SELECT LOG ASSIGN TO LOGDD.", "    SELECT NOJCL ASSIGN TO ABSENT.", "PROCEDURE DIVISION.",
                          "    GOBACK.")


def test_dd_binding_resolves_datasets_through_the_step_that_runs_the_program() -> None:
    jcl = ("//J JOB\n//S0 EXEC PGM=IDCAMS\n//SYSIN DD *\n DEFINE CLUSTER (NAME(PROD.CUST) INDEXED KEYS(4 0))\n/*\n"
           "//S1 EXEC PGM=FILER\n//CUSTDD DD DSN=PROD.CUST,DISP=SHR\n//LOGDD DD SYSOUT=*\n")
    build = build_graph(records({"c/FILER.cbl": COBOL_WITH_FILES, "j/J.jcl": jcl}))
    cust = [e for e in edges(build, "uses-dataset") if dict(e.detail).get("ddname") == "CUSTDD"][0]
    assert cust.dst == "vsam-cluster:PROD.CUST" and dict(cust.detail)["vsam"] == "yes"
    assert (cust.file, cust.line) == ("c/FILER.cbl", 5) and dict(cust.detail)["jcl_file"] == "j/J.jcl"
    log = [e for e in edges(build, "uses-dataset") if dict(e.detail).get("ddname") == "LOGDD"][0]
    assert log.dst == "sysout:SYSOUT" and log.resolution == "resolved"
    absent = [e for e in edges(build, "assigns-file") if e.dst == "dd:ABSENT"][0]
    assert absent.reason == "missing-dd"
    assert build.bindings[0]["program"] == "FILER" and build.bindings[0]["vsam"] is True


def test_a_program_no_job_runs_has_unbound_ddnames_which_are_tracked() -> None:
    build = build_graph(records({"c/FILER.cbl": COBOL_WITH_FILES}))
    unbound = [e for e in edges(build, "assigns-file")]
    assert {e.reason for e in unbound} == {"unbound-ddname"} and len(unbound) == 3
    assert not any(UNRESOLVED_REASONS[e.reason] for e in unbound)


def test_proc_steps_take_job_level_dd_overrides() -> None:
    proc = "//RUNPROC PROC\n//STEP1 EXEC PGM=FILER\n//CUSTDD DD DSN=DEFAULT.CUST,DISP=SHR\n//LOGDD DD DUMMY\n//ABSENT DD DUMMY\n// PEND\n"
    job = "//J JOB\n//GO EXEC PROC=RUNPROC\n//STEP1.CUSTDD DD DSN=PROD.CUST,DISP=SHR\n"
    build = build_graph(records({"c/FILER.cbl": COBOL_WITH_FILES, "p/RUNPROC.prc": proc, "j/J.jcl": job}))
    cust = [e for e in edges(build, "uses-dataset") if dict(e.detail).get("ddname") == "CUSTDD"]
    assert [e.dst for e in cust] == ["dataset:PROD.CUST"]


# --- tables, CICS, builds ------------------------------------------------------------------------------------------------


def test_db2_table_resolution() -> None:
    build = build_graph(records({
        "s/P.cbl": program("P", "EXEC SQL SELECT A INTO :X FROM HR.EMP END-EXEC.",
                           "EXEC SQL UPDATE HR.GONE SET A = 1 END-EXEC."),
        "d/S.sql": "CREATE TABLE HR.EMP (A INT);\n"}))
    assert one(build, "accesses-table", "HR.EMP").resolution == "resolved"
    gone = one(build, "accesses-table", "HR.GONE")
    assert gone.reason == "external-table" and not UNRESOLVED_REASONS[gone.reason]


def test_cics_map_transaction_and_link_resolution() -> None:
    csd = "//J JOB\n//S1 EXEC PGM=DFHCSDUP\n//SYSIN DD *\n  DEFINE TRANSACTION(TRN1) GROUP(G) PROGRAM(CICSP)\n/*\n"
    build = build_graph(records({
        "s/CICSP.cbl": program("CICSP", "EXEC CICS SEND MAP('M1') MAPSET('SET1') END-EXEC.",
                               "EXEC CICS SEND MAP('M2') MAPSET('NOSET') END-EXEC.",
                               "EXEC CICS RETURN TRANSID('TRN1') END-EXEC.", "EXEC CICS START TRANSID('TRN9') END-EXEC.",
                               "EXEC CICS LINK PROGRAM('NOLINK') END-EXEC."),
        "b/SET1.bms": "SET1 DFHMSD TYPE=MAP\nM1 DFHMDI SIZE=(24,80)\n DFHMSD TYPE=FINAL\n", "j/CSD.jcl": csd}))
    assert one(build, "uses-map", "SET1").resolution == "resolved"
    assert one(build, "uses-map", "NOSET").reason == "missing-mapset"
    assert one(build, "starts-transaction", "TRN1").resolution == "resolved"
    assert one(build, "starts-transaction", "TRN9").reason == "undefined-transaction"
    assert one(build, "cics-link", "NOLINK").reason == "missing-program"


def test_build_script_references_resolve_to_files_or_are_missing_sources() -> None:
    make = "all:\n\tcobc -x -I cpy src/PAYROLL.cbl src/GONE.cbl\n"
    build = build_graph(records({"Makefile": make, "src/PAYROLL.cbl": program("PAYROLL"), "cpy/A.cpy": _fixed("01 A PIC X.")}))
    assert one(build, "builds", "src/PAYROLL.cbl").resolution == "resolved"
    assert one(build, "builds", "src/GONE.cbl").reason == "missing-source"
    assert one(build, "uses-library", "cpy").resolution == "resolved"


def test_compile_step_member_must_exist() -> None:
    jcl = "//J JOB\n//C EXEC PGM=IGYCRCTL\n//SYSIN DD DSN=PROD.SRC(PAYROLL),DISP=SHR\n//C2 EXEC PGM=IGYCRCTL\n//SYSIN DD DSN=PROD.SRC(LOST),DISP=SHR\n"
    build = build_graph(records({"j/B.jcl": jcl, "s/PAYROLL.cbl": program("PAYROLL")}))
    assert one(build, "builds", "PAYROLL").resolution == "resolved"
    assert one(build, "builds", "LOST").reason == "missing-source"


# --- invariants -------------------------------------------------------------------------------------------------------


def test_every_edge_has_a_source_span_and_every_unresolved_edge_a_known_reason() -> None:
    graph = DependencyGraph()
    with pytest.raises(ValueError):
        graph.add_edge(Edge("a", "b", "calls", "CALL", "", 1, 1))
    with pytest.raises(ValueError):
        graph.add_edge(Edge("a", "b", "calls", "CALL", "f", 0, 1))
    with pytest.raises(ValueError):
        graph.add_edge(Edge("a", "b", "calls", "CALL", "f", 1, 1, "unresolved", "because"))
    with pytest.raises(ValueError):
        graph.add_edge(Edge("a", "b", "calls", "CALL", "f", 1, 1, "resolved", "missing-program"))


def test_unresolved_edges_stay_in_the_edge_list_and_in_the_unresolved_projection() -> None:
    build = build_graph(records({"a/P.cbl": program("P", "CALL 'GONE'.")}))
    payload = build.graph.to_dict()
    unresolved = [e for e in payload["edges"] if e["resolution"] == "unresolved"]
    assert unresolved == payload["unresolved"] and unresolved[0]["blocking"] is True
    assert payload["stats"]["blocking_unresolved"] == 1


def test_graph_is_independent_of_input_order() -> None:
    files = {"a/P.cbl": program("P", "CALL 'Q'.", "COPY C1."), "a/Q.cbl": program("Q"), "a/C1.cpy": _fixed("01 A PIC X."),
             "j/J.jcl": "//J JOB\n//S EXEC PGM=P\n", "d/S.sql": "CREATE TABLE T (A INT);\n"}
    base = json.dumps(build_graph(records(files)).graph.to_dict(), sort_keys=True)
    items = list(files.items())
    for seed in range(5):
        random.Random(seed).shuffle(items)
        assert json.dumps(build_graph(records(dict(items))).graph.to_dict(), sort_keys=True) == base


def test_nodes_that_exist_in_the_upload_carry_path_and_hash() -> None:
    build = build_graph(records({"a/P.cbl": program("P")}))
    node = build.graph.nodes["program:P"]
    assert node.origin == "input" and node.path == "a/P.cbl" and len(node.sha256) == 64
    assert Node("x", "k").as_dict() == {"id": "x", "kind": "k", "origin": "input"}


# --- DB2 BIND MEMBER: a relation the graph does not know must never abort the whole build ------------------------------


def test_db2_bind_member_reaches_the_graph_without_aborting_the_build() -> None:
    jcl = ("//J JOB\n//S1 EXEC PGM=IKJEFT01\n//SYSTSIN DD *\n  DSN SYSTEM(DB2P)\n"
           "  BIND PLAN(NEWPLAN) MEMBER(DBRM1,DBRM2)\n  END\n/*\n")
    build = build_graph(records({"jcl/BIND.jcl": jcl}))  # raised ValueError("unknown relation 'binds'") before the fix
    members = {e.dst for e in edges(build, "uses-db2") if e.dst.startswith("dbrm:")}
    assert members == {"dbrm:DBRM1", "dbrm:DBRM2"}
    for edge in edges(build, "uses-db2"):
        assert edge.file == "jcl/BIND.jcl" and edge.line >= 1 and edge.column >= 1  # provenance is mandatory
    assert not [e for e in build.graph.edges() if e.relation == "binds"]  # the vocabulary stays closed


def test_every_relation_a_scanner_emits_is_in_the_closed_vocabulary() -> None:
    """Guard the producer/vocabulary seam itself: any JCL utility ref must be constructible as an Edge."""
    from enterprise.discovery.graph import EDGE_RELATIONS
    jcl = ("//J JOB\n//S1 EXEC PGM=IKJEFT01\n//SYSTSIN DD *\n  DSN SYSTEM(DB2P)\n  RUN PROGRAM(P1) PLAN(PL1)\n"
           "  BIND PLAN(PL2) MEMBER(M1)\n  END\n/*\n//S2 EXEC PGM=IDCAMS\n//SYSIN DD *\n"
           "  DEFINE CLUSTER (NAME(A.B) INDEXED KEYS(4 0) RECORDSIZE(80 80))\n  REPRO INFILE(IN1) OUTFILE(OUT1)\n/*\n"
           "//S3 EXEC PGM=SORT\n//SYSIN DD *\n  SORT FIELDS=(1,6,CH,A)\n/*\n")
    scan = scan_file("jcl/ALL.jcl", classify("jcl/ALL.jcl", jcl).cls, jcl)
    assert {r.relation for r in scan.refs} <= set(EDGE_RELATIONS)
