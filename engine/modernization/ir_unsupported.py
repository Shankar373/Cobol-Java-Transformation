"""Layer 7: capability findings from what the Application IR says it could not read, model or accept.

Two sources, both carried verbatim by the IR from Layer 5, both closed tables, both deterministic and free of source text:

* the named reasons on a program (``EXTERNAL_CLAUSE_NOT_READ``, ``NESTED_PROGRAM_NOT_MODELLED``, ...): ``REASON_LEVELS``;
* the IR notes (``refusal``, ``unsupported``, ``diagnostic``, ``option``, ``cancel``): ``note_floor``.

A finding is a *floor*: it can only lower a program's level, never raise it.  A reason or an ``unsupported`` code that is in no table
fails closed (UNSUPPORTED for a program reason, UNKNOWN for a note code), so a new Layer 5 vocabulary entry cannot silently pass.

Dispositions that leave the level alone are recorded here with their evidence, not left implicit:

* ``diagnostic`` notes are parser warnings; the analyzer owns them through its certified-construct rules (``PARTIAL_SUPPORT`` on a
  certified binary item is SUPPORTED in 24 fixture programs, pinned by ``tests/capability_truth.txt``).
* ``unsupported/CONDITION_UNSTRUCTURED`` is a Layer 5 reference-extraction limit on ``PERFORM VARYING ... UNTIL``, a certified
  construct (SUPPORTED in 4 fixture programs); ``unsupported/COPYBOOK_NOT_EXPANDED`` is the Layer 5 limit that copybook declarations
  are not merged; the analyzer's own copybook components cover it (SUPPORTED in 6 fixture programs).
* ``cancel`` is covered by the CALL analysis; JCL refusals belong to the JCL ledger, never to a capability component.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable

from engine.application_ir.model import ApplicationIR, IRNote
from engine.transformation.ir import CobolApplication, CobolProgramUnit, normalize_cobol_name
from engine.transformation.semantic_capability import CapabilityLevel, worst_level

#: Closed table: Layer 5 program reason -> the most generous level a program carrying it may have.
REASON_LEVELS: dict[str, CapabilityLevel] = {
    "EXTERNAL_CLAUSE_NOT_READ": CapabilityLevel.UNSUPPORTED,     # storage shared across programs is not reproduced
    "GLOBAL_CLAUSE_NOT_READ": CapabilityLevel.PARTIAL,           # scope visibility to nested programs is not read
    "NESTED_PROGRAM_NOT_MODELLED": CapabilityLevel.UNSUPPORTED,
    "RENAMES_NOT_MODELLED": CapabilityLevel.UNSUPPORTED,
}

#: ``unsupported`` notes: code -> floor, ``None`` meaning "documented non-blocking" (see the module docstring).
UNSUPPORTED_NOTE_FLOORS: dict[str, CapabilityLevel | None] = {
    "STATEMENT_PARTLY_PARSED": CapabilityLevel.PARTIAL,
    "OPERAND_UNPARSED": CapabilityLevel.PARTIAL,
    "INSPECT_OPERAND_KIND_UNKNOWN": CapabilityLevel.PARTIAL,
    "GOTO_TARGET_UNPARSED": CapabilityLevel.PARTIAL,
    "CONDITION_UNSTRUCTURED": None,
    "COPYBOOK_NOT_EXPANDED": None,
}

_FILE_SUBJECTS = ("diag", "copy", "parse", "option", "cancel")     # Layer 5 subject ids: "<prefix>:<file>:<detail>"
_STATEMENT_PREFIX = "stmt:program:"                                 # "stmt:program:<NAME>[@<file>]/<paragraph>/<n>"
APPLICATION_FINDING = "IR-NOTES"


def level_of(reason: str) -> CapabilityLevel:
    return REASON_LEVELS.get(reason, CapabilityLevel.UNSUPPORTED)


def note_floor(kind: str, code: str) -> CapabilityLevel | None:
    """The floor one IR note puts on its program; ``None`` when the note is a documented non-blocking disposition."""
    if kind == "refusal":
        return None if code.startswith("JCL_") else CapabilityLevel.UNSUPPORTED
    if kind == "unsupported":
        if code in REASON_LEVELS:         # Layer 5 also states each program reason as a note: one table, one level
            return REASON_LEVELS[code]
        return UNSUPPORTED_NOTE_FLOORS.get(code, CapabilityLevel.UNKNOWN)
    if kind == "option":
        return CapabilityLevel.PARTIAL if code == "COMPILER_OPTION_UNMODELLED" else None
    if kind in ("diagnostic", "cancel"):
        return None
    return CapabilityLevel.UNKNOWN        # a note kind outside the closed IR vocabulary is not understood: fail closed


def _file_of(note: IRNote) -> str:
    if note.span is not None and note.span.file:
        return note.span.file.replace("\\", "/")
    prefix, _, rest = note.subject.partition(":")
    if prefix in _FILE_SUBJECTS:
        return rest.split(":", 1)[0].replace("\\", "/")
    return ""


def _statement_owner(note: IRNote) -> str:
    """The program name a statement note's id names when it names no file (``""`` otherwise)."""
    if not note.subject.startswith(_STATEMENT_PREFIX):
        return ""
    owner = note.subject[len(_STATEMENT_PREFIX):].split("/", 1)[0]
    return "" if "@" in owner else owner


