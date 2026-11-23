"""Layer 5 P6: files, VSAM, SQL and JCL relationships read from the discovery graph (design 6.2, 6.3)."""

from __future__ import annotations

import ast
import copy
import random
from pathlib import Path

import pytest

from engine.semantic_facts.build import build_semantic_facts
from engine.semantic_facts.document import verify
from engine.semantic_facts.graph_bridge import GraphView, proposed_edges
from enterprise.discovery import graph as graph_module
from enterprise.discovery.graph_view import graph_from_directory

REPO = Path(__file__).resolve().parents[2]

PROGRAM = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. P1.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT A-FILE ASSIGN TO ADD1.
           SELECT B-FILE ASSIGN TO BDD.
           SELECT V-FILE ASSIGN TO VDD ORGANIZATION IS INDEXED
               ACCESS MODE IS DYNAMIC RECORD KEY IS V-KEY.
           SELECT L-FILE ASSIGN TO 'local.dat'.
           SELECT N-FILE ASSIGN TO NOJCL.
       DATA DIVISION.
       FILE SECTION.
       FD A-FILE.
       01 A-REC PIC X(10).
       FD B-FILE.
       01 B-REC PIC X(10).
       FD V-FILE.
       01 V-REC.
          05 V-KEY PIC X(4).
       FD L-FILE.
       01 L-REC PIC X(10).
       FD N-FILE.
       01 N-REC PIC X(10).
       WORKING-STORAGE SECTION.
       01 HV PIC X(4).
       PROCEDURE DIVISION.
       MAIN.
           OPEN INPUT A-FILE.
           STOP RUN.
