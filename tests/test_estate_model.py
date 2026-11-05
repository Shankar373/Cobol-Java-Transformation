"""Roadmap unit 17: the estate graph -- nodes, edges, proof states and summary (pure function)."""

from __future__ import annotations

from engine.estate.model import BLOCKED, PARTIAL, PROVEN, UNPROVEN, build_estate

DISCOVERY = {
    "cobol_programs": [
        {"program_id": "PAYROLL", "copybooks": ["EMPREC", "MISSING"],
         "calls": [{"target": "TAXCALC", "arguments": []}, {"target": "EXTLIB", "arguments": []},
                   {"target": "", "arguments": []}]},
        {"program_id": "TAXCALC", "copybooks": [], "calls": []},
    ],
    "copybooks": ["EMPREC"],
    "jcl_jobs": [{"name": "PAYJOB", "steps": [
        {"name": "S1", "program": "PAYROLL", "procedure": None},
        {"name": "S2", "program": "IEFBR14", "procedure": None},
        {"name": "S3", "program": "SORT", "procedure": None},
        {"name": "S4", "program": None, "procedure": "NOPROC"},
    ]}],
    "dataset_catalog": [
        {"dsn": "HR.MASTER", "kind": "PERMANENT",
         "uses": [{"job": "PAYJOB", "step": "S1", "dd": "MASTER", "disposition": "OLD", "role": "CONSUMER"}]},
        {"dsn": "HR.GDG(+1)", "kind": "GDG_RELATIVE",
         "uses": [{"job": "PAYJOB", "step": "S1", "dd": "OUT", "disposition": "NEW", "role": "PRODUCER"}]},
    ],
    "dd_bindings": [
        {"job": "PAYJOB", "step": "S1", "program": "PAYROLL", "file_name": "MASTER-FILE", "ddname": "MASTER",
         "dataset": "HR.MASTER", "status": "BOUND", "detail": ""},
        {"job": "PAYJOB", "step": "S1", "program": "PAYROLL", "file_name": "RPT", "ddname": "RPTDD",
         "dataset": "", "status": "UNBOUND", "detail": "no DD statement named RPTDD in step S1"},
        {"job": "PAYJOB", "step": "S1", "program": "PAYROLL", "file_name": "TMP", "ddname": "",
         "dataset": "", "status": "LITERAL_PATH", "detail": "the program names its file itself"},
        {"job": "PAYJOB", "step": "S1", "program": "PAYROLL", "file_name": "", "ddname": "SPARE",
         "dataset": "X", "status": "UNUSED_DD", "detail": ""},
    ],
    "dataset_flows": [{"from": "PAYJOB.S1", "to": "PAYJOB.S2", "dsn": "HR.MASTER"}],
}
EXTERNAL = {"PAYROLL": [
    {"dependency_id": "DB2:TABLE=EMPLOYEE", "kind": "DB2", "proof_state": "PARTIAL",
     "reason": "EXEC SQL on a certified subset"},
    {"dependency_id": "MQ:QUEUE=PAY.IN", "kind": "MQ", "proof_state": "BLOCKED", "reason": "no MQ lane"},
    {"dependency_id": "IMS:SEGMENT=EMPSEG", "kind": "DependencyKind.IMS", "proof_state": "ProofState.BLOCKED",
     "reason": "no IMS lane"},
    {"dependency_id": "CICS:FILE=ACCT", "kind": "CICS", "proof_state": "WHATEVER", "reason": "x"},
    {"dependency_id": "PARAMETER:X", "kind": "PARAMETER", "proof_state": "PROVEN", "reason": "ignored"},
]}


def _edges(estate):
    return {(e.source, e.relation, e.target): e for e in estate.edges}


def test_programs_copybooks_and_calls_carry_proof_states():
    edges = _edges(build_estate(DISCOVERY, EXTERNAL))
    assert edges[("PROGRAM:PAYROLL", "INCLUDES", "COPYBOOK:EMPREC")].proof_state == PROVEN
    assert edges[("PROGRAM:PAYROLL", "INCLUDES", "COPYBOOK:MISSING")].proof_state == BLOCKED
    assert edges[("PROGRAM:PAYROLL", "CALLS", "PROGRAM:TAXCALC")].proof_state == PROVEN
    assert edges[("PROGRAM:PAYROLL", "CALLS", "EXTERNAL_PROGRAM:EXTLIB")].proof_state == BLOCKED
    assert not any(e.target.endswith(":") for e in edges.values()), "a blank call target is dropped, not invented"


def test_jobs_steps_and_what_each_step_runs():
    edges = _edges(build_estate(DISCOVERY, EXTERNAL))
    assert edges[("JOB:PAYJOB", "RUNS", "STEP:PAYJOB.S1")].proof_state == PROVEN
    assert edges[("STEP:PAYJOB.S1", "EXECUTES", "PROGRAM:PAYROLL")].proof_state == PROVEN
    utility = edges[("STEP:PAYJOB.S2", "EXECUTES", "UTILITY:IEFBR14")]
    assert utility.proof_state == PARTIAL and "no IBM/JES oracle" in utility.evidence
    assert edges[("STEP:PAYJOB.S3", "EXECUTES", "EXTERNAL_PROGRAM:SORT")].proof_state == BLOCKED
    assert edges[("STEP:PAYJOB.S4", "EXECUTES", "EXTERNAL_PROGRAM:NOPROC")].proof_state == UNPROVEN


