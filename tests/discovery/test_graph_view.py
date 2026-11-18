"""The estate view of the discovery graph: structure from the graph only, proof states added by the engine."""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from engine.estate.decomposition import plan_decomposition
from engine.estate.model import BLOCKED, PARTIAL, PROVEN, UNPROVEN, build_estate_from_graph
from enterprise.discovery.graph_view import estate_from_directory, estate_from_graph, graph_from_directory

MAIN = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MAIN.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT MASTER-FILE ASSIGN TO MASTER.
           SELECT RPT-FILE ASSIGN TO RPTDD.
       DATA DIVISION.
       FILE SECTION.
       FD MASTER-FILE.
       01 M-REC PIC X(10).
       FD RPT-FILE.
       01 R-REC PIC X(10).
       WORKING-STORAGE SECTION.
           COPY EMPREC.
           COPY MISSING.
           COPY DUP.
       PROCEDURE DIVISION.
           CALL 'SUB1' USING EMP-ID.
           CALL 'NOWHERE'.
           CALL WS-DYN.
           OPEN INPUT MASTER-FILE.
           READ MASTER-FILE.
           EXEC SQL SELECT A INTO :X FROM EMPLOYEE END-EXEC.
           GOBACK.
"""
SUB1 = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SUB1.
       DATA DIVISION.
       LINKAGE SECTION.
       01 L PIC X.
       PROCEDURE DIVISION USING L.
           GOBACK.
"""
JOB = """\
//RUNJOB   JOB CLASS=A
//S1       EXEC PGM=MAIN
//MASTER   DD DSN=HR.MASTER,DISP=OLD
//OUT      DD DSN=HR.GDG(+1),DISP=(NEW,CATLG)
//S2       EXEC PGM=IEFBR14
//IN       DD DSN=HR.GDG(+1),DISP=OLD
//S3       EXEC PGM=SORT
//S4       EXEC NOPROC
//S5       EXEC MYPROC
"""
PROC = """\
//MYPROC   PROC
//P1       EXEC PGM=SUB1
//         PEND
"""


