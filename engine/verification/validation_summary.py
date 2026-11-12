"""Deterministic per-run validation summary.

Conversion / Compilation / Runtime / Business equivalence, plus the named
unsupported constructs and the warnings, derived **only** from evidence the
platform already holds: the stored verdict and its comparator results, the
execution evidence of the candidate and the run's modernization report.  No
field is estimated, defaulted to PASS or filled from a model; a field with no
evidence behind it is ``NOT_RUN`` / ``NOT_EVALUATED`` (fail-closed).

Pure functions over plain dicts, so the derivation is unit-testable without
Docker.  The service gathers the inputs (``Service.get_validation_summary``).

Field semantics (each is a claim about *evidence*, not about COBOL in general):

* ``conversion``   SUCCESS when the pipeline's transformation succeeded, FAIL
  when it reported errors, NOT_RUN without a pipeline report.
* ``compilation``  FAIL when the candidate recorded BUILD-phase evidence (a
  build that did not complete - includes a build that could not run at all),
  PASS when a built candidate was executed, NOT_RUN otherwise.  The JDK is the
  one recorded in the candidate's environment identity.
* ``runtime``      PASS when every candidate EXECUTE run terminated (normal or
  with a recorded non-zero exit), FAIL on timeout/error/no exit code, NOT_RUN
  without one.  PASS says the program ran, not that it is equivalent.
* ``business_equivalence``  derived from the comparator results and the verdict:
  PASS only for a VERIFIED verdict whose comparisons all MATCH with no skipped
  or unavailable checks; WARNING for a VERIFIED verdict with gaps; FAIL for any
  MISMATCH or a FAILED verdict; NOT_EVALUATED when the candidate did not build
  or run, or the verdict is ERROR/UNAVAILABLE.  A build failure is therefore
  Compilation FAIL and never a business verdict.
"""
from __future__ import annotations

import re
from typing import Any

SCHEMA = "systemaops.validation_summary"
SCHEMA_VERSION = 1

_TERMINATED = ("normal", "nonzero_exit")
_MIN_JDK = 17


def _java_major(version: str | None) -> int | None:
    if not version:
        return None
    m = re.search(r'version\s+"?(\d+)(?:\.(\d+))?', version) or re.search(r"^(\d+)", version.strip())
    if not m:
        return None
    major = int(m.group(1))
    if major == 1 and m.lastindex and m.lastindex >= 2 and m.group(2):  # legacy "1.8.0"
        return int(m.group(2))
    return major


def _candidate_entries(evidence: dict | None) -> list[dict]:
    if not evidence:
        return []
    return [
        e for e in evidence.get("execution_evidence", [])
        if str(e.get("runtime_id", "")).startswith("candidate")
    ]


def _conversion(report: dict | None) -> dict[str, Any]:
    pr = (report or {}).get("pipeline_report") or {}
    t = pr.get("transformation")
    if not isinstance(t, dict) or "success" not in t:
        return {"status": "NOT_RUN", "detail": "no pipeline transformation result recorded", "errors": []}
    errors = [str(e) for e in t.get("errors", [])]
    if t.get("success") is True and not errors:
        return {"status": "SUCCESS", "detail": "transformation reported success",
                "programs": list(t.get("program_ids", [])), "errors": []}
    return {"status": "FAIL", "detail": "transformation reported errors", "errors": errors}


def _jdk(evidence: dict | None) -> dict[str, Any]:
    version = None
    for env in (evidence or {}).get("environment_identities", []):
        if env.get("runtime_id") == "candidate-java" and env.get("java_version"):
            version = str(env["java_version"])
    major = _java_major(version)
    return {"version": version, "major": major,
            "at_least_17": None if major is None else major >= _MIN_JDK}


def _compilation(evidence: dict | None) -> dict[str, Any]:
    cand = _candidate_entries(evidence)
    jdk = _jdk(evidence)
    builds = [e for e in cand if e.get("execution_phase") == "BUILD"]
    runs = [e for e in cand if e.get("execution_phase", "EXECUTE") == "EXECUTE"]
    if builds:
        b = builds[0]
        return {"status": "FAIL", "jdk": jdk,
                "detail": f"build did not complete (termination={b.get('termination_status')}, "
                          f"exit={b.get('exit_code')}); a build failure is not execution evidence"}
    if runs:
        return {"status": "PASS", "jdk": jdk,
                "detail": "a built candidate was executed (compile-only evidence is absent)"}
    return {"status": "NOT_RUN", "jdk": jdk, "detail": "no candidate build or execution evidence"}


