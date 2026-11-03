"""JCL DD binding and the dataset catalogue (analysis only).

A COBOL program names a file by DD name (``SELECT EMP-FILE ASSIGN TO EMPIN``); the JCL step
that runs it binds ``//EMPIN DD DSN=HR.EMPLOYEES``. This module reports, for every step that
executes a program of the application, how each of the program's ``ASSIGN TO`` names binds:

- ``BOUND``        a DD of that name exists in the step (dataset recorded);
- ``UNBOUND``      no DD of that name: on a mainframe the OPEN fails;
- ``LITERAL_PATH`` the program names its file itself (``ASSIGN TO "x.dat"``): not JCL-bound;
- ``UNUSED_DD``    a DD no ``ASSIGN`` name uses (standard system DDs are not reported).

It also builds a catalogue of datasets (permanent, temporary ``&&``, relative GDG generations,
inline, SYSOUT) with the steps that produce and consume them, and the cross-step data flow.

Nothing here executes JCL and nothing resolves a GDG generation: ``HR.MASTER(+1)`` is
catalogued and flagged "not resolved". The JCL proof state of an application stays PARTIAL.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: DD names the system or the language runtime supplies; never a COBOL file.
STANDARD_DDS = frozenset({
    "SYSOUT", "SYSPRINT", "SYSUDUMP", "SYSABEND", "SYSIN", "SYSLOG", "STEPLIB", "JOBLIB",
    "SYSDBOUT", "CEEDUMP", "SYSTSPRT", "SYSTSIN", "SYSPRT", "SYSUT1", "SYSUT2",
})
_GDG = re.compile(r"\((?:[+-]\d+|0)\)\s*$")


@dataclass(frozen=True)
class FileAssign:
    """One SELECT ... ASSIGN of a COBOL program."""

    file_name: str  # the SELECT name
    kind: str  # "DDNAME" | "LITERAL" | other (uncertified)
    target: str  # the DD name, or the literal path


def cobol_file_assignments(source_text: str) -> list[FileAssign]:
    """The ``ASSIGN`` names of one program, or ``[]`` if it cannot be parsed."""
    from engine.transformation.cobol_parser import CobolParser

    try:
        program = CobolParser().parse(source_text)
    except Exception:  # noqa: BLE001 - an unparseable program has no known bindings
        return []
    return [
        FileAssign(fd.name, fd.assign_kind, fd.container_path)
        for fd in program.file_definitions
        if fd.container_path
    ]


def _disposition(text: str) -> str:
    """The first (status) token of ``DISP=(NEW,CATLG)`` / ``SHR``, upper case."""
    match = re.match(r"\(?\s*([A-Za-z]+)", text or "")
    return match.group(1).upper() if match else ""


def _role(disposition: str, *, temporary: bool, passed: bool) -> str:
    status = _disposition(disposition)
    if status in ("NEW", "MOD"):
        return "PRODUCER"
    if status in ("OLD", "SHR"):
        return "CONSUMER"
    return "PRODUCER" if (temporary and not passed) else "CONSUMER"


def bind_dd_names(jcl_app, programs: dict[str, list[FileAssign]]) -> list[dict]:
    """Bindings of every step that runs a program present in ``programs``."""
    out: list[dict] = []
    by_program = {name.upper(): files for name, files in programs.items()}
    for job in jcl_app.jobs:
        for step in job.steps:
            program = (step.exec_.program if step.exec_ else "") or ""
            files = by_program.get(program.upper())
            if files is None:
                continue
            dds = {dd.name.upper(): dd for dd in step.dd_statements}
            used: set[str] = set()
            for assign in files:
                row = {
                    "job": job.name, "step": step.name, "program": program.upper(),
                    "file_name": assign.file_name, "ddname": assign.target,
                    "dataset": "", "disposition": "", "status": "", "detail": "",
                }
                if assign.kind != "DDNAME":
                    row.update(
                        ddname="", status="LITERAL_PATH",
                        detail=f"the program names its file itself ({assign.target!r}); not bound by JCL",
                    )
                else:
                    used.add(assign.target.upper())
                    dd = dds.get(assign.target.upper())
                    if dd is None:
                        row.update(
                            status="UNBOUND",
                            detail=f"no DD statement named {assign.target} in step {step.name}",
                        )
                    else:
                        row.update(
                            status="BOUND", dataset=dd.dataset or ("*INLINE*" if dd.is_inline else ""),
                            disposition=dd.disposition,
                        )
                out.append(row)
            for name, dd in dds.items():
                if name in used or name in STANDARD_DDS or dd.sysout:
                    continue
                out.append({
                    "job": job.name, "step": step.name, "program": program.upper(),
                    "file_name": "", "ddname": name, "dataset": dd.dataset,
                    "disposition": dd.disposition, "status": "UNUSED_DD",
                    "detail": f"no ASSIGN name of {program.upper()} uses DD {name}",
                })
    out.sort(key=lambda r: (r["job"], r["step"], r["ddname"], r["file_name"]))
    return out


def _kind(dd) -> str:
    if dd.is_inline:
        return "INLINE"
    if dd.sysout:
        return "SYSOUT"
    if dd.is_temporary or (dd.dataset or "").startswith("&&"):
        return "TEMPORARY"
    if _GDG.search(dd.dataset or ""):
        return "GDG_RELATIVE"
    return "PERMANENT"


def build_dataset_catalog(jcl_app) -> list[dict]:
    """Datasets named by DD statements with their uses, in deterministic order."""
    entries: dict[str, dict] = {}
    for job in jcl_app.jobs:
        for step in job.steps:
            for dd in step.dd_statements:
                if not dd.dataset:
                    continue
                kind = _kind(dd)
                entry = entries.setdefault(dd.dataset, {
                    "dsn": dd.dataset, "kind": kind, "uses": [], "flags": [],
                })
                if kind == "GDG_RELATIVE" and not entry["flags"]:
                    entry["flags"].append(
                        "relative generation (+n/0/-n) is catalogued but not resolved to a generation"
                    )
                passed = "PASS" in (dd.disposition or "").upper()
                entry["uses"].append({
                    "job": job.name, "step": step.name, "dd": dd.name,
                    "disposition": dd.disposition,
                    "role": _role(dd.disposition, temporary=kind == "TEMPORARY", passed=passed),
                })
    return [entries[key] for key in sorted(entries)]


def dataset_flows(jcl_app) -> list[dict]:
    """Producer-step -> consumer-step data flow, per dataset, in step order."""
    flows: list[dict] = []
    for job in jcl_app.jobs:
        produced: dict[str, str] = {}
        for step in job.steps:
            here = f"{job.name}.{step.name}"
            for dd in step.dd_statements:
                if not dd.dataset:
                    continue
                kind = _kind(dd)
                role = _role(dd.disposition, temporary=kind == "TEMPORARY",
                             passed="PASS" in (dd.disposition or "").upper())
                if role == "CONSUMER" and dd.dataset in produced and produced[dd.dataset] != here:
                    flows.append({"from": produced[dd.dataset], "to": here, "dsn": dd.dataset})
            for dd in step.dd_statements:
                if dd.dataset and _role(dd.disposition, temporary=_kind(dd) == "TEMPORARY",
                                        passed="PASS" in (dd.disposition or "").upper()) == "PRODUCER":
                    produced[dd.dataset] = here
    return sorted(flows, key=lambda f: (f["from"], f["to"], f["dsn"]))
