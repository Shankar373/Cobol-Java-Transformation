"""Validation summary: every field is derived from evidence, never invented.

Covers the derivation (``engine.verification.validation_summary``) including the
negative cases - a comparator mismatch is business FAIL, a build failure is
Compilation FAIL and *not* a business verdict - and the API surface.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from engine.verification.validation_summary import build_validation_summary, render_markdown

JDK21 = 'openjdk version "21.0.12.1" 2026-08-18 LTS'


def _evidence(*, build_failed=False, run=True, term="normal", exit_code=0, java=JDK21):
    ex = [{"runtime_id": "oracle-gnucobol-3.1.2", "execution_phase": "EXECUTE",
           "termination_status": "normal", "exit_code": 0}]
    if build_failed:
        ex.append({"runtime_id": "candidate-java", "execution_phase": "BUILD",
                   "termination_status": "error", "exit_code": None})
    elif run:
        ex.append({"runtime_id": "candidate-java", "execution_phase": "EXECUTE",
                   "termination_status": term, "exit_code": exit_code})
    return {"execution_evidence": ex,
            "environment_identities": [{"runtime_id": "candidate-java", "java_version": java}]}


def _verdict(state="VERIFIED", results=("MATCH", "MATCH", "MATCH"), skipped=0, unavailable=0):
    types = ("STDOUT", "STDERR", "EXIT_STATUS")
    return {"state": state, "executed_check_count": len(results), "skipped_count": skipped,
            "unavailable_count": unavailable,
            "comparisons": [{"artifact_type": t, "result": r, "differences": [] if r == "MATCH" else [f"{t} differs"]}
                            for t, r in zip(types, results)]}


def _report(*, ok=True, components=(), runtime="plain_java", unsupported_deps=()):
    return {"pipeline_report": {
        "transformation": {"success": ok, "errors": [] if ok else ["lowering failed"], "program_ids": ["P"]},
        "capability": {"components": [dict(component_id=n, component_type="PROGRAM", level=l, reason=r)
                                       for n, l, r in components]},
        "assembly": {"target_runtime": runtime}},
        "integrated_proof": {"unsupported_dependencies": list(unsupported_deps),
                             "runtime": {"evidence_integrity_valid": True}}}


def _summary(**kw):
    return build_validation_summary(run_id="run-1", verdict=kw.pop("verdict", _verdict()),
                                    evidence=kw.pop("evidence", _evidence()),
                                    report=kw.pop("report", _report()), **kw)


def test_clean_verified_run_passes_every_check_and_names_the_jdk():
    s = _summary()
    assert (s["conversion"]["status"], s["compilation"]["status"], s["runtime"]["status"],
            s["business_equivalence"]["status"]) == ("SUCCESS", "PASS", "PASS", "PASS")
    assert s["overall_pass"] is True
    assert s["compilation"]["jdk"] == {"version": JDK21, "major": 21, "at_least_17": True}
    assert s["unsupported_constructs"]["count"] == 0 and s["warnings"]["count"] == 0


def test_comparator_mismatch_yields_business_fail_not_pass():
    s = _summary(verdict=_verdict("FAILED", ("MATCH", "MISMATCH", "MATCH")))
    assert s["compilation"]["status"] == "PASS" and s["runtime"]["status"] == "PASS"
    assert s["business_equivalence"]["status"] == "FAIL"
    assert s["overall_pass"] is False


def test_mismatch_under_a_verified_verdict_still_fails_closed():
    assert _summary(verdict=_verdict("VERIFIED", ("MATCH", "MISMATCH", "MATCH")))["business_equivalence"]["status"] == "FAIL"


def test_build_failure_is_compilation_fail_and_never_a_business_verdict():
    # the platform compares an empty candidate against the oracle and records MISMATCH
    s = _summary(evidence=_evidence(build_failed=True), verdict=_verdict("ERROR", ("MISMATCH",) * 3))
    assert s["compilation"]["status"] == "FAIL"
    assert s["runtime"]["status"] == "NOT_RUN"
    assert s["business_equivalence"]["status"] == "NOT_EVALUATED"
    assert s["overall_pass"] is False


def test_no_candidate_evidence_is_not_run_never_pass():
    s = _summary(evidence=_evidence(run=False), verdict=_verdict("UNAVAILABLE", ("MATCH",) * 3))
    assert s["compilation"]["status"] == "NOT_RUN" and s["runtime"]["status"] == "NOT_RUN"
    assert s["business_equivalence"]["status"] == "NOT_EVALUATED"


def test_missing_evidence_verdict_and_report_invent_nothing():
    s = build_validation_summary(run_id="r", verdict=None, evidence=None, report=None)
    assert s["conversion"]["status"] == "NOT_RUN"
    assert s["compilation"]["status"] == "NOT_RUN" and s["runtime"]["status"] == "NOT_RUN"
    assert s["business_equivalence"]["status"] == "NOT_EVALUATED"
    assert s["overall_pass"] is False and s["compilation"]["jdk"]["version"] is None


def test_timeout_is_runtime_fail():
    s = _summary(evidence=_evidence(term="timeout", exit_code=None), verdict=_verdict("FAILED", ("MISMATCH",) * 3))
    assert s["runtime"]["status"] == "FAIL"


def test_nonzero_exit_that_terminated_is_a_completed_run():
    s = _summary(evidence=_evidence(term="nonzero_exit", exit_code=3))
    assert s["runtime"]["status"] == "PASS" and s["runtime"]["executions"][0]["exit_code"] == 3


def test_verified_with_skipped_or_unavailable_checks_is_warning_not_pass():
    s = _summary(verdict=_verdict("VERIFIED", skipped=1))
    assert s["business_equivalence"]["status"] == "WARNING" and s["overall_pass"] is False
    assert any("skipped" in w for w in s["warnings"]["items"])


def test_conversion_failure_is_reported():
    s = _summary(report=_report(ok=False))
    assert s["conversion"]["status"] == "FAIL" and s["conversion"]["errors"] == ["lowering failed"]
    assert s["overall_pass"] is False


def test_unsupported_constructs_are_named_and_partial_ones_become_warnings():
    rep = _report(components=[("ACCEPTER", "UNSUPPORTED", "EXEC CICS"), ("SEARCHER", "PARTIAL", "SEARCH ALL form"),
                              ("FINE", "SUPPORTED", "ok")],
                  unsupported_deps=[{"dependency_id": "DB2PROG", "kind": "PROGRAM", "reason": "EXEC SQL"}])
    s = _summary(report=rep)
    names = {i["name"] for i in s["unsupported_constructs"]["items"]}
    assert names == {"ACCEPTER", "DB2PROG"} and s["unsupported_constructs"]["count"] == 2
    assert s["warnings"]["count"] == 1 and "SEARCHER" in s["warnings"]["items"][0]


@pytest.mark.parametrize("java,major,ok", [(JDK21, 21, True), ('openjdk version "17.0.9"', 17, True),
                                           ('openjdk version "11.0.2"', 11, False), ('java version "1.8.0_392"', 8, False)])
def test_jdk_floor_is_derived_from_the_recorded_version(java, major, ok):
    s = _summary(evidence=_evidence(java=java))
    assert s["compilation"]["jdk"]["major"] == major and s["compilation"]["jdk"]["at_least_17"] is ok
    assert (not ok) == any("below the required 17" in w for w in s["warnings"]["items"])


def test_unrecorded_jdk_is_a_warning_not_a_guess():
    s = _summary(evidence=_evidence(java=None))
    assert s["compilation"]["jdk"]["at_least_17"] is None
    assert any("JDK version not recorded" in w for w in s["warnings"]["items"])


@pytest.mark.parametrize("runtime,phrase", [("jakarta_ee", "NOT certified"), ("quarkus", "command mode only"),
                                            ("micronaut", "command mode only")])
def test_uncertified_or_limited_runtimes_state_what_is_not_proven(runtime, phrase):
    s = _summary(report=_report(runtime=runtime))
    assert any(phrase in n for n in s["not_proven"])
    assert any("IBM" in n for n in s["not_proven"]) and any("REST" in n for n in s["not_proven"])


def test_summary_is_deterministic_and_markdown_names_every_check():
    a, b = _summary(), _summary()
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    md = render_markdown(a)
    for label in ("Conversion", "Compilation", "Runtime", "Business equivalence", "Unsupported constructs:", "Warnings:", "Not proven"):
        assert label in md
    assert md == render_markdown(b)


# --- API surface -----------------------------------------------------------

@pytest.fixture
def client(tmp_path):
    import api.app as app_mod
    import api.service as svc_mod
    from api.service import Service
    from api.store import Store

    store = Store(db_path=tmp_path / "vs.db")
    svc = Service(store)
    app_mod._store = store
    app_mod._service = svc
    svc_mod._store = store
    svc_mod._service = svc
    return TestClient(app_mod.app), svc


def test_endpoint_404_without_a_verdict_and_422_for_a_bad_format(client):
    c, svc = client
    assert c.get("/runs/run-missing/validation-summary").status_code == 404
    from unittest.mock import patch
    with patch.object(type(svc), "get_validation_summary", lambda self, rid: _summary()):
        assert c.get("/runs/run-1/validation-summary?format=pdf").status_code == 422


def test_endpoint_serves_json_and_markdown_from_the_service(client):
    from unittest.mock import patch
    c, svc = client
    with patch.object(type(svc), "get_validation_summary", lambda self, rid: _summary()):
        j = c.get("/runs/run-1/validation-summary")
        m = c.get("/runs/run-1/validation-summary?format=markdown")
    assert j.status_code == 200 and j.json()["business_equivalence"]["status"] == "PASS"
    assert m.status_code == 200 and m.headers["content-type"].startswith("text/markdown")
    assert "Business equivalence" in m.text
