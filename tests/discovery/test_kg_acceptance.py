"""Layer 3 knowledge-graph acceptance criteria (docs/discovery/KNOWLEDGE_GRAPH_AUDIT.md), exercised on the realistic
multi-application corpus in ``tests/fixtures/estate_multiapp``.

Covered here: 1 (determinism), 2 (edge provenance), 4 (control flow / file verbs / SQL / CICS / IMS / MQ), 5 (COPY
REPLACING), 6 (library order), 7 (copybook impact against an independent brute force), 8 (diff), 10 (lossless store
import).  Criterion 11 lives in ``test_kg_scale_benchmark.py``; 3 and 9 belong to the engine and traceability work.

Every ``xfail(strict=True)`` below marks a *genuine* production gap with the real assertion intact; when the gap is
fixed the strict xfail fails and the mark must be removed.
"""

from __future__ import annotations

import json
import random
import shutil
from pathlib import Path

import pytest

from enterprise.discovery.applications import build_applications, link_applications
from enterprise.discovery.classify import classify
from enterprise.discovery.compilers import ToolchainConfig
from enterprise.discovery.discover import DiscoveryRequest, discover, scan_file
from enterprise.discovery.graph import (
    CONFIDENCE_VALUES, RESOLVER_RULES, Edge, graph_id_of, stamp_graph_id,
)
from enterprise.discovery.inventory import FileRecord
from enterprise.discovery.kg_export import canonical_json
from enterprise.discovery.kg_query import diff, impact
from enterprise.discovery.kg_store import KGStore
from enterprise.discovery.resolve import build_graph
from tests.discovery.helpers import _fixed

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "estate_multiapp"
NO_TOOLCHAIN = ToolchainConfig(backend="none")


# --- helpers ---------------------------------------------------------------------------------------------------------


def corpus() -> dict[str, str]:
    """The fixture as ``{posix path: text}``, sorted by path."""
    return {p.relative_to(FIXTURE).as_posix(): p.read_bytes().decode("utf-8")
            for p in sorted(FIXTURE.rglob("*")) if p.is_file()}


def document_of(files: dict[str, str]) -> dict:
    """Scan -> resolve -> applications -> document, in exactly the order ``files`` iterates."""
    records = []
    for path, text in files.items():
        cls = classify(path, text).cls
        records.append(FileRecord(path, "0" * 64, len(text), cls, scan=scan_file(path, cls, text)))
    graph = build_graph(records).graph
    link_applications(graph, build_applications(records, graph))
    document = graph.to_dict()
    stamp_graph_id(document)
    return document


@pytest.fixture(scope="module")
def files() -> dict[str, str]:
    return corpus()


@pytest.fixture(scope="module")
def doc(files) -> dict:
    return document_of(files)


def edges_of(document: dict, relation: str | None = None, src: str | None = None, dst: str | None = None) -> list[dict]:
    return [e for e in document["edges"] if (relation is None or e["relation"] == relation)
            and (src is None or e["from"] == src) and (dst is None or e["to"] == dst)]


def line_of(files: dict[str, str], path: str, needle: str) -> int:
    """1-based line of the first line of ``path`` containing ``needle`` (the test derives lines from the source)."""
    for number, line in enumerate(files[path].splitlines(), 1):
        if needle in line:
            return number
    raise AssertionError(f"{needle!r} not in {path}")


def one(document: dict, relation: str, src: str, dst: str, line: int | None = None) -> dict:
    found = [e for e in edges_of(document, relation, src, dst) if line is None or e["line"] == line]
    assert len(found) == 1, (relation, src, dst, line, found)
    return found[0]


def kind_of(document: dict) -> dict[str, str]:
    return {n["id"]: n["kind"] for n in document["nodes"]}


# --- corpus sanity ---------------------------------------------------------------------------------------------------