def _runtime(evidence: dict | None) -> dict[str, Any]:
    runs = [e for e in _candidate_entries(evidence) if e.get("execution_phase", "EXECUTE") == "EXECUTE"]
    if not runs:
        return {"status": "NOT_RUN", "detail": "candidate never executed", "executions": []}
    rows = [{"termination": e.get("termination_status"), "exit_code": e.get("exit_code")} for e in runs]
    ok = all(e.get("termination_status") in _TERMINATED and e.get("exit_code") is not None for e in runs)
    return {"status": "PASS" if ok else "FAIL",
            "detail": "candidate executed to completion" if ok
            else "candidate timed out, errored or recorded no exit code",
            "executions": rows}


def _business(verdict: dict | None, compilation: dict, runtime: dict) -> dict[str, Any]:
    if not verdict:
        return {"status": "NOT_EVALUATED", "detail": "no verdict recorded", "comparators": []}
    comps = [{"artifact_type": c.get("artifact_type"), "result": c.get("result"),
              "differences": list(c.get("differences", []))} for c in verdict.get("comparisons", [])]
    state = verdict.get("state")
    base = {"verdict_state": state, "comparators": comps,
            "executed_check_count": verdict.get("executed_check_count"),
            "skipped_count": verdict.get("skipped_count"),
            "unavailable_count": verdict.get("unavailable_count")}
    if compilation["status"] == "FAIL" or runtime["status"] == "NOT_RUN":
        return {**base, "status": "NOT_EVALUATED",
                "detail": "the candidate did not build or run, so there is no behaviour to compare"}
    results = [str(c["result"]).upper() for c in comps]
    if state == "FAILED" or "MISMATCH" in results:
        return {**base, "status": "FAIL", "detail": "a comparator reported a mismatch or the verdict is FAILED"}
    if state == "VERIFIED":
        clean = (bool(results) and all(r == "MATCH" for r in results)
                 and not verdict.get("skipped_count") and not verdict.get("unavailable_count")
                 and verdict.get("executed_check_count", 0) > 0)
        return {**base, "status": "PASS" if clean else "WARNING",
                "detail": "all comparators MATCH on the recorded input" if clean
                else "verdict VERIFIED but some checks were skipped, unavailable or not MATCH"}
    return {**base, "status": "NOT_EVALUATED",
            "detail": f"verdict {state} does not certify equivalence either way"}


def _unsupported(report: dict | None) -> tuple[list[dict], list[dict]]:
    unsupported: dict[str, dict] = {}
    partial: dict[str, dict] = {}
    cap = ((report or {}).get("pipeline_report") or {}).get("capability") or {}
    for c in cap.get("components", []):
        row = {"name": c.get("component_id"), "kind": c.get("component_type"),
               "level": c.get("level"), "reason": c.get("reason")}
        if c.get("level") == "UNSUPPORTED":
            unsupported[str(row["name"])] = row
        elif c.get("level") == "PARTIAL":
            partial[str(row["name"])] = row
    proof = (report or {}).get("integrated_proof") or {}
    for d in proof.get("unsupported_dependencies", []):
        name = str(d.get("dependency_id") if isinstance(d, dict) else d)
        unsupported.setdefault(name, {"name": name, "kind": (d or {}).get("kind") if isinstance(d, dict) else None,
                                      "level": "UNSUPPORTED",
                                      "reason": (d or {}).get("reason") if isinstance(d, dict) else None})
    return list(unsupported.values()), list(partial.values())


_ALWAYS_NOT_PROVEN = (
    "No IBM runtime evidence: the only reference is GnuCOBOL 3.1.2 (OCESQL + PostgreSQL 14 for SQL).",
    "Equivalence is shown only for the recorded comparison input, not for all inputs.",
    "REST/HTTP behaviour of a generated application is not separately verified.",
)
_RUNTIME_NOT_PROVEN = {
    "jakarta_ee": "Jakarta EE is a generation profile and is NOT certified.",
    "quarkus": "Quarkus is certified in command mode only (no HTTP, no native image).",
    "micronaut": "Micronaut is certified in command mode only (no HTTP, no native image).",
}