@pytest.fixture(scope="module")
def workspace(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("estate")
    files = {
        "cobol/MAIN.cbl": MAIN, "cobol/SUB1.cbl": SUB1, "jcl/RUN.jcl": JOB, "jcl/PRC.jcl": PROC,
        "copy/EMPREC.cpy": "       01 EMP-ID PIC X(5).\n       COPY INNER.\n", "copy/INNER.cpy": "       01 I PIC X.\n",
        "copy/DUP.cpy": "       01 D1 PIC X.\n", "copy2/DUP.cpy": "       01 D2 PIC X.\n",
    }
    for name, text in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


@pytest.fixture(scope="module")
def built(workspace):
    estate, document, problems = estate_from_directory(workspace)
    return estate, document, problems, {(e.source, e.relation, e.target): e for e in estate.edges}


def test_calls_carry_proof_states_from_graph_resolution(built):
    edges = built[3]
    assert edges[("PROGRAM:MAIN", "CALLS", "PROGRAM:SUB1")].proof_state == PROVEN
    assert edges[("PROGRAM:MAIN", "CALLS", "EXTERNAL_PROGRAM:NOWHERE")].proof_state == BLOCKED
    assert edges[("PROGRAM:MAIN", "CALLS", "EXTERNAL_PROGRAM:WS-DYN")].proof_state == UNPROVEN


def test_copybooks_missing_and_ambiguous_are_blocked_never_proven(built):
    edges = built[3]
    assert edges[("PROGRAM:MAIN", "INCLUDES", "COPYBOOK:EMPREC")].proof_state == PROVEN
    assert edges[("PROGRAM:MAIN", "INCLUDES", "COPYBOOK:MISSING")].proof_state == BLOCKED
    ambiguous = edges[("PROGRAM:MAIN", "INCLUDES", "COPYBOOK:DUP")]
    assert ambiguous.proof_state == BLOCKED and "ambiguous" in ambiguous.evidence
    assert "copy/DUP.cpy" in ambiguous.evidence and "copy2/DUP.cpy" in ambiguous.evidence


def test_a_copybooks_own_copy_is_an_edge_from_the_copybook(built):
    assert built[3][("COPYBOOK:EMPREC", "INCLUDES", "COPYBOOK:INNER")].proof_state == PROVEN


def test_job_steps_utilities_and_procedures(built):
    edges = built[3]
    assert edges[("JOB:RUNJOB", "RUNS", "STEP:RUNJOB.S1")].proof_state == PROVEN
    assert edges[("STEP:RUNJOB.S1", "EXECUTES", "PROGRAM:MAIN")].proof_state == PROVEN
    utility = edges[("STEP:RUNJOB.S2", "EXECUTES", "UTILITY:IEFBR14")]
    assert utility.proof_state == PARTIAL and "no IBM/JES oracle" in utility.evidence
    assert edges[("STEP:RUNJOB.S3", "EXECUTES", "EXTERNAL_PROGRAM:SORT")].proof_state == BLOCKED
    missing_proc = edges[("STEP:RUNJOB.S4", "EXECUTES", "EXTERNAL_PROGRAM:NOPROC")]
    assert missing_proc.proof_state == BLOCKED and "procedure" in missing_proc.evidence
    expanded = edges[("STEP:RUNJOB.S5", "EXECUTES", "PROGRAM:SUB1")]
    assert expanded.proof_state == PROVEN and "via procedure MYPROC" in expanded.evidence


def test_datasets_bindings_and_flows(built):
    edges = built[3]
    assert edges[("STEP:RUNJOB.S1", "USES_DATASET", "DATASET:HR.MASTER")].proof_state == PARTIAL
    gdg = edges[("STEP:RUNJOB.S1", "USES_DATASET", "DATASET:HR.GDG(+1)")]
    assert gdg.proof_state == PARTIAL and "not resolved" in gdg.evidence
    assert edges[("PROGRAM:MAIN", "BINDS", "DATASET:HR.MASTER")].proof_state == PROVEN
    assert edges[("PROGRAM:MAIN", "BINDS", "DATASET:<unbound:RPTDD>")].proof_state == BLOCKED
    assert edges[("STEP:RUNJOB.S1", "FLOWS_TO", "STEP:RUNJOB.S2")].proof_state == PARTIAL


def test_db2_reference_comes_from_the_graph_and_is_not_promoted(built):
    edge = built[3][("PROGRAM:MAIN", "USES_DB2", "DB2_TABLE:EMPLOYEE")]
    assert edge.proof_state == UNPROVEN


def test_the_ledger_overlay_supplies_state_and_reason_only(workspace):
    document, _ = graph_from_directory(workspace)
    states = {("MAIN", "DB2_TABLE", "EMPLOYEE"): (PARTIAL, "EXEC SQL on a certified subset"),
              ("MAIN", "MQ_QUEUE", "NOT-IN-GRAPH"): (BLOCKED, "ignored: the graph does not mention it")}
    estate = estate_from_graph(document, subsystem_states=states)
    edges = {(e.source, e.relation, e.target): e for e in estate.edges}
    db2 = edges[("PROGRAM:MAIN", "USES_DB2", "DB2_TABLE:EMPLOYEE")]
    assert db2.proof_state == PARTIAL and db2.evidence == "EXEC SQL on a certified subset"
    assert not any(e.relation == "USES_MQ" for e in estate.edges), "the overlay never adds structure"


def test_an_unknown_overlay_state_is_never_promoted(workspace):
    document, _ = graph_from_directory(workspace)
    estate = estate_from_graph(document, subsystem_states={("MAIN", "DB2_TABLE", "EMPLOYEE"): ("WHATEVER", "x")})
    db2 = next(e for e in estate.edges if e.relation == "USES_DB2")
    assert db2.proof_state == UNPROVEN


def test_estate_from_graph_is_pure_and_needs_no_source_files():
    document = {
        "nodes": [{"id": "program:A", "kind": "program", "origin": "input", "path": "a.cbl"},
                  {"id": "program:B", "kind": "program", "origin": "input", "path": "b.cbl"},
                  {"id": "copybook:C", "kind": "copybook", "origin": "absent"}],
        "edges": [
            {"from": "program:A", "to": "program:B", "relation": "calls", "resolution": "resolved",
             "file": "a.cbl", "line": 3, "column": 8},
            {"from": "program:A", "to": "copybook:C", "relation": "copies", "resolution": "unresolved",
             "reason": "missing-copybook", "file": "a.cbl", "line": 2, "column": 8},
        ],
    }
    estate = estate_from_graph(document)
    states = {(e.source, e.relation, e.target): e.proof_state for e in estate.edges}
    assert states == {("PROGRAM:A", "CALLS", "PROGRAM:B"): PROVEN, ("PROGRAM:A", "INCLUDES", "COPYBOOK:C"): BLOCKED}
    assert {n.id for n in estate.nodes} == {"PROGRAM:A", "PROGRAM:B", "COPYBOOK:C"}


def test_the_view_is_independent_of_graph_document_order(workspace):
    document, _ = graph_from_directory(workspace)
    first = estate_from_graph(document).to_dict()
    shuffled = dict(document, nodes=list(document["nodes"]), edges=list(document["edges"]))
    random.Random(7).shuffle(shuffled["nodes"])
    random.Random(8).shuffle(shuffled["edges"])
    assert estate_from_graph(shuffled).to_dict() == first
    assert json.dumps(first, sort_keys=True) == json.dumps(estate_from_graph(document).to_dict(), sort_keys=True)


def test_engine_entry_point_delegates_to_the_view(workspace):
    document, _ = graph_from_directory(workspace)
    assert build_estate_from_graph(document).to_dict() == estate_from_graph(document).to_dict()


def test_the_decomposition_planner_runs_on_the_graph_estate(built):
    plan = plan_decomposition(built[0])
    programs = {p for service in plan.services for p in service.programs}
    assert programs == {"PROGRAM:MAIN", "PROGRAM:SUB1"}
    assert len(plan.services) == 1, "MAIN calls SUB1, so they stay together"
    assert plan.services[0].blocked and plan.review_required


def test_scanner_problems_are_returned_not_swallowed(tmp_path):
    (tmp_path / "big.cbl").write_text("       IDENTIFICATION DIVISION.\n       PROGRAM-ID. P.\n", encoding="utf-8")
    document, problems = graph_from_directory(tmp_path)
    assert any(n["id"] == "program:P" for n in document["nodes"])
    assert isinstance(problems, list)


def test_hidden_directories_are_not_scanned(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "X.cbl").write_text("       IDENTIFICATION DIVISION.\n       PROGRAM-ID. HIDDEN.\n")
    document, _ = graph_from_directory(tmp_path)
    assert not any("HIDDEN" in n["id"] for n in document["nodes"])


def test_graph_and_legacy_copybook_resolution_agree_on_search_order_cases(tmp_path):
    """The graph (name based) and ApplicationDiscovery (directory based) must not disagree on the outcome class:
    same stem in two directories is ambiguous, a .cpy beats a .cbl of the same stem, absence is unresolved."""
    from engine.transformation.application_discovery import ApplicationDiscovery

    files = {
        "MAIN.cbl": ("       IDENTIFICATION DIVISION.\n       PROGRAM-ID. MAIN.\n       DATA DIVISION.\n"
                     "       WORKING-STORAGE SECTION.\n           COPY ONE.\n           COPY TWO.\n"
                     "           COPY THREE.\n           COPY NONE.\n       PROCEDURE DIVISION.\n           GOBACK.\n"),
        "a/ONE.cpy": "       01 A PIC X.\n", "b/one.cpy": "       01 A PIC X.\n",
        "a/TWO.cpy": "       01 A PIC X.\n", "b/TWO.cbl": "       01 A PIC X.\n",
        "a/THREE.cpy": "       01 A PIC X.\n",
    }
    for name, text in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text, encoding="utf-8")
    legacy = {c.copybook_name.upper(): c.resolution.lower()
              for unit in ApplicationDiscovery().discover(str(tmp_path)).programs for c in unit.copybooks}
    document, _ = graph_from_directory(tmp_path)
    graph = {e["to"].split(":", 1)[1]: e["resolution"] for e in document["edges"] if e["relation"] == "copies"}
    assert legacy == graph == {"ONE": "ambiguous", "TWO": "resolved", "THREE": "resolved", "NONE": "unresolved"}