def test_corpus_is_a_realistic_multi_application_estate(files, doc) -> None:
    kinds = kind_of(doc)
    applications = sorted(n for n, k in kinds.items() if k == "application")
    assert len(applications) >= 3 and len(files) >= 20
    for name in ("PAYROLL", "ORDENTRY", "BILLRUN"):
        assert f"program:{name}" in kinds
    owners = {e["from"] for e in edges_of(doc, "copies", dst="copybook:CUSTREC")}
    assert {"program:PAYROLL", "program:ORDENTRY", "program:BILLRUN", "program:BILLIMS"} == owners, "shared copybook"
    twins = [p for p in files if p.endswith("/RATES.cpy")]
    assert sorted(twins) == ["libs/lib1/RATES.cpy", "libs/lib2/RATES.cpy"]


# --- criterion 1: byte-identical, order independent ------------------------------------------------------------------


@pytest.mark.parametrize("seed", [0, 1, 2, 3, 4, 5])
def test_c1_graph_and_graph_id_do_not_depend_on_file_order(files, doc, seed: int) -> None:
    items = list(files.items())
    random.Random(seed).shuffle(items)
    shuffled = document_of(dict(items))
    assert canonical_json(shuffled) == canonical_json(doc)
    assert shuffled["header"]["graph_id"] == doc["header"]["graph_id"]
    assert json.dumps(shuffled, sort_keys=True) == json.dumps(doc, sort_keys=True)


def test_c1_reversed_order_and_recorded_id_matches_the_content(files, doc) -> None:
    reversed_doc = document_of(dict(reversed(list(files.items()))))
    assert canonical_json(reversed_doc) == canonical_json(doc)
    assert doc["header"]["graph_id"] == graph_id_of(doc["nodes"], doc["edges"])
    assert len(doc["header"]["graph_id"]) == 64


def test_c1_changing_one_character_changes_the_graph_id(files, doc) -> None:
    mutated = dict(files)
    mutated["payroll/src/TAXLIB.cbl"] = mutated["payroll/src/TAXLIB.cbl"].replace("GOBACK", "STOP RUN")
    # No edge or node changes, so the id must be stable; a structural change must move it.
    assert document_of(mutated)["header"]["graph_id"] == doc["header"]["graph_id"]
    mutated["payroll/src/TAXLIB.cbl"] = mutated["payroll/src/TAXLIB.cbl"].replace(
        "PROCEDURE DIVISION.", "PROCEDURE DIVISION.\n           CALL 'PAYCALC'.")
    assert document_of(mutated)["header"]["graph_id"] != doc["header"]["graph_id"]


def _write_in_order(root: Path, items: list[tuple[str, str]]) -> Path:
    for path, text in items:
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8"))
    return root


def test_c1_two_discovery_runs_over_differently_ordered_directories_write_identical_graph_bytes(tmp_path: Path,
                                                                                               files) -> None:
    items = list(files.items())
    shuffled = list(items)
    random.Random(7).shuffle(shuffled)
    first = _write_in_order(tmp_path / "a" / "estate", items)
    second = _write_in_order(tmp_path / "b" / "other-name", shuffled)
    r1 = discover(DiscoveryRequest("directory", str(first)), tmp_path / "s1", toolchain=NO_TOOLCHAIN)
    r2 = discover(DiscoveryRequest("directory", str(second)), tmp_path / "s2", toolchain=NO_TOOLCHAIN)
    g1 = (r1.outdir / "dependency-graph.json").read_bytes()
    g2 = (r2.outdir / "dependency-graph.json").read_bytes()
    assert g1 == g2
    assert json.loads(g1)["header"]["graph_id"] == json.loads(g2)["header"]["graph_id"]
    assert r1.checkpoint.checkpoint_id == r2.checkpoint.checkpoint_id


# --- criterion 2: every edge is traceable and classified -----------------------------------------------------------------


@pytest.mark.parametrize("override", [
    {"file": ""}, {"line": 0}, {"column": 0}, {"rule": ""}, {"confidence": ""},
    {"rule": "made-up-rule"}, {"confidence": "probably"}, {"mode": "sideways"}, {"scope": "galaxy"},
    {"relation": "teleports"},
], ids=lambda o: "-".join(f"{k}={v!r}" for k, v in o.items()))
def test_c2_constructing_an_edge_without_provenance_raises(override) -> None:
    fields = dict(src="program:A", dst="program:B", relation="calls", clause="CALL", file="a.cbl", line=3, column=8,
                  rule="definition-calls", confidence="certain")
    Edge(**fields)  # the baseline is valid
    with pytest.raises(ValueError):
        Edge(**{**fields, **override})


