"""Layer 7: the IR-keyed capability record that the sealed evidence manifest carries.

The record states, as content addresses, which capability analysis a run rests on:

* ``capability_id`` - sha256 of the whole report (every component with level, reason and its Layer 5 provenance details), the
  application id and the four other ids below, so no component, reason, provenance id or binding can change without moving it;
* ``ir_id`` / ``semantic_id`` - the Application IR the analysis consumed (an IR built by the modernization pipeline from the
  discovered texts; it is *not* the document the API records under ``application_ir``, which also carries the checkpoint, source
  digest and graph, so the two ids legitimately differ);
* ``plan_id`` - sha256 of the Layer 8 plan's ``(component, type, action)`` rows, binding the report to the plan built from it;
* ``source_hash`` - the source tree hash, computed exactly as ``engine.pipeline`` computes ``SourceIdentity.source_hash`` so the
  manifest validator can require the two to be equal;
* ``application_id`` and ``overall_level`` (a closed vocabulary).

Pure functions of the report, plan, IR and tree: deterministic, no clock, no randomness, no LLM.  Without any input there is no
record (``()``), never a partial one.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from engine.application_ir.model import ApplicationIR
from engine.application_ir.project import ir_id_of
from engine.transformation.semantic_capability import CapabilityLevel
from enterprise.discovery.graph import canonical_bytes

KEYS = ("application_id", "capability_id", "ir_id", "overall_level", "plan_id", "semantic_id", "source_hash")
DIGEST_KEYS = ("capability_id", "ir_id", "plan_id", "semantic_id", "source_hash")
LEVELS = frozenset(level.value for level in CapabilityLevel)
_SHA256_HEX = re.compile(r"[0-9a-f]{64}")


def _sha(payload: Any) -> str:
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def source_tree_hash(source: "str | Path") -> str:
    """The tree hash ``engine.pipeline`` records as ``SourceIdentity.source_hash`` ("" when the path does not exist)."""
    path = Path(source)
    hasher = hashlib.sha256()
    if path.is_file():
        hasher.update(path.read_bytes())
    elif path.is_dir():
        for found in sorted(path.rglob("*")):
            if found.is_file():
                hasher.update(str(found.relative_to(path)).encode())
                hasher.update(found.read_bytes())
    else:
        return ""
    return hasher.hexdigest()


def plan_id_of(plan: Any) -> str:
    rows = [[c.component_id, c.component_type, getattr(c.action, "value", str(c.action))] for c in plan.components]
    return _sha({"components": rows, "total": plan.total_programs, "transformable": plan.transformable_programs})


def capability_id_of(application_id: str, report: Any, *, ir_id: str, semantic_id: str, plan_id: str, source_hash: str) -> str:
    components = [[c.component_id, c.component_type, c.level.value, c.reason, sorted([k, v] for k, v in c.details.items())]
                  for c in report.components]
    return _sha({"application_id": application_id, "components": components, "ir_id": ir_id,
                 "overall_level": report.overall_level.value, "plan_id": plan_id, "semantic_id": semantic_id,
                 "source_hash": source_hash})


def build_record(application_id: str, report: Any, plan: Any, ir: ApplicationIR | None,
                 source_dir: "str | Path") -> tuple[tuple[str, str], ...]:
    """The sorted ``(key, value)`` record, or ``()`` when any input is missing (no partial record)."""
    if not application_id or report is None or plan is None or ir is None:
        return ()
    source_hash = source_tree_hash(source_dir)
    if not source_hash:
        return ()
    values = {"application_id": application_id, "ir_id": ir_id_of(ir), "overall_level": report.overall_level.value,
              "plan_id": plan_id_of(plan), "semantic_id": ir.binding("semantic_id"), "source_hash": source_hash}
    values["capability_id"] = capability_id_of(
        application_id, report, ir_id=values["ir_id"], semantic_id=values["semantic_id"], plan_id=values["plan_id"],
        source_hash=source_hash)
    return tuple(sorted(values.items()))


def shape_problems(pairs: tuple[tuple[str, str], ...]) -> list[tuple[str, str]]:
    """``(field, problem)`` for every way ``pairs`` is not a well-formed record (used by the evidence validator)."""
    keys = sorted(key for key, _value in pairs)
    if keys != sorted(KEYS):
        return [("capability_analysis", f"must hold exactly {','.join(sorted(KEYS))}; got {','.join(keys)}")]
    values = dict(pairs)
    problems = [(f"capability_analysis.{key}", "is not a sha256 hex digest") for key in DIGEST_KEYS
                if not _SHA256_HEX.fullmatch(values[key])]
    if values["overall_level"] not in LEVELS:
        problems.append(("capability_analysis.overall_level", "is not a capability level"))
    if not values["application_id"]:
        problems.append(("capability_analysis.application_id", "is empty"))
    return problems


def verify_record(pairs: tuple[tuple[str, str], ...], application_id: str, report: Any, plan: Any,
                  ir: ApplicationIR | None, source_dir: "str | Path") -> list[str]:
    """Problems found re-deriving the record from its inputs (empty when it is exactly the record of those inputs)."""
    if not pairs:
        return ["capability_analysis: no record"]
    malformed = shape_problems(pairs)
    if malformed:
        return [f"{field}: {problem}" for field, problem in malformed]
    expected = dict(build_record(application_id, report, plan, ir, source_dir))
    if not expected:
        return ["capability_analysis: the inputs cannot produce a record"]
    return [f"{key}: recorded {value[:16]} but the inputs give {expected[key][:16]}"
            for key, value in sorted(dict(pairs).items()) if value != expected[key]]
