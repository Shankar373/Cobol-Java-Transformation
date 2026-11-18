"""The transformation readiness decision, derived from a discovery report.

``BLOCKED``        discovery is incomplete (a blocking reference is unresolved, a file was not scanned, the checkpoint does not verify, ...):
                   modernization must not start.
``NOT_SUPPORTED``  discovery is complete, but some programs use constructs that open-source tooling cannot check or that this product
                   refuses (EXEC CICS, IMS, IBM MQ, ...), or GnuCOBOL rejects them: modernization may be requested, but the unsupported
                   items travel with the request and are never reported as handled.
``READY``          nothing blocks, nothing is unsupported, and every compilable program received an open-source compiler verdict.
                   A program whose compiler check did not run (no compiler, tool failure, budget) makes the status ``NOT_SUPPORTED``.

The decision is a pure function of the report, so it is reproducible and can be re-derived by anyone holding the artefacts.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

__all__ = ["READINESS_STATES", "UNVERIFIED_VERDICTS", "evaluate_readiness", "describe_blockers"]

#: Compiler verdicts that mean "no open-source compiler verdict exists for this program although one was possible": the check did not
#: run (no compiler, tool failure, time budget) or its inputs were not usable.  Such a program is never reported as READY.
UNVERIFIED_VERDICTS = frozenset({"NOT_ATTEMPTED_NO_COMPILER", "NOT_ATTEMPTED_TOOL_FAILURE", "NOT_ATTEMPTED_BUDGET", "NOT_ATTEMPTED_BLOCKED_DEPENDENCY"})

READINESS_STATES = ("BLOCKED", "NOT_SUPPORTED", "READY")
_LIMIT = 50


def evaluate_readiness(report: Mapping[str, Any]) -> dict[str, Any]:
    gate = report["completeness"]
    compat = report.get("compatibility", {"programs": []})
    apps = report.get("applications", {"applications": []})["applications"]
    blockers = [{"detail": next((c["detail"] for c in gate["checks"] if c["id"] == b), ""), "id": b} for b in gate["blockers"]]
    unsupported: list[dict[str, Any]] = []
    compile_errors: list[dict[str, Any]] = []
    unverified: list[dict[str, Any]] = []
    for program in compat["programs"]:
        for feature in program["unsupported_features"]:
            unsupported.append({"evidence": feature["evidence"][:3], "feature": feature["feature"], "file": program["file"],
                                "label": feature["label"], "note": feature["note"], "stops_check": feature["stops_check"]})
        if program["verdict"] in UNVERIFIED_VERDICTS:
            unverified.append({"file": program["file"], "reason": program["verdict"]})
        if program["verdict"] == "COMPILE_ERRORS":
            compile_errors.append({"diagnostics": [d for d in program["diagnostics"] if d["severity"] == "error"][:5],
                                   "dialect": program["dialect"], "file": program["file"]})
    status = "BLOCKED" if blockers else ("NOT_SUPPORTED" if unsupported or compile_errors or unverified else "READY")
    return {
        "allowed": status != "BLOCKED",
        "applications": [{"id": a["id"], "name": a["name"], "readiness": a["readiness"]} for a in apps],
        "blocking_references": gate.get("blocking_references", [])[:_LIMIT],
        "blockers": blockers,
        "compile_errors": compile_errors[:_LIMIT],
        "status": status,
        "unsupported": unsupported[:_LIMIT],
        "unverified": unverified[:_LIMIT],
        "unverified_total": len(unverified),
        "unsupported_total": len(unsupported),
    }


def describe_blockers(readiness: Mapping[str, Any]) -> str:
    """A short, path-free sentence for an API error: what is missing and where the full list is."""
    parts = [f"{b['id']} ({b['detail']})" if b["detail"] else str(b["id"]) for b in readiness["blockers"]]
    targets = [f"{r['to']} at {r['file']}:{r['line']}" for r in readiness["blocking_references"][:5]]
    text = "; ".join(parts)
    if targets:
        text += ". Missing: " + ", ".join(targets)
    return text