def test_c2_an_unresolved_edge_cannot_claim_to_be_certain() -> None:
    with pytest.raises(ValueError):
        Edge("program:A", "program:X", "calls", "CALL", "a.cbl", 1, 1, "unresolved", "missing-program",
             rule="definition-calls", confidence="certain")


def test_c2_every_emitted_edge_has_file_line_column_rule_and_confidence(files, doc) -> None:
    assert len(doc["edges"]) > 150
    for edge in doc["edges"]:
        assert edge["file"] in files, edge
        assert 1 <= edge["line"] <= len(files[edge["file"]].splitlines()), edge
        assert edge["column"] >= 1, edge
        assert edge["rule"] in RESOLVER_RULES and edge["confidence"] in CONFIDENCE_VALUES, edge
        assert (edge["confidence"] == "unresolved") == (edge["resolution"] == "unresolved"), edge


def test_c2_provenance_survives_the_store(doc, tmp_path: Path) -> None:
    with KGStore(tmp_path / "kg.sqlite3") as store:
        graph_id = store.save(doc)
        rows = store.edges(graph_id, limit=None)
    assert len(rows) == len(doc["edges"])
    assert all(r["file"] and r["line"] >= 1 and r["column"] >= 1 and r["rule"] and r["confidence"] for r in rows)


# --- criterion 4: control flow, file verbs, SQL, CICS, IMS, MQ -----------------------------------------------------------


def test_c4_perform_and_go_to_edges_carry_the_right_lines(files, doc) -> None:
    path = "payroll/src/PAYROLL.cbl"
    pr = "program:PAYROLL"
    perform_read = one(doc, "performs", pr, "paragraph:PAYROLL/READ-EMP", line_of(files, path, "PERFORM READ-EMP"))
    perform_calc = one(doc, "performs", pr, "paragraph:PAYROLL/CALC-PAY", line_of(files, path, "PERFORM CALC-PAY"))
    goto = one(doc, "goes-to", pr, "paragraph:PAYROLL/FINISH-PARA", line_of(files, path, "GO TO FINISH-PARA"))
    assert dict(perform_calc["detail"])["thru"] == "CALC-EXIT"
    for edge in (perform_read, perform_calc, goto):
        assert edge["file"] == path and edge["mode"] in ("", "control") and edge["resolution"] == "resolved"
    assert one(doc, "performs", pr, "paragraph:PAYROLL/CALC-EXIT")["line"] == perform_calc["line"]


def test_c4_paragraphs_are_contained_in_their_program(files, doc) -> None:
    paragraphs = {e["to"] for e in edges_of(doc, "contains", "program:PAYROLL") if e["to"].startswith("paragraph:")}
    assert paragraphs == {f"paragraph:PAYROLL/{n}" for n in
                          ("MAIN-PARA", "READ-EMP", "CALC-PAY", "CALC-EXIT", "FINISH-PARA")}
    contain = one(doc, "contains", "program:PAYROLL", "paragraph:PAYROLL/READ-EMP")
    header = next(n for n, l in enumerate(files["payroll/src/PAYROLL.cbl"].splitlines(), 1) if l.strip() == "READ-EMP.")
    assert contain["line"] == header


def test_c4_read_write_rewrite_edges_have_modes_and_lines(files, doc) -> None:
    path = "payroll/src/PAYROLL.cbl"
    read = one(doc, "reads-file", "program:PAYROLL", "dataset:PROD.EMP.KSDS", line_of(files, path, "READ EMP-FILE"))
    rewrite = [e for e in edges_of(doc, "rewrites-file", "program:PAYROLL")]
    write = [e for e in edges_of(doc, "writes-file", "program:PAYROLL")]
    assert read["mode"] == "read" and read["resolution"] == "resolved"
    assert [(e["mode"], e["line"]) for e in rewrite] == [("update", line_of(files, path, "REWRITE CUST-REC"))]
    assert [(e["mode"], e["line"]) for e in write] == [("write", line_of(files, path, "WRITE PAY-REC"))]
    billing = "billing/src/BILLRUN.cbl"
    assert one(doc, "reads-file", "program:BILLRUN", "dataset:PROD.CUST.KSDS")["line"] == line_of(
        files, billing, "READ CUST-FILE")
    assert [e["line"] for e in edges_of(doc, "writes-file", "program:BILLRUN")] == [line_of(files, billing, "WRITE INV-REC")]