def _owns(unit: CobolProgramUnit, note: IRNote) -> bool:
    path = unit.source_path.replace("\\", "/")
    name = _file_of(note)
    if name:
        return name == path or path.rsplit("/", 1)[-1] == name.rsplit("/", 1)[-1]
    owner = _statement_owner(note)
    return bool(owner) and normalize_cobol_name(owner) == normalize_cobol_name(unit.program_id)


def _floored(ir: ApplicationIR) -> Iterable[tuple[IRNote, CapabilityLevel]]:
    for note in sorted(ir.notes, key=lambda n: n.note_id):
        floor = note_floor(note.kind, note.code)
        if floor is not None:
            yield note, floor


def unit_reasons(ir: ApplicationIR | None, unit: CobolProgramUnit) -> tuple[str, ...]:
    """The named reasons the IR attaches to ``unit``'s program (empty when none or when the IR lacks the program)."""
    if ir is None:
        return ()
    key = normalize_cobol_name(unit.program_id)
    return tuple(sorted({r for p in ir.programs if normalize_cobol_name(p.name) == key for r in p.unsupported}))


def apply(components: list, unit: CobolProgramUnit, ir: ApplicationIR | None) -> list:
    """``components`` with the PROGRAM component worsened by the IR's findings for ``unit`` (unchanged when it has none)."""
    if ir is None:
        return components
    reasons = unit_reasons(ir, unit)
    notes = [(n, f) for n, f in _floored(ir) if _owns(unit, n)]
    if not reasons and not notes:
        return components
    floor = worst_level([level_of(r) for r in reasons] + [f for _n, f in notes])
    assert floor is not None
    labels = list(reasons) + sorted({f"{n.kind}/{n.code}" for n, _f in notes})
    out = []
    for comp in components:
        if comp.component_type == "PROGRAM" and comp.component_id == unit.program_id:
            worse = worst_level([comp.level, floor])
            assert worse is not None
            text = "Application IR names: " + ", ".join(labels)
            details = {**comp.details, "ir_unsupported": ",".join(reasons)} if reasons else dict(comp.details)
            if notes:
                details["ir_provenance"] = ",".join(sorted({n.provenance for n, _f in notes}))
            if worse is comp.level:        # the IR confirms the level: provenance only, the verdict text is unchanged
                reason = comp.reason
            else:
                reason = text if comp.level is CapabilityLevel.SUPPORTED else f"{comp.reason}; {text}"
            comp = dataclasses.replace(comp, level=worse, details=details, reason=reason)
        out.append(comp)
    return out


def application_findings(ir: ApplicationIR | None, application: CobolApplication) -> list:
    """One component for the floored notes no program of ``application`` owns (a note is never silently dropped)."""
    from engine.modernization.capability_analyzer import ComponentCapability

    if ir is None:
        return []
    orphans = [(n, f) for n, f in _floored(ir) if not any(_owns(u, n) for u in application.programs)]
    if not orphans:
        return []
    level = worst_level([f for _n, f in orphans])
    assert level is not None
    labels = sorted({f"{n.kind}/{n.code}" for n, _f in orphans})
    return [ComponentCapability(
        component_id=APPLICATION_FINDING, component_type="CALL", level=level,
        reason="Application IR notes belong to no analysed program: " + ", ".join(labels),
        details={"ir_provenance": ",".join(sorted({n.provenance for n, _f in orphans}))})]