"""
JCL = """//J1       JOB (ACCT),'X'
//S1       EXEC PGM=P1
//BDD      DD DSN=PROD.GDG.FILE(+1),DISP=(NEW,CATLG)
//VDD      DD DSN=PROD.VSAM.CLUSTER,DISP=SHR
//NOJCL    DD DSN=PROD.PLAIN,DISP=SHR
"""
JCL_TWO_STEPS = """//J2       JOB (ACCT),'X'
//S1       EXEC PGM=P1
//ADD1     DD DSN=PROD.FIRST,DISP=SHR
//S2       EXEC PGM=P1
//ADD1     DD DSN=PROD.SECOND,DISP=SHR
"""


def _tree(tmp_path: Path, jcl: str = JCL, program: str = PROGRAM) -> Path:
    (tmp_path / "cobol").mkdir(parents=True)
    (tmp_path / "jcl").mkdir(parents=True)
    (tmp_path / "cobol" / "P1.cob").write_text(program, encoding="utf-8")
    (tmp_path / "jcl" / "J1.jcl").write_text(jcl, encoding="utf-8")
    return tmp_path


def _build(root: Path, **kwargs):
    document, _problems = graph_from_directory(root)
    sources = {p.relative_to(root).as_posix(): p.read_text(encoding="utf-8") for p in root.rglob("*.cob")}
    jcl = {p.relative_to(root).as_posix(): p.read_text(encoding="utf-8") for p in root.rglob("*.jcl")}
    return build_semantic_facts(sources, graph=document, jcl_sources=jcl, **kwargs), document


def _bindings(doc) -> dict[str, dict]:
    return {f["attributes"]["file"]: f for f in doc.facts if f["kind"] == "file-binding"}


def test_the_chain_select_to_dd_to_dataset_to_vsam_is_stated_with_provenance(tmp_path):
    doc, graph = _build(_tree(tmp_path))
    bound = _bindings(doc)
    vsam = bound["V-FILE"]
    assert vsam["resolution"]["state"] == "resolved" and vsam["resolution"]["candidates"] == ["dataset:PROD.VSAM.CLUSTER"]
    assert vsam["attributes"]["ddname"] == "VDD" and vsam["attributes"]["organization"] == "INDEXED"
    assert vsam["attributes"]["vsam_candidate"] == "yes" and vsam["attributes"]["job_step"] == "job:J1/S1"
    assert vsam["attributes"]["jcl_file"] == "jcl/J1.jcl" and vsam["attributes"]["jcl_line"] == "4"
    assert vsam["span"]["file"] == "cobol/P1.cob" and vsam["span"]["line"] == 8
    assert doc.header["graph_id"] == graph["header"]["graph_id"] and doc.header["graph_bound"] is True
    assert verify(doc.as_dict()) == []


def test_each_failure_mode_has_its_own_named_state(tmp_path):
    doc, _ = _build(_tree(tmp_path))
    bound = _bindings(doc)
    assert (bound["A-FILE"]["resolution"]["state"], bound["A-FILE"]["resolution"]["reason"]) == ("unresolved", "missing-dd")
    gdg = bound["B-FILE"]["resolution"]
    assert (gdg["state"], gdg["reason"]) == ("unsupported", "GDG_GENERATION_NOT_RESOLVED")
    assert bound["B-FILE"]["attributes"]["generation"] == "+1"
    assert bound["L-FILE"]["resolution"]["candidates"] == ["external-file:local.dat"]
    assert bound["L-FILE"]["attributes"]["assign_kind"] == "LITERAL"
    assert not doc.complete and doc.header["unsupported_summary"]["GDG_GENERATION_NOT_RESOLVED"] == 1


def test_a_select_nobody_binds_is_unresolved_missing_logical_file(tmp_path):
    root = _tree(tmp_path, jcl="//J1 JOB (A),'X'\n//S1 EXEC PGM=OTHER\n")
    doc, _ = _build(root)
    for file in ("N-FILE", "V-FILE"):
        res = _bindings(doc)[file]["resolution"]
        assert res["state"] == "unresolved" and res["reason"] in ("missing-logical-file", "missing-dd", "unbound-ddname")


def test_two_steps_binding_different_datasets_are_ambiguous_with_both_candidates(tmp_path):
    doc, _ = _build(_tree(tmp_path, jcl=JCL_TWO_STEPS))
    res = _bindings(doc)["A-FILE"]["resolution"]
    assert res["state"] == "ambiguous" and res["candidates"] == ["dataset:PROD.FIRST", "dataset:PROD.SECOND"]
    assert res["confidence"] == "heuristic"


def test_jcl_dd_facts_carry_the_graph_position_step_and_generation(tmp_path):
    doc, _ = _build(_tree(tmp_path))
    dd = {f["attributes"]["dd"]: f for f in doc.facts if f["kind"] == "jcl-dd-binding"}
    assert dd["VDD"]["span"]["file"] == "jcl/J1.jcl" and dd["VDD"]["span"]["line"] == 4
    assert dd["BDD"]["attributes"]["generation"] == "gdg" and dd["BDD"]["attributes"]["member"] == "+1"
    assert dd["VDD"]["attributes"]["step"] == "S1"


def test_a_non_zos_jcl_text_is_refused_by_flavour_not_read(tmp_path):
    document, _ = graph_from_directory(_tree(tmp_path))
    doc = build_semantic_facts({"cobol/P1.cob": PROGRAM}, graph=document,
                               jcl_sources={"jcl/VSE.jcl": "// JOB PAY\n// EXEC PGM=PAY\n/&\n"})
    refusal = [f for f in doc.facts if f["kind"] == "refusal" and f["attributes"].get("flavour")]
    assert [f["attributes"]["flavour"] for f in refusal] == ["VSE"] and not doc.complete
    assert doc.header["unsupported_summary"]["JCL_FLAVOUR_UNSUPPORTED"] == 1


def test_sql_tables_and_host_variables_come_from_graph_and_symbols():
    root = REPO / "fixtures" / "workload-db2" / "cobol"
    document, _ = graph_from_directory(root)
    sources = {p.relative_to(root).as_posix(): p.read_text(encoding="utf-8", errors="replace") for p in root.rglob("*.cob")}
    doc = build_semantic_facts(sources, graph=document)
    tables = [f for f in doc.facts if f["kind"] == "sql-table"]
    assert tables and {f["attributes"]["table"] for f in tables} == {"table:ACCOUNT"}
    assert {f["resolution"]["reason"] for f in tables} == {"external-table"}      # the graph's own verdict, kept
    hostvars = [f for f in doc.facts if f["kind"] == "sql-host-var"]
    graph_unresolved = [f for f in hostvars if f["attributes"]["graph_resolution"] == "unresolved"]
    assert graph_unresolved and all(f["resolution"]["state"] == "resolved" for f in graph_unresolved), \
        "Layer 5 resolves host variables the graph could not"


def test_without_a_graph_no_external_fact_is_claimed(tmp_path):
    root = _tree(tmp_path)
    plain = build_semantic_facts({"cobol/P1.cob": PROGRAM})
    assert not [f for f in plain.facts if f["kind"] in ("file-binding", "sql-table", "jcl-dd-binding", "sql-host-var")]
    assert plain.header["graph_bound"] is False and plain.header["graph_id"] == ""
    bound, _ = _build(root)
    assert bound.semantic_id != plain.semantic_id


def test_a_graph_document_is_read_only(tmp_path):
    root = _tree(tmp_path)
    document, _ = graph_from_directory(root)
    before = copy.deepcopy(document)
    build_semantic_facts({"cobol/P1.cob": PROGRAM}, graph=document, jcl_sources={})
    assert document == before


def test_the_document_is_deterministic_with_a_graph(tmp_path):
    root = _tree(tmp_path)
    first, _ = _build(root)
    second, _ = _build(root)
    assert first.canonical() == second.canonical()
    document, _ = graph_from_directory(root)
    sources = {"cobol/P1.cob": PROGRAM, "cobol/Z.cob": PROGRAM.replace("P1", "Z9")}
    items = list(sources.items())
    random.Random(1).shuffle(items)
    assert build_semantic_facts(sources, graph=document).canonical() == build_semantic_facts(dict(items), graph=document).canonical()


def test_editing_the_select_changes_the_binding(tmp_path):
    base, _ = _build(_tree(tmp_path / "a"))
    edited, _ = _build(_tree(tmp_path / "b", program=PROGRAM.replace("SELECT V-FILE ASSIGN TO VDD", "SELECT V-FILE ASSIGN TO ADD1")))
    assert _bindings(base)["V-FILE"]["resolution"] != _bindings(edited)["V-FILE"]["resolution"]


# --- the graph proposal ------------------------------------------------------------------------------------------

NESTED = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. NEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 A PIC 9(3).
       01 B PIC 9(3).
       PROCEDURE DIVISION.
       MAIN.
           IF A > 1
               MOVE A TO B
               PERFORM SUB1
           END-IF.
           STOP RUN.
       SUB1.
           ADD 1 TO B.
"""