def build_validation_summary(
    *, run_id: str, verdict: dict | None, evidence: dict | None, report: dict | None,
    target_runtime: str | None = None,
) -> dict[str, Any]:
    """Derive the summary.  ``evidence`` carries ``execution_evidence`` and
    ``environment_identities`` as plain dicts (see ``Service.get_validation_summary``)."""
    conversion = _conversion(report)
    compilation = _compilation(evidence)
    runtime = _runtime(evidence)
    business = _business(verdict, compilation, runtime)
    unsupported, partial = _unsupported(report)

    warnings: list[str] = []
    for p in partial:
        warnings.append(f"PARTIAL capability {p['name']}: {p['reason']}")
    if business.get("skipped_count"):
        warnings.append(f"{business['skipped_count']} comparison check(s) skipped")
    if business.get("unavailable_count"):
        warnings.append(f"{business['unavailable_count']} comparison check(s) unavailable")
    for c in business.get("comparators", []):
        if str(c["result"]).upper() not in ("MATCH", "MISMATCH"):
            warnings.append(f"comparator {c['artifact_type']} result {c['result']}")
    jdk = compilation["jdk"]
    if compilation["status"] != "NOT_RUN":
        if jdk["major"] is None:
            warnings.append("JDK version not recorded in the evidence")
        elif not jdk["at_least_17"]:
            warnings.append(f"JDK {jdk['major']} is below the required 17")
    proof_rt = (((report or {}).get("integrated_proof") or {}).get("runtime") or {})
    if proof_rt.get("evidence_integrity_valid") is False:
        warnings.append("evidence integrity validation did not pass for this run")

    runtime_key = target_runtime or (((report or {}).get("pipeline_report") or {}).get("assembly") or {}).get("target_runtime")
    not_proven = list(_ALWAYS_NOT_PROVEN)
    if runtime_key in _RUNTIME_NOT_PROVEN:
        not_proven.append(_RUNTIME_NOT_PROVEN[runtime_key])

    overall = (conversion["status"] == "SUCCESS" and compilation["status"] == "PASS"
               and runtime["status"] == "PASS" and business["status"] == "PASS")
    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "target_runtime": runtime_key,
        "verdict_state": (verdict or {}).get("state"),
        "conversion": conversion,
        "compilation": compilation,
        "runtime": runtime,
        "business_equivalence": business,
        "unsupported_constructs": {"count": len(unsupported), "items": unsupported},
        "warnings": {"count": len(warnings), "items": warnings},
        "overall_pass": overall,
        "not_proven": not_proven,
        "reference": "GnuCOBOL 3.1.2 (deterministic comparison; no LLM, no IBM runtime)",
    }


def render_markdown(summary: dict[str, Any]) -> str:
    """Deterministic Markdown rendering of :func:`build_validation_summary` output."""
    c, k, r, b = (summary["conversion"], summary["compilation"], summary["runtime"], summary["business_equivalence"])
    jdk = k["jdk"]
    jdk_txt = jdk["version"] or "not recorded"
    u, w = summary["unsupported_constructs"], summary["warnings"]
    lines = [
        f"# Validation summary - {summary['run_id']}",
        "",
        f"Target runtime: `{summary['target_runtime']}` | Verdict: `{summary['verdict_state']}` | "
        f"Overall pass: **{'YES' if summary['overall_pass'] else 'NO'}**",
        "",
        "| Check | Result | Basis |",
        "|---|---|---|",
        f"| Conversion | **{c['status']}** | {c['detail']} |",
        f"| Compilation | **{k['status']}** | {k['detail']}; JDK: {jdk_txt} |",
        f"| Runtime | **{r['status']}** | {r['detail']} |",
        f"| Business equivalence | **{b['status']}** | {b['detail']} |",
        "",
        f"Unsupported constructs: **{u['count']}**",
    ]
    lines += [f"- {i['name']} ({i['kind']}): {i['reason']}" for i in u["items"]]
    lines += ["", f"Warnings: **{w['count']}**"]
    lines += [f"- {i}" for i in w["items"]]
    lines += ["", "Not proven:"] + [f"- {i}" for i in summary["not_proven"]]
    lines += ["", f"Reference: {summary['reference']}", ""]
    return "\n".join(lines)