def test_c4_write_and_rewrite_resolve_to_the_file_they_write(doc) -> None:
    for program in ("PAYROLL", "BILLRUN"):
        for relation in ("writes-file", "rewrites-file"):
            for edge in edges_of(doc, relation, f"program:{program}"):
                assert edge["resolution"] != "unresolved", edge


def test_c4_perform_inside_an_inline_perform_is_found(files, doc) -> None:
    line = line_of(files, "billing/src/BILLRUN.cbl", "PERFORM WRITE-INV")
    one(doc, "performs", "program:BILLRUN", "paragraph:BILLRUN/WRITE-INV", line)


def test_c4_sql_read_and_write_are_distinguished(files, doc) -> None:
    payroll = "payroll/src/PAYROLL.cbl"
    select = one(doc, "accesses-table", "program:PAYROLL", "table:HR.EMPLOYEE", line_of(files, payroll, "SELECT NAME"))
    update = one(doc, "accesses-table", "program:PAYROLL", "table:HR.PAYSTUB", line_of(files, payroll, "UPDATE HR.PAYSTUB"))
    assert (select["mode"], dict(select["detail"])["operation"]) == ("read", "SELECT")
    assert (update["mode"], dict(update["detail"])["operation"]) == ("write", "UPDATE")
    billing = {e["line"]: e for e in edges_of(doc, "accesses-table", "program:BILLRUN", "table:BILL.INVOICE")}
    insert_line = line_of(files, "billing/src/BILLRUN.cbl", "INSERT INTO")
    select_line = line_of(files, "billing/src/BILLRUN.cbl", "SELECT TOTAL")
    assert (billing[insert_line]["mode"], billing[select_line]["mode"]) == ("write", "read")
    assert one(doc, "defines-table", "file:payroll/db/schema.sql", "table:HR.PAYSTUB")["resolution"] == "resolved"


def test_c4_cics_map_and_link_edges(files, doc) -> None:
    path = "orders/src/ORDENTRY.cbl"
    receive = one(doc, "uses-map", "program:ORDENTRY", "bms-mapset:ORDSET", line_of(files, path, "RECEIVE MAP"))
    link = one(doc, "cics-link", "program:ORDENTRY", "program:ORDPRICE", line_of(files, path, "LINK PROGRAM"))
    assert (receive["mode"], receive["resolution"]) == ("receive", "resolved")
    assert (link["mode"], link["resolution"]) == ("invoke", "resolved")
    assert one(doc, "starts-transaction", "program:ORDENTRY", "transaction:ORD1")["line"] == line_of(
        files, path, "RETURN TRANSID")


def test_c4_cics_file_commands_keep_their_own_file_line_and_mode(files, doc) -> None:
    path = "orders/src/ORDENTRY.cbl"
    read = one(doc, "uses-cics-file", "program:ORDENTRY", "cics-file:ORDFILE", line_of(files, path, "READ FILE"))
    write = one(doc, "uses-cics-file", "program:ORDENTRY", "cics-file:ORDLOG", line_of(files, path, "WRITE FILE"))
    assert (read["mode"], write["mode"]) == ("read", "write")


def test_c4_ims_calls_are_recorded_with_function_and_line(files, doc) -> None:
    path = "billing/src/BILLIMS.cbl"
    edges = [e for e in doc["edges"] if e["from"] == "program:BILLIMS" and e["relation"] in ("uses-ims", "ims-call")]
    assert {(e["line"], dict(e["detail"])["function"]) for e in edges} == {
        (line_of(files, path, "FUNC-GU"), "FUNC-GU"), (line_of(files, path, "FUNC-ISRT"), "FUNC-ISRT")}
    assert {e["to"] for e in edges} == {"ims-interface:CBLTDLI"} and all(e["resolution"] == "external" for e in edges)