def test_the_proposal_has_exact_positions_and_cannot_become_a_graph_edge_by_accident(tmp_path):
    (tmp_path / "NEST.cob").write_text(NESTED, encoding="utf-8")
    document, _ = graph_from_directory(tmp_path)
    before = copy.deepcopy(document)
    doc_facts = build_semantic_facts({"NEST.cob": NESTED}, graph=document)
    # the programs the document was built from
    from engine.semantic_facts.build import build_program_facts

    program = build_program_facts("NEST.cob", NESTED)
    proposal = proposed_edges([program], GraphView(document))
    edges = proposal["edges"]
    assert edges and all(e["file"] == "NEST.cob" and e["line"] >= 1 and e["column"] >= 1 for e in edges)
    assert {e["relation"] for e in edges} >= {"performs", "reads-item", "writes-item"}
    assert any(e["relation"] == "writes-item" and e["to"] == "data-item:NEST/B" and e["line"] == 10 for e in edges)
    assert all(e["rule"] == "l5-proposed" and e["rule"] not in graph_module.RESOLVER_RULES for e in edges)
    assert document == before, "proposing changes nothing: graph_id is untouched"
    assert proposal["already_in_graph"] < len(edges), "some proposed edges are new to the graph"
    assert doc_facts.complete


def test_a_fact_without_an_exact_span_is_counted_never_emitted():
    from engine.semantic_facts.build import build_program_facts

    twice = NESTED.replace("MOVE A TO B", "MOVE A TO A")        # the token occurs twice on its line: no exact span
    proposal = proposed_edges([build_program_facts("T.cbl", twice)])
    assert proposal["unplaced"] >= 1
    assert all(e["column"] >= 1 and not (e["line"] == 10 and e["to"] == "data-item:NEST/A") for e in proposal["edges"])


# --- the import boundary ------------------------------------------------------------------------------------------

#: What ``engine/semantic_facts`` may import from discovery: the graph encoder, the graph view / graph document access and
#: the source policy.  Anything else (scanners, resolvers, readers) would be a second authority.
ALLOWED_DISCOVERY_IMPORTS = {"enterprise.discovery.graph", "enterprise.discovery.graph_view",
                             "enterprise.discovery.kg_query", "enterprise.discovery.source_policy"}


def test_semantic_facts_imports_only_the_allowed_discovery_modules():
    imported: set[str] = set()
    for path in sorted((REPO / "engine" / "semantic_facts").glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("enterprise"):
                imported.add(node.module)
            elif isinstance(node, ast.Import):
                imported.update(a.name for a in node.names if a.name.startswith("enterprise"))
    assert imported <= ALLOWED_DISCOVERY_IMPORTS, imported - ALLOWED_DISCOVERY_IMPORTS


def test_the_engine_never_imports_a_source_scanner_or_a_second_reader():
    forbidden = ("scan_cobol", "scan_jcl", "cobol_text", "textio", "resolve")
    for path in sorted((REPO / "engine" / "semantic_facts").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        assert not any(f"enterprise.discovery.{name}" in text for name in forbidden), path.name


def test_a_step_the_graph_could_not_bind_is_kept_beside_the_datasets_it_did_bind():
    root = REPO / "fixtures" / "enterprise" / "payroll-batch"
    document, _ = graph_from_directory(root)
    sources = {p.relative_to(root).as_posix(): p.read_text(encoding="utf-8") for p in root.rglob("*.cob")}
    doc = build_semantic_facts(sources, graph=document)
    rptprt = next(f for f in doc.facts if f["kind"] == "file-binding" and f["attributes"]["program"] == "RPTPRT")
    assert rptprt["attributes"]["unresolved_steps"] == "job:COPYJOB/RPT"
    assert rptprt["resolution"]["state"] == "ambiguous"
