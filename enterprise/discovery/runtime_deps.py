"""Runtime dependencies and COBOL dialect evidence, derived from scanner findings (never from guesses).

Every item carries the source positions that justify it.  A dialect is reported as *indicative*: the signals are
facts about the source, but only a compile with the customer's compiler can prove the dialect.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from .findings import Fact, Ref
from .inventory import FileRecord

__all__ = ["runtime_dependencies", "dialect_report", "EVIDENCE_CAP"]

EVIDENCE_CAP = 25
UTILITIES = frozenset({"IDCAMS", "IEFBR14", "IEBGENER", "IEBCOPY", "SORT", "ICETOOL", "ICEGENER", "IKJEFT01", "IKJEFT1B",
                       "DFSRRC00", "DSNUTILB", "DFHCSDUP", "CSQUTIL", "BPXBATCH", "FTP", "ADRDSSU"})
VSAM = "VSAM (indexed/relative files)"
Note = Callable[..., None]


@dataclass
class _Item:
    category: str
    name: str
    evidence: list[tuple[str, int]] = field(default_factory=list)
    detail: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        unique = sorted(set(self.evidence))
        out: dict[str, object] = {
            "category": self.category, "evidence": [{"file": f, "line": ln} for f, ln in unique[:EVIDENCE_CAP]],
            "evidence_count": len(unique), "name": self.name,
        }
        if self.detail:
            out["detail"] = dict(sorted(self.detail.items()))
        return out


def runtime_dependencies(records: list[FileRecord]) -> list[dict[str, object]]:
    """Subsystems, utilities, libraries, settings and tools the estate needs at run time or build time."""
    items: dict[tuple[str, str], _Item] = {}

    def note(category: str, name: str, file: str, line: int, **detail: str) -> None:
        item = items.setdefault((category, name), _Item(category, name))
        item.evidence.append((file, line))
        item.detail.update({k: v for k, v in detail.items() if v})

    for record in sorted(records, key=lambda r: r.path):
        if record.scan is None:
            continue
        for fact in record.scan.facts:
            _from_fact(note, record, fact)
        for ref in record.scan.refs:
            _from_ref(note, record, ref)
    return [items[key].as_dict() for key in sorted(items)]


_FACT_SUBSYSTEM = {
    "cics-command": "CICS", "cics-resource-definition": "CICS", "sql-statement": "DB2/SQL", "sql-include": "DB2/SQL",
    "dynamic-sql": "DB2/SQL", "sql-declare-table": "DB2/SQL", "db2-bind": "DB2/SQL", "dli-command": "IMS",
    "mq-definition": "MQ",
}


def _from_fact(note: Note, record: FileRecord, fact: Fact) -> None:
    info = dict(fact.detail)
    where = (record.path, fact.line)
    category = fact.category
    if category in _FACT_SUBSYSTEM:
        note("subsystem", _FACT_SUBSYSTEM[category], *where)
    elif category == "sort-verb":
        note("utility", "SORT (DFSORT/SYNCSORT/GnuCOBOL sort)", *where)
    elif (category == "file-select" and info.get("vsam_candidate") == "yes") or category in ("vsam-cluster", "vsam-aix"):
        note("subsystem", VSAM, *where, organization=info.get("organization", ""))
    elif category == "environment":
        note("environment-variable", fact.name, *where, access=info.get("access", ""))
    elif category in ("os-command", "runtime-command"):
        note("os-command", fact.name, *where)
    elif category == "java-dependency":
        note("java-dependency", fact.name, *where, source=info.get("source", ""))
    elif category == "runtime-setting":
        note("runtime-setting", fact.name, *where, value=info.get("value", ""))
    elif category == "build-invocation":
        note("build-tool", fact.name, *where, flags=info.get("flags", ""))
    elif category == "compile-step":
        note("build-tool", info.get("compiler") or info.get("procedure") or "COBOL compile step", *where)
    elif category == "link-step":
        note("build-tool", info.get("linker", "linkage editor"), *where)
    elif category == "compiler-option":
        note("compiler-option", fact.name, *where)
    elif category == "ims-region":
        note("subsystem", "IMS", *where, region=info.get("region", ""))


def _from_ref(note: Note, record: FileRecord, ref: Ref) -> None:
    where = (record.path, ref.line)
    info = dict(ref.detail)
    relation = ref.relation
    if relation == "uses-mq" or (relation == "uses-queue" and ref.target_kind == "mq-queue"):
        note("subsystem", "MQ", *where)
    elif relation == "uses-ims":
        note("subsystem", "IMS", *where)
    elif relation == "uses-runtime":
        category = {"LE": "language-environment", "DB2": "db2-runtime"}.get(info.get("subsystem", ""), "cobol-runtime-library")
        note(category, ref.target, *where)
    elif relation == "executes" and ref.target_kind == "program" and ref.target in UTILITIES:
        note("utility", ref.target, *where)
    elif relation in ("cics-link", "cics-xctl", "cics-load", "starts-transaction", "uses-map", "uses-cics-file"):
        note("subsystem", "CICS", *where)
    elif relation in ("uses-db2", "accesses-table"):
        note("subsystem", "DB2/SQL", *where)
    elif relation == "assigns-file" and ref.target_kind == "external-file":
        note("external-file", ref.target, *where)
    elif relation == "uses-library" and info.get("purpose") in ("steplib", "joblib", "ims-reslib", "load-library"):
        note("load-library", ref.target, *where, purpose=info.get("purpose", ""))
    elif relation == "uses-library" and info.get("purpose") in ("copybook-path", "library-path", "syslib", "procedure-library"):
        note("library-path", ref.target, *where, purpose=info.get("purpose", ""))


# --- dialects ---------------------------------------------------------------------------------------------------------

_HINT_TO_DIALECT = {
    "ibm": "ibm-enterprise", "ibm-or-extension": "ibm-enterprise", "ibm-or-ansi": "ibm-enterprise",
    "gnucobol": "gnucobol", "gnucobol-or-microfocus": "gnucobol-or-microfocus", "microfocus": "microfocus",
    "legacy-cobol74": "legacy-cobol74", "ansi85": "cobol85", "cobol85-intrinsic": "cobol2002-intrinsic-functions",
    "object-oriented": "object-oriented-cobol", "extension": "vendor-extension",
}
_SHARED = "gnucobol-or-microfocus"
_WEAK_SIGNALS = frozenset({"GOBACK", "DAY-OF-WEEK", "COMP-5"})


def _signal(fact: Fact) -> tuple[str, str]:
    """``(dialect, label)`` a fact indicates, or ``("", "")``."""
    info = dict(fact.detail)
    if fact.category == "dialect-signal":
        return _HINT_TO_DIALECT.get(info.get("hint", ""), ""), fact.name
    if fact.category == "compiler-option":
        return "ibm-enterprise", f"CBL option {fact.name}"
    if fact.category in ("cics-command", "dli-command", "sql-statement"):
        return "ibm-enterprise", fact.category
    if fact.category == "directive":
        return ("gnucobol-or-microfocus" if fact.name.startswith(">>") else "microfocus"), fact.name[:30]
    if fact.category == "program-id" and info.get("kind") in ("CLASS-ID", "INTERFACE-ID"):
        return "object-oriented-cobol", info["kind"]
    return "", ""


def dialect_report(records: list[FileRecord]) -> dict[str, object]:
    """Per-file dialect signals and a project summary; ``undetermined`` when there is no signal or the top two tie."""
    per_file: list[dict[str, object]] = []
    totals: dict[str, int] = {}
    for record in sorted(records, key=lambda r: r.path):
        if record.cls not in ("cobol", "copybook") or record.scan is None:
            continue
        evidence: dict[str, list[tuple[str, int]]] = {}
        for fact in record.scan.facts:
            dialect, label = _signal(fact)
            if dialect:
                evidence.setdefault(dialect, []).append((label, fact.line))
        shared = evidence.pop(_SHARED, [])
        for dialect in ("gnucobol", "microfocus"):  # a signal both compilers accept counts for each of them
            if shared:
                evidence.setdefault(dialect, []).extend(shared)
        for dialect, items in evidence.items():
            totals[dialect] = totals.get(dialect, 0) + len(items)
        # A lone weak signal (GOBACK, COMP-5) is shared by several compilers and does not decide a dialect.
        decisive = {d: v for d, v in evidence.items() if any(label not in _WEAK_SIGNALS for label, _ in v)}
        ranked = sorted(decisive.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        tie = len(ranked) > 1 and len(ranked[0][1]) == len(ranked[1][1])
        per_file.append({
            "candidates": [{"dialect": d, "evidence_count": len(v),
                            "examples": [{"line": ln, "signal": label} for label, ln in sorted(v, key=lambda x: x[1])[:5]]}
                           for d, v in sorted(evidence.items(), key=lambda kv: (-len(kv[1]), kv[0]))],
            "file": record.path,
            "primary": ranked[0][0] if ranked and not tie else "undetermined",
            "source_format": record.source_format,
        })
    summary = sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))
    return {
        "basis": "indicative: derived from source signals; only the customer's compiler can confirm a dialect",
        "files": per_file,
        "summary": [{"dialect": d, "evidence_count": n} for d, n in summary],
        "undetermined_files": sorted(str(f["file"]) for f in per_file if f["primary"] == "undetermined"),
    }