def test_c4_mq_put_and_get_are_distinguished(files, doc) -> None:
    path = "billing/src/BILLMQ.cbl"
    by_target = {e["to"]: e for e in doc["edges"] if e["from"] == "program:BILLMQ" and e["relation"] in
                 ("uses-mq", "mq-put", "mq-get")}
    assert by_target["mq-interface:MQPUT"]["mode"] == "put" and by_target["mq-interface:MQGET"]["mode"] == "get"
    assert by_target["mq-interface:MQPUT"]["line"] == line_of(files, path, "'MQPUT'")
    assert by_target["mq-interface:MQGET"]["line"] == line_of(files, path, "'MQGET'")


def test_c4_unresolved_dynamic_call_is_data_not_noise(files, doc) -> None:
    path = "orders/src/ORDENTRY.cbl"
    dynamic = one(doc, "calls", "program:ORDENTRY", "dynamic:WS-DYN", line_of(files, path, "CALL WS-DYN")) \
        if edges_of(doc, "calls", "program:ORDENTRY", "dynamic:WS-DYN") else None
    candidates = [e for e in edges_of(doc, "calls", "program:ORDENTRY") if e["line"] == line_of(files, path, "CALL WS-DYN")]
    assert len(candidates) == 1, candidates
    edge = dynamic or candidates[0]
    assert (edge["resolution"], edge["reason"], edge["blocking"], edge["confidence"]) == (
        "unresolved", "dynamic-target", False, "unresolved")
    assert edge.get("dynamic") is True and edge.get("variable") == "WS-DYN"
    assert edge in doc["unresolved"]
    assert one(doc, "calls", "program:ORDENTRY", "program:ORDPRICE", line_of(files, path, "CALL WS-PGM"))[
        "resolution"] == "resolved", "a VALUE-initialised variable is resolvable"
    missing = one(doc, "calls", "program:ORDENTRY", "program:DYNLOOKUP")
    assert (missing["reason"], missing["blocking"]) == ("missing-program", True)


# --- criterion 5: COPY REPLACING --------------------------------------------------------------------------------------


def test_c5_replacing_pairs_are_recorded_in_detail(files, doc) -> None:
    payhdr = one(doc, "copies", "program:PAYROLL", "copybook:PAYHDR", line_of(files, "payroll/src/PAYROLL.cbl", "COPY PAYHDR"))
    assert dict(payhdr["detail"]) == {"replacing": "yes", "replacing_count": "1", "replacing_pairs": "HDR BY PAY"}
    tranrec = one(doc, "copies", "program:PAYROLL", "copybook:TRANREC")
    assert dict(tranrec["detail"])["replacing_pairs"] == ":TR: BY PAY"
    billing = one(doc, "copies", "program:BILLRUN", "copybook:TRANREC")
    assert dict(billing["detail"])["replacing_pairs"] == ":TR: BY INV"
    plain = one(doc, "copies", "program:PAYROLL", "copybook:CUSTREC")
    assert "replacing" not in dict(plain.get("detail", {}))


def test_c5_data_items_of_the_copybook_are_linked_to_the_including_program(files, doc) -> None:
    line = line_of(files, "payroll/src/PAYROLL.cbl", "COPY PAYHDR")
    linked = {e["to"] for e in edges_of(doc, "contains", "program:PAYROLL") if e["line"] == line}
    assert {"data-item:shared/copy/PAYHDR.cpy/HDR-DATE", "data-item:shared/copy/PAYHDR.cpy/HDR-BATCH"} <= linked
    declared = [e for e in edges_of(doc, "contains", "program:PAYROLL", "data-item:shared/copy/PAYHDR.cpy/HDR-DATE")]
    assert declared[0]["rule"] == "copy-replacing" and dict(declared[0]["detail"])["replacing_pairs"] == "HDR BY PAY"
    assert any(e["rule"] == "copy-replacing" and dict(e["detail"]).get("replacing_pair") == "HDR BY PAY"
               and e["to"].endswith("PAY-DATE") for e in edges_of(doc, "contains", "program:PAYROLL"))


