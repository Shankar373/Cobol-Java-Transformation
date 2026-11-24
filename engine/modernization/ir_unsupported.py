"""Layer 7: capability findings from the reasons the Application IR names as read-but-not-modelled.

Layer 5 attaches a named reason to a declaration whose clause or construct the parser read without modelling it
(``EXTERNAL_CLAUSE_NOT_READ``, ``NESTED_PROGRAM_NOT_MODELLED``, ...).  The IR carries them verbatim per program.  A program
carrying one is never SUPPORTED: the level comes from the closed table below and a reason that is not in the table is
UNSUPPORTED (fail closed), so a new Layer 5 reason cannot silently pass.  Deterministic; nothing here reads source text.
"""

from __future__ import annotations

import dataclasses

from engine.application_ir.model import ApplicationIR
from engine.transformation.ir import CobolProgramUnit, normalize_cobol_name
from engine.transformation.semantic_capability import CapabilityLevel, worst_level

#: Closed table: Layer 5 reason -> the most generous level a program carrying it may have.
REASON_LEVELS: dict[str, CapabilityLevel] = {
    "EXTERNAL_CLAUSE_NOT_READ": CapabilityLevel.UNSUPPORTED,     # storage shared across programs is not reproduced
    "GLOBAL_CLAUSE_NOT_READ": CapabilityLevel.PARTIAL,           # scope visibility to nested programs is not read
    "NESTED_PROGRAM_NOT_MODELLED": CapabilityLevel.UNSUPPORTED,
    "RENAMES_NOT_MODELLED": CapabilityLevel.UNSUPPORTED,
}


def level_of(reason: str) -> CapabilityLevel:
    return REASON_LEVELS.get(reason, CapabilityLevel.UNSUPPORTED)


def unit_reasons(ir: ApplicationIR | None, unit: CobolProgramUnit) -> tuple[str, ...]:
    """The named reasons the IR attaches to ``unit``'s program (empty when none or when the IR lacks the program)."""
    if ir is None:
        return ()
    key = normalize_cobol_name(unit.program_id)
    return tuple(sorted({r for p in ir.programs if normalize_cobol_name(p.name) == key for r in p.unsupported}))


def apply(components: list, unit: CobolProgramUnit, ir: ApplicationIR | None) -> list:
    """``components`` with the PROGRAM component worsened by the IR's reasons for ``unit`` (unchanged when it has none)."""
    reasons = unit_reasons(ir, unit)
    if not reasons:
        return components
    level = worst_level([level_of(r) for r in reasons])
    assert level is not None
    out = []
    for comp in components:
        if comp.component_type == "PROGRAM" and comp.component_id == unit.program_id:
            worse = worst_level([comp.level, level])
            assert worse is not None
            note = "Application IR names: " + ", ".join(reasons)
            comp = dataclasses.replace(
                comp, level=worse,
                reason=note if comp.level is CapabilityLevel.SUPPORTED else f"{comp.reason}; {note}",
                details={**comp.details, "ir_unsupported": ",".join(reasons)})
        out.append(comp)
    return out
