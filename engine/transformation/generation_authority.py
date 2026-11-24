"""Layer 9: the Layer 8 transformation plan as the authority over what generation may emit.

Generation used to be *checked* against the plan by the pipeline only (a blanket refusal before ``ApplicationGenerator`` ran).  This
module lets the generator itself take the plan: it states, as two pure checks, what a plan permits.

* ``preflight`` - before any Java is produced: the plan must be about this application, trustworthy (no evidence conflict), complete
  (every discovered program appears in it, no program it names is missing), approved (every program, CALL and copybook component is
  ``TRANSFORM``; a blocked callee or copybook therefore refuses its callers) and must establish a transformable entry that agrees with
  the entry the caller asked for.
* ``verify_output`` - after generation: the program classes that were emitted are exactly the approved programs (nothing blocked,
  nothing extra, nothing missing, program-id to class identity preserved) and the entry class is the plan's entry.

Both return refusal messages (``[]`` when nothing is wrong); neither raises, reads a clock or consults anything but its arguments.  No
LLM, no I/O.  ``plan`` is a ``TransformationPlan`` (duck-typed: only ``components``, ``application_id``, ``oracle``,
``evidence_conflicts`` are read).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from typing import Any

from engine.transformation.entrypoint import normalise

_TRANSFORM = "TRANSFORM"
#: Component types that must all be approved for the application to be generated at all (see ``engine.modernization.pipeline``).
_GATING_TYPES = ("PROGRAM", "CALL", "COPYBOOK")


def _action(component: Any) -> str:
    return getattr(component.action, "value", str(component.action))


def runtime_class_name(target_runtime: str, program_id: str) -> str:
    """The Java class a program id is generated as in ``target_runtime``.

    Spring Boot names its service classes in PascalCase (``STUDENT-PROCESSOR`` -> ``StudentProcessor``); every other target keeps the
    shared generator's rule (``Student_Processor``).  Both are deterministic functions of the program id alone."""
    from engine.transformation.java_generator import JavaGenerator
    from engine.transformation.java_to_spring_mapping import service_class_name

    return service_class_name(program_id) if target_runtime == "spring_boot" else JavaGenerator().class_name_for(program_id)


def approved_program_ids(plan: Any) -> tuple[str, ...]:
    """Program ids the plan approves, in the plan's execution order (callees first)."""
    approved = {c.component_id for c in plan.components if c.component_type == "PROGRAM" and _action(c) == _TRANSFORM}
    return tuple(pid for pid in plan.execution_order if pid in approved)


def preflight(plan: Any, application_id: str, discovered_program_ids: Iterable[str], requested_entry: str = "") -> list[str]:
    """Why the plan does not permit generating this application ("" list when it does)."""
    if plan is None:
        return ["Transformation plan is absent: generation requires an approved plan"]
    problems: list[str] = []
    if plan.application_id != application_id:
        problems.append(f"Plan is for application {plan.application_id!r}, not {application_id!r}")
    if plan.evidence_conflicts:
        problems.append("Plan evidence is in conflict: " + "; ".join(plan.evidence_conflicts))

    planned = Counter(c.component_id for c in plan.components if c.component_type == "PROGRAM")
    discovered = Counter(discovered_program_ids)
    if planned != discovered:
        missing = sorted((discovered - planned).elements())
        unknown = sorted((planned - discovered).elements())
        problems.append("Plan and application disagree on programs"
                        + (f"; not planned: {', '.join(missing)}" if missing else "")
                        + (f"; planned but not discovered: {', '.join(unknown)}" if unknown else ""))

    refused = [c for c in plan.components if c.component_type in _GATING_TYPES and _action(c) != _TRANSFORM]
    if refused:
        problems.append("Plan does not approve: " + ", ".join(f"{c.component_type} {c.component_id}" for c in refused))

    if not plan.has_transformations:
        problems.append("Plan approves no program")
    if not plan.entrypoint_resolved:
        problems.append(plan.oracle.entry_diagnostic or "Plan establishes no entrypoint")
    elif not plan.entry_transformable:
        problems.append(f"Plan entry {plan.oracle.entry_program!r} is not approved for transformation")
    elif requested_entry and normalise(requested_entry) != normalise(plan.oracle.entry_program):
        problems.append(f"Requested entrypoint {requested_entry!r} disagrees with the plan's {plan.oracle.entry_program!r}")
    return problems


def verify_output(plan: Any, program_classes: Sequence[str], program_ids: Sequence[str], entry_class: str,
                  class_name_of: Callable[[str], str]) -> list[str]:
    """Why the emitted Java is not what the plan approved (empty list when it is exactly that).

    ``program_classes`` are the emitted program classes (assembly helpers and copybook models excluded), ``program_ids`` the programs
    mapped, ``class_name_of`` the generator's program-id to class-name rule (identity preservation)."""
    approved = approved_program_ids(plan)
    problems: list[str] = []
    if Counter(normalise(p) for p in program_ids) != Counter(normalise(p) for p in approved):
        problems.append("Generated programs " + ", ".join(sorted(program_ids))
                        + " are not the approved programs " + ", ".join(sorted(approved)))
    expected_classes = Counter(class_name_of(p) for p in approved)
    if Counter(program_classes) != expected_classes:
        problems.append("Generated classes " + ", ".join(sorted(program_classes))
                        + " do not preserve the approved program identities " + ", ".join(sorted(expected_classes.elements())))
    if normalise(entry_class) != normalise(plan.oracle.entry_program):
        problems.append(f"Generation selected entry {entry_class!r} but the plan established {plan.oracle.entry_program!r}")
    return problems