def test_c5_expanded_item_ids_name_the_item_the_program_sees(doc) -> None:
    assert "data-item:PAYROLL/PAY-DATE" in {e["to"] for e in edges_of(doc, "contains", "program:PAYROLL")}
    assert not [e for e in doc["edges"] if "PAYPAY" in e["to"]]


def test_c5_colon_tagged_copybook_expands_into_the_including_program(doc) -> None:
    contained = {e["to"] for e in edges_of(doc, "contains", "program:PAYROLL")}
    assert any(node.endswith("/PAY-AMT") for node in contained), sorted(contained)


# --- criterion 6: library order -----------------------------------------------------------------------------------------


def test_c6_same_named_copybooks_keep_the_loser_in_candidates(doc) -> None:
    for program in ("PAYCALC", "ORDPRICE", "BILLRUN"):
        edge = one(doc, "copies", f"program:{program}", "copybook:RATES")
        assert {"libs/lib1/RATES.cpy", "libs/lib2/RATES.cpy"} <= set(edge["candidates"]), edge
        assert edge["resolution"] in ("ambiguous", "resolved")
        if edge["resolution"] == "ambiguous":
            assert edge["confidence"] == "heuristic"


def _billing_with_syslib_order(files: dict[str, str], first: str, second: str) -> dict:
    changed = dict(files)
    jcl = changed["billing/jcl/BILLJOB.jcl"]
    jcl = jcl.replace("ORDER=(LIBS.LIB2,LIBS.LIB1)", f"ORDER=(LIBS.{first},LIBS.{second})")
    jcl = jcl.replace("//SYSLIB   DD DSN=LIBS.LIB2,DISP=SHR\n//         DD DSN=LIBS.LIB1,DISP=SHR",
                      f"//SYSLIB   DD DSN=LIBS.{first},DISP=SHR\n//         DD DSN=LIBS.{second},DISP=SHR")
    changed["billing/jcl/BILLJOB.jcl"] = jcl
    return document_of(changed)


def test_c6_syslib_order_picks_the_winner_and_keeps_the_loser_as_a_candidate(files, doc) -> None:
    for first, second, winner, loser in (("LIB2", "LIB1", "libs/lib2/RATES.cpy", "libs/lib1/RATES.cpy"),
                                         ("LIB1", "LIB2", "libs/lib1/RATES.cpy", "libs/lib2/RATES.cpy")):
        document = doc if (first, second) == ("LIB2", "LIB1") else _billing_with_syslib_order(files, first, second)
        edge = one(document, "copies", "program:BILLRUN", "copybook:RATES")
        node = next(n for n in document["nodes"] if n["id"] == "copybook:RATES")
        assert (edge["resolution"], edge["rule"]) == ("resolved", "copy-library-order"), edge
        assert node["path"] == winner and loser in edge["candidates"] and edge["confidence"] == "derived"


# --- criterion 7: copybook impact == independent brute force ----------------------------------------------------------


def brute_force_dependants(document: dict, start: str) -> set[str]:
    """Fixpoint over the raw edge list (no BFS, no kg_query): every node that can reach ``start`` along an edge."""
    reaches = {start}
    edges = [(e["from"], e["to"]) for e in document["edges"]]
    changed = True
    while changed:
        changed = False
        for src, dst in edges:
            if dst in reaches and src not in reaches:
                reaches.add(src)
                changed = True
    return reaches - {start}


def entities(document: dict, nodes: set[str]) -> dict[str, set[str]]:
    kinds = kind_of(document)
    return {kind: {n for n in nodes if kinds.get(n) == kind} for kind in ("program", "job", "application")}


def copybook_ids(document: dict) -> list[str]:
    return sorted(n["id"] for n in document["nodes"] if n["kind"] == "copybook" and n["origin"] == "input")


def test_c7_every_copybooks_impact_equals_the_brute_force_closure(doc) -> None:
    ids = copybook_ids(doc)
    assert {"copybook:CUSTREC", "copybook:RATES", "copybook:ERRCODES", "copybook:DATEFLD"} <= set(ids)
    for copybook in ids:
        expected = brute_force_dependants(doc, copybook)
        assert impact(doc, copybook, "in") == expected, copybook
        assert entities(doc, impact(doc, copybook, "in")) == entities(doc, expected)