def test_datasets_bindings_and_flows():
    edges = _edges(build_estate(DISCOVERY, EXTERNAL))
    assert edges[("STEP:PAYJOB.S1", "USES_DATASET", "DATASET:HR.MASTER")].proof_state == PARTIAL
    gdg = edges[("STEP:PAYJOB.S1", "USES_DATASET", "DATASET:HR.GDG(+1)")]
    assert gdg.proof_state == PARTIAL and "not resolved" in gdg.evidence
    assert edges[("PROGRAM:PAYROLL", "BINDS", "DATASET:HR.MASTER")].proof_state == PROVEN
    assert edges[("PROGRAM:PAYROLL", "BINDS", "DATASET:<unbound:RPTDD>")].proof_state == BLOCKED
    assert edges[("PROGRAM:PAYROLL", "BINDS", "DATASET:<path:TMP>")].proof_state == UNPROVEN
    assert not any("SPARE" in e.target for e in edges.values()), "an unused DD is not a dependency"
    assert edges[("STEP:PAYJOB.S1", "FLOWS_TO", "STEP:PAYJOB.S2")].proof_state == PARTIAL


def test_subsystem_references_come_from_the_ledger_entries():
    edges = _edges(build_estate(DISCOVERY, EXTERNAL))
    assert edges[("PROGRAM:PAYROLL", "USES_DB2", "DB2_TABLE:TABLE=EMPLOYEE")].proof_state == PARTIAL
    assert edges[("PROGRAM:PAYROLL", "USES_MQ", "MQ_QUEUE:QUEUE=PAY.IN")].proof_state == BLOCKED
    assert edges[("PROGRAM:PAYROLL", "USES_IMS", "IMS_SEGMENT:SEGMENT=EMPSEG")].proof_state == BLOCKED
    # an unknown proof state is never promoted
    assert edges[("PROGRAM:PAYROLL", "USES_CICS", "CICS_RESOURCE:FILE=ACCT")].proof_state == UNPROVEN
    assert not any("PARAMETER" in e.target for e in edges.values())


def test_mq_ims_and_cics_edges_name_the_simulator_without_changing_the_state():
    edges = _edges(build_estate(DISCOVERY, EXTERNAL))
    mq = edges[("PROGRAM:PAYROLL", "USES_MQ", "MQ_QUEUE:QUEUE=PAY.IN")]
    assert mq.proof_state == BLOCKED and "SIMMQ-1" in mq.evidence and "no IBM runtime was run" in mq.evidence
    ims = edges[("PROGRAM:PAYROLL", "USES_IMS", "IMS_SEGMENT:SEGMENT=EMPSEG")]
    assert ims.proof_state == BLOCKED and "SIMDLI-1" in ims.evidence
    cics = edges[("PROGRAM:PAYROLL", "USES_CICS", "CICS_RESOURCE:FILE=ACCT")]
    assert cics.proof_state == UNPROVEN and "SIMCICS-1" in cics.evidence
    # DB2 has no simulator: its evidence is untouched
    db2 = edges[("PROGRAM:PAYROLL", "USES_DB2", "DB2_TABLE:TABLE=EMPLOYEE")]
    assert "simulator" not in db2.evidence.lower()


def test_summary_counts_and_the_blocked_list():
    summary = build_estate(DISCOVERY, EXTERNAL).summary()
    assert summary["edge_count"] == sum(summary["edges_by_proof_state"].values())
    assert summary["nodes_by_kind"]["PROGRAM"] == 2 and summary["nodes_by_kind"]["JOB"] == 1
    assert "PROGRAM:PAYROLL -[USES_MQ]-> MQ_QUEUE:QUEUE=PAY.IN" in summary["blocked_edges"]
    assert 0 < summary["proven_edge_percent"] < 100


def test_the_build_is_deterministic_and_sorted():
    first = build_estate(DISCOVERY, EXTERNAL).to_dict()
    assert first == build_estate(DISCOVERY, EXTERNAL).to_dict()
    assert [n["id"] for n in first["nodes"]] == sorted(
        [n["id"] for n in first["nodes"]], key=lambda i: (i.split(":", 1)[0], i.split(":", 1)[1]))


def test_an_empty_application_is_an_empty_graph_with_zero_percent():
    summary = build_estate({}).summary()
    assert summary["node_count"] == summary["edge_count"] == 0 and summary["proven_edge_percent"] == 0.0


def test_a_stronger_state_replaces_a_weaker_one_for_the_same_edge_only():
    discovery = {"cobol_programs": [{"program_id": "A", "copybooks": [], "calls": [{"target": "A"}]}]}
    edges = _edges(build_estate(discovery))
    assert edges[("PROGRAM:A", "CALLS", "PROGRAM:A")].proof_state == PROVEN
