"""Per-FD VSAM migration assessment (Stage 1, product workflow).

Before any data is converted the product can state, for each file a program declares, whether the
migration library can take it and why not.  The record layout is derived with the IBM width model (the
source side of a mainframe migration); the verdict is one of

* ``MIGRATABLE``         - layout derivable, no binary fields
* ``REQUIRES_PLATFORMS`` - layout derivable, binary fields need explicit source and target platforms
* ``REFUSED``            - layout not derivable or ambiguous (reasons are the layout diagnostics)
* ``BLOCKED``            - RRDS: needs an IBM VSAM reference that is not available
* ``NOT_APPLICABLE``     - a sort work file (SD) is never migrated

Nothing is guessed: several records in one FD are refused until one is chosen.  The assessment reads the
parsed program only; it never touches data and never claims IBM equivalence.
"""
from __future__ import annotations

from engine.transformation.ir import CobolProgram, FileDefinition, FileOrganization
from engine.vsam.convert import FieldKind
from engine.vsam.layout import BinaryWidthModel, RecordLayout, derive_file_layout

EVIDENCE = {
    "layout_widths": "IBM 2/4/8 byte binary widths, documented; verified against GnuCOBOL only",
    "not_claimed": "IBM Enterprise COBOL or IBM VSAM equivalence is not established by this assessment",
}

_ALTERNATE_INDEX_NOTE = ("alternate index(es) are validated (uniqueness, duplicates) but the index structure "
                         "is not built")


def _layout_summary(layout: RecordLayout) -> dict:
    return {
        "record_name": layout.record_name, "record_length": layout.record_length, "supported": layout.supported,
        "field_count": len(layout.fields),
        "has_binary": any(f.kind is FieldKind.BINARY for f in layout.fields),
        "diagnostics": [{"code": d.code, "path": d.path, "message": d.message} for d in layout.diagnostics],
    }


def _layouts(fd: FileDefinition) -> list[RecordLayout]:
    model = BinaryWidthModel.IBM_2_4_8
    if len(fd.record_groups) > 1:
        return [derive_file_layout(fd, binary_width_model=model, record_name=g.name) for g in fd.record_groups]
    return [derive_file_layout(fd, binary_width_model=model)]


def _verdict(fd: FileDefinition, layouts: list[RecordLayout]) -> tuple[str, list[str], list[str]]:
    notes = [_ALTERNATE_INDEX_NOTE] if fd.alternate_keys else []
    if fd.is_sort_file:
        return "NOT_APPLICABLE", ["a sort work file (SD) is never migrated"], notes
    if fd.organization is FileOrganization.RELATIVE:
        return "BLOCKED", ["RRDS migration is BLOCKED: the unload format needs an IBM VSAM reference that is "
                           "not available"], notes
    reasons = [f"{d.code} at {d.path or l.record_name}: {d.message}" for l in layouts for d in l.diagnostics]
    if len(fd.record_groups) > 1:
        names = ", ".join(g.name for g in fd.record_groups)
        reasons.insert(0, f"FD {fd.name} has several records ({names}) sharing one area; one record must be "
                          "chosen - none is assumed")
    if reasons:
        return "REFUSED", reasons, notes
    if any(f.kind is FieldKind.BINARY for l in layouts for f in l.fields):
        return "REQUIRES_PLATFORMS", [
            "binary (COMP / COMP-5) fields need an explicit source_platform and target_platform "
            "(and a target layout)"], notes
    return "MIGRATABLE", [], notes


def assess_file_definition(fd: FileDefinition) -> dict:
    """The migration assessment of one FD."""
    layouts = _layouts(fd)
    status, reasons, notes = _verdict(fd, layouts)
    return {
        "file": fd.name, "organization": fd.organization.value, "access_mode": fd.access_mode.value,
        "record_key": fd.record_key.field_name if fd.record_key else "",
        "alternate_keys": [{"field": k.field_name, "duplicates": k.is_duplicated} for k in fd.alternate_keys],
        "record_layouts": [_layout_summary(l) for l in layouts],
        "migration": {"status": status, "reasons": reasons, "notes": notes},
        "evidence": dict(EVIDENCE),
    }


def assess_program(program: CobolProgram) -> list[dict]:
    """The assessment of every FD of ``program``, in declaration order."""
    return [assess_file_definition(fd) for fd in program.file_definitions]