def test_c7_shared_copybook_reaches_programs_jobs_and_all_applications(doc) -> None:
    reached = entities(doc, impact(doc, "copybook:CUSTREC", "in"))
    assert {"program:PAYROLL", "program:ORDENTRY", "program:BILLRUN", "program:BILLIMS"} <= reached["program"]
    assert reached["job"] == {"job:PAYJOB", "job:BILLJOB"}
    all_apps = {n["id"] for n in doc["nodes"] if n["kind"] == "application"}
    assert reached["application"] == all_apps and len(all_apps) == 3
    rates = entities(doc, impact(doc, "copybook:RATES", "in"))
    assert {"program:PAYCALC", "program:ORDPRICE", "program:BILLRUN"} <= rates["program"]
    assert rates["job"] == {"job:PAYJOB", "job:BILLJOB"} and len(rates["application"]) == 3


def test_c7_impact_respects_application_boundaries_for_a_private_copybook(files, doc) -> None:
    # PAYHDR is copied by PAYROLL alone: only the payroll application and its job are affected, never orders/billing.
    reached = entities(doc, impact(doc, "copybook:PAYHDR", "in"))
    assert reached["program"] == {"program:PAYROLL"} and reached["job"] == {"job:PAYJOB"}
    apps = {n["id"]: n for n in doc["nodes"] if n["kind"] == "application"}
    assert [dict(apps[a]["detail"])["name"] for a in reached["application"]] == ["PAYJOB"]


def test_c7_impact_follows_nested_copybooks(files, doc) -> None:
    outer = {e["from"] for e in edges_of(doc, "copies", dst="copybook:CUSTREC")}
    inner_direct = {e["from"] for e in edges_of(doc, "copies", dst="copybook:DATEFLD") if e["from"].startswith("program:")}
    expected_programs = outer | inner_direct
    assert {"program:PAYROLL", "program:ORDENTRY", "program:BILLRUN", "program:BILLIMS", "program:ORDPRICE"} == expected_programs
    assert expected_programs <= impact(doc, "copybook:DATEFLD", "in")


# --- criterion 8: diff ---------------------------------------------------------------------------------------------------


def _empty(bucket: dict) -> bool:
    return not any(bucket[k] for k in ("added", "removed", "changed"))


def test_c8_diff_of_identical_input_is_empty(files, doc) -> None:
    again = document_of(files)
    result = diff(doc, again)
    assert _empty(result["nodes"]) and _empty(result["edges"])
    assert _empty(diff(doc, doc)["nodes"]) and _empty(diff(doc, doc)["edges"])


def _modified(files: dict[str, str]) -> dict[str, str]:
    changed = dict(files)
    del changed["shared/copy/PAYHDR.cpy"]  # removed: its file node and declared items disappear
    del changed["payroll/src/TAXLIB.cbl"]  # changed: still called, now unresolved
    changed["payroll/src/NEWPGM.cbl"] = _fixed(
        "IDENTIFICATION DIVISION.", "PROGRAM-ID. NEWPGM.", "PROCEDURE DIVISION.",
        "    CALL 'PAYROLL'.", "    GOBACK.")  # added
    return changed


def test_c8_diff_lists_added_removed_and_changed_nodes_and_edges(files, doc) -> None:
    after = document_of(_modified(files))
    result = diff(doc, after)
    assert "program:NEWPGM" in result["nodes"]["added"] and "file:payroll/src/NEWPGM.cbl" in result["nodes"]["added"]
    assert {"file:shared/copy/PAYHDR.cpy", "data-item:shared/copy/PAYHDR.cpy/HDR-DATE",
            "data-item:shared/copy/PAYHDR.cpy/HDR-BATCH"} <= result["nodes"]["removed"]
    assert "program:TAXLIB" in result["nodes"]["changed"], "still referenced, so it stays as an unresolved node"
    assert not result["nodes"]["added"] & result["nodes"]["removed"]
    added_calls = [k for k in result["edges"]["added"] if k.startswith("program:NEWPGM|program:PAYROLL|calls|")]
    assert len(added_calls) == 1
    changed_calls = [k for k in result["edges"]["changed"] if k.startswith("program:PAYCALC|program:TAXLIB|calls|")]
    assert len(changed_calls) == 1
    assert any(k.startswith("file:shared/copy/PAYHDR.cpy|") for k in result["edges"]["removed"])
    assert any(k.startswith("program:PAYROLL|copybook:PAYHDR|copies|") for k in result["edges"]["changed"])
    # The diff is directional and symmetric.
    reverse = diff(after, doc)
    assert reverse["nodes"]["added"] == result["nodes"]["removed"] and reverse["edges"]["added"] == result["edges"]["removed"]
    assert reverse["nodes"]["removed"] == result["nodes"]["added"] and reverse["edges"]["removed"] == result["edges"]["added"]


