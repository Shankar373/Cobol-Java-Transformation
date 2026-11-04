"""Roadmap unit 18: the decomposition planner -- boundaries proposed from the estate graph, for review."""

from __future__ import annotations

from engine.estate.decomposition import plan_decomposition
from engine.estate.model import build_estate


def _prog(name, copybooks=(), calls=()):
    return {"program_id": name, "copybooks": list(copybooks), "calls": [{"target": c} for c in calls]}


DISCOVERY = {
    "cobol_programs": [
        _prog("ORDERS", ["CUSTREC"], ["PRICING"]),
        _prog("PRICING"),
        _prog("BILLING", ["CUSTREC"]),
        _prog("LEDGER"),
        _prog("AUDIT", [], ["EXTLIB"]),
        _prog("REPORTS"),
    ],
    "copybooks": ["CUSTREC"],
    "jcl_jobs": [
        {"name": "NIGHTLY", "steps": [
            {"name": "S1", "program": "ORDERS"}, {"name": "S2", "program": "BILLING"},
            {"name": "S3", "program": "REPORTS"}]},
    ],
    "dd_bindings": [
        {"job": "NIGHTLY", "step": "S2", "program": "BILLING", "file_name": "F", "ddname": "BILLDD",
         "dataset": "FIN.INVOICE", "status": "BOUND"},
        {"job": "NIGHTLY", "step": "S3", "program": "LEDGER", "file_name": "F", "ddname": "LEDDD",
         "dataset": "FIN.INVOICE", "status": "BOUND"},
    ],
    "dataset_flows": [{"from": "NIGHTLY.S1", "to": "NIGHTLY.S2", "dsn": "FIN.TMP"}],
}
EXTERNAL = {
    "REPORTS": [{"dependency_id": "DB2:TABLE=SALES", "kind": "DB2", "proof_state": "PARTIAL", "reason": "r"}],
    "LEDGER": [{"dependency_id": "DB2:TABLE=SALES", "kind": "DB2", "proof_state": "PARTIAL", "reason": "r"}],
}


def _plan():
    return plan_decomposition(build_estate(DISCOVERY, EXTERNAL))


def _services(plan):
    return {tuple(s.programs): s for s in plan.services}


def test_a_static_call_keeps_two_programs_in_one_service():
    assert ("PROGRAM:ORDERS", "PROGRAM:PRICING") in _services(_plan())


def test_programs_sharing_a_dataset_or_a_table_stay_together_transitively():
    # BILLING and LEDGER share FIN.INVOICE; LEDGER and REPORTS share the SALES table
    services = _services(_plan())
    merged = services[("PROGRAM:BILLING", "PROGRAM:LEDGER", "PROGRAM:REPORTS")]
    assert merged.datasets == ("FIN.INVOICE",) and merged.db2_tables == ("SALES",)


def test_a_service_lists_the_job_steps_that_run_it():
    services = _services(_plan())
    assert services[("PROGRAM:ORDERS", "PROGRAM:PRICING")].entry_steps == ("NIGHTLY.S1",)
    assert services[("PROGRAM:BILLING", "PROGRAM:LEDGER", "PROGRAM:REPORTS")].entry_steps == (
        "NIGHTLY.S2", "NIGHTLY.S3")


def test_shared_copybook_same_job_and_dataset_flow_are_reported_as_coupling_not_merged():
    plan = _plan()
    by_kind = {c.kind: c for c in plan.couplings}
    assert by_kind["SHARED_COPYBOOK"].detail == "CUSTREC"
    assert by_kind["SAME_JOB"].detail == "NIGHTLY"
    assert (by_kind["DATASET_FLOW"].source, by_kind["DATASET_FLOW"].target) == ("svc-orders", "svc-billing")  # producer to consumer
    assert len(plan.services) == 3  # ORDERS+PRICING, BILLING+LEDGER+REPORTS, AUDIT


def test_a_service_with_a_blocked_edge_is_marked_with_its_blockers():
    audit = _services(_plan())[("PROGRAM:AUDIT",)]
    assert audit.blocked and any("EXTLIB" in b for b in audit.blockers)
    orders = _services(_plan())[("PROGRAM:ORDERS", "PROGRAM:PRICING")]
    assert not orders.blocked and orders.blockers == ()


def test_the_plan_is_a_proposal_that_needs_review_and_generates_nothing():
    body = _plan().to_dict()
    assert body["review_required"] is True
    assert body["service_count"] == 3
    assert any("no code, artifact or container is generated" in n for n in body["notes"])


def test_the_plan_does_not_depend_on_edge_or_program_order():
    shuffled = dict(DISCOVERY)
    shuffled["cobol_programs"] = list(reversed(DISCOVERY["cobol_programs"]))
    shuffled["dd_bindings"] = list(reversed(DISCOVERY["dd_bindings"]))
    assert plan_decomposition(build_estate(shuffled, EXTERNAL)).to_dict() == _plan().to_dict()


def test_an_empty_estate_gives_an_empty_plan():
    body = plan_decomposition(build_estate({})).to_dict()
    assert body["service_count"] == 0 and body["couplings"] == [] and body["review_required"] is True


def test_service_names_are_stable_and_unique():
    names = [s.name for s in _plan().services]
    assert len(set(names)) == len(names) and names == sorted(names, key=lambda n: n)
