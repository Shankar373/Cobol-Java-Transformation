"""Layer 8: the transformation-plan record that the sealed evidence manifest carries.

The record states, as content addresses, which plan a run was generated from:

* ``plan_digest`` - sha256 of the whole plan document (``TransformationPlan.to_dict``: every component with action, transformer,
  reason, priority, capability level, provenance and blocker, the oracle parameters, the assembly plan, the evidence conflicts and
  notes), so nothing the plan decided can change without moving it;
* ``plan_id`` - the Layer 7 definition (``capability_record.plan_id_of``: the ``(component, type, action)`` rows and counts), kept
  so the plan record and the capability record can be required to name the same plan;
* ``capability_id`` / ``ir_id`` - the Layer 7 capability record and IR the plan was built from (the plan record is refused when it
  names a different analysis than the capability record beside it);
* ``source_hash`` - the source tree hash, computed exactly as ``engine.pipeline`` computes ``SourceIdentity.source_hash``;
* ``application_id`` and ``entry_resolution`` (closed vocabulary: ``RESOLVED`` / ``UNRESOLVED``).

Pure functions of the plan and the capability record: deterministic, no clock, no randomness, no LLM.  Without any input there is
no record (``()``), never a partial one.  The record is advisory lineage: it never changes generation or a verdict.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from engine.modernization.capability_record import plan_id_of, source_tree_hash
from enterprise.discovery.graph import canonical_bytes

KEYS = ("application_id", "capability_id", "entry_resolution", "ir_id", "plan_digest", "plan_id", "source_hash")
DIGEST_KEYS = ("capability_id", "ir_id", "plan_digest", "plan_id", "source_hash")
ENTRY_RESOLUTIONS = frozenset({"RESOLVED", "UNRESOLVED"})
#: Keys the plan record and the capability record must hold with equal values (they describe one analysis and one plan).
SHARED_WITH_CAPABILITY = ("application_id", "capability_id", "ir_id", "plan_id", "source_hash")
_SHA256_HEX = re.compile(r"[0-9a-f]{64}")


def plan_digest_of(plan: Any) -> str:
    return hashlib.sha256(canonical_bytes(plan.to_dict())).hexdigest()


def build_record(application_id: str, plan: Any, capability_pairs: tuple[tuple[str, str], ...],
                 source_dir: "str | Path") -> tuple[tuple[str, str], ...]:
    """The sorted ``(key, value)`` record, or ``()`` when any input is missing (no partial record).

    ``capability_pairs`` is the Layer 7 record built for the same plan; the plan must be the one it names (equal ``plan_id``)."""
    if not application_id or plan is None or not capability_pairs:
        return ()
    capability = dict(capability_pairs)
    source_hash = source_tree_hash(source_dir)
    plan_id = plan_id_of(plan)
    if not source_hash or capability.get("plan_id") != plan_id or capability.get("source_hash") != source_hash:
        return ()
    values = {"application_id": application_id, "capability_id": capability.get("capability_id", ""),
              "entry_resolution": plan.oracle.entry_resolution, "ir_id": capability.get("ir_id", ""),
              "plan_digest": plan_digest_of(plan), "plan_id": plan_id, "source_hash": source_hash}
    return tuple(sorted(values.items()))


def shape_problems(pairs: tuple[tuple[str, str], ...]) -> list[tuple[str, str]]:
    """``(field, problem)`` for every way ``pairs`` is not a well-formed record (used by the evidence validator)."""
    keys = sorted(key for key, _value in pairs)
    if keys != sorted(KEYS):
        return [("transformation_plan", f"must hold exactly {','.join(sorted(KEYS))}; got {','.join(keys)}")]
    values = dict(pairs)
    problems = [(f"transformation_plan.{key}", "is not a sha256 hex digest") for key in DIGEST_KEYS
                if not _SHA256_HEX.fullmatch(values[key])]
    if values["entry_resolution"] not in ENTRY_RESOLUTIONS:
        problems.append(("transformation_plan.entry_resolution", "is not an entry resolution"))
    if not values["application_id"]:
        problems.append(("transformation_plan.application_id", "is empty"))
    return problems


def disagreements_with_capability(plan_pairs: tuple[tuple[str, str], ...],
                                  capability_pairs: tuple[tuple[str, str], ...]) -> list[str]:
    """Shared keys on which a well-formed plan record and capability record differ (one analysis, one plan, one source)."""
    plan, capability = dict(plan_pairs), dict(capability_pairs)
    return [key for key in SHARED_WITH_CAPABILITY if plan.get(key) != capability.get(key)]


def verify_record(pairs: tuple[tuple[str, str], ...], application_id: str, plan: Any,
                  capability_pairs: tuple[tuple[str, str], ...], source_dir: "str | Path") -> list[str]:
    """Problems found re-deriving the record from its inputs (empty when it is exactly the record of those inputs)."""
    if not pairs:
        return ["transformation_plan: no record"]
    malformed = shape_problems(pairs)
    if malformed:
        return [f"{field}: {problem}" for field, problem in malformed]
    expected = dict(build_record(application_id, plan, capability_pairs, source_dir))
    if not expected:
        return ["transformation_plan: the inputs cannot produce a record"]
    return [f"{key}: recorded {value[:16]} but the inputs give {expected[key][:16]}"
            for key, value in sorted(dict(pairs).items()) if value != expected[key]]