def test_c8_checkpoint_diff_over_real_discovery_runs(tmp_path: Path, files) -> None:
    store = tmp_path / "store"
    first = _write_in_order(tmp_path / "v1", list(files.items()))
    again = tmp_path / "v1-copy"
    shutil.copytree(first, again)
    modified = _write_in_order(tmp_path / "v2", list(_modified(files).items()))
    docs = []
    for source in (first, again, modified):
        result = discover(DiscoveryRequest("directory", str(source)), store, toolchain=NO_TOOLCHAIN)
        docs.append((result, json.loads((result.outdir / "dependency-graph.json").read_text(encoding="utf-8"))))
    (r1, g1), (r2, g2), (r3, g3) = docs
    assert r1.checkpoint.checkpoint_id == r2.checkpoint.checkpoint_id != r3.checkpoint.checkpoint_id
    assert _empty(diff(g1, g2)["nodes"]) and _empty(diff(g1, g2)["edges"])
    result = diff(g1, g3)
    assert "program:NEWPGM" in result["nodes"]["added"] and "file:shared/copy/PAYHDR.cpy" in result["nodes"]["removed"]
    assert "program:TAXLIB" in result["nodes"]["changed"]
    assert g1["header"]["graph_id"] != g3["header"]["graph_id"]


# --- criterion 10: lossless store import ---------------------------------------------------------------------------------


def test_c10_store_rows_equal_the_json_including_unresolved_and_blocking(doc, tmp_path: Path) -> None:
    with KGStore(tmp_path / "kg.sqlite3") as store:
        graph_id = store.save(doc, application="estate")
        rows = store.rows_equal(graph_id)
        counts = store.counts(graph_id)
        unresolved = store.unresolved(graph_id, limit=None)
        blocking = store.unresolved(graph_id, blocking=True, limit=None)
    assert rows == {"kg_snapshot": 1, "kg_node": len(doc["nodes"]), "kg_edge": len(doc["edges"]),
                    "kg_unresolved": len(doc["unresolved"])}
    assert counts["blocking"] == len(blocking) == sum(1 for e in doc["edges"] if e.get("blocking"))
    assert len(unresolved) == len(doc["unresolved"])
    assert {r["dst"] for r in blocking} >= {"program:DYNLOOKUP"}
    assert any(r["reason"] == "dynamic-target" for r in unresolved)


def test_c10_store_accepts_a_program_run_from_two_jobs(tmp_path: Path) -> None:
    program = _fixed("IDENTIFICATION DIVISION.", "PROGRAM-ID. SHARED.", "ENVIRONMENT DIVISION.",
                     "INPUT-OUTPUT SECTION.", "FILE-CONTROL.", "    SELECT IN-FILE ASSIGN TO INDD.",
                     "PROCEDURE DIVISION.", "    GOBACK.")
    document = document_of({
        "src/SHARED.cbl": program,
        "jcl/JOBA.jcl": "//JOBA     JOB (A),'A'\n//S1       EXEC PGM=SHARED\n//OTHER    DD DSN=A.IN,DISP=SHR\n",
        "jcl/JOBB.jcl": "//JOBB     JOB (A),'B'\n//S1       EXEC PGM=SHARED\n//OTHER    DD DSN=B.IN,DISP=SHR\n",
    })
    with KGStore(tmp_path / "kg.sqlite3") as store:
        graph_id = store.save(document)
        assert store.counts(graph_id)["edges"] == len(document["edges"])
