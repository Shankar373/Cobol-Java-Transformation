"""Engine adapter between modernization output and the knowledge graph (Layer 3, gap 7 / criterion 9).

The only engine module that talks to :mod:`enterprise.discovery.traceability`.  It

* reads the discovery graph document (``dependency-graph.json``) and answers which programs a transformation covers
  (:func:`program_closure`), so the transformation consults the graph instead of re-scanning,
* walks the generated Java project and records, for every Java class and method, a ``generated-from`` edge to the
  COBOL program / paragraph / copybook node of the *same* graph (:func:`trace_generation`),
* records ``verified-by`` edges from the evidence the pipeline produced (:func:`record_verification`), and
* produces the lineage pairs carried by the sealed evidence manifest (:func:`lineage_pairs`).

Everything is deterministic: files are visited in sorted order and nothing depends on time or absolute paths.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from enterprise.discovery.kg_query import reachable
from enterprise.discovery.traceability import (
    TraceabilityError,
    TraceabilityOverlay,
    java_class_id,
    java_method_id,
)

__all__ = ["JavaClassInfo", "TraceReport", "load_graph_document", "program_closure", "scan_java_project",
           "trace_generation", "record_verification", "lineage_pairs", "normalise_name"]

_CLASS = re.compile(r"^\s*(?:(?:public|final|abstract|static)\s+)*(?:class|record|interface|enum)\s+([A-Za-z_]\w*)")
_METHOD = re.compile(
    r"^\s*(?:(?:public|private|protected|static|final|synchronized)\s+)*[\w<>\[\],.?]+(?:\s*<[^>]*>)?\s+"
    r"([A-Za-z_][\w$]*)\s*\([^;{}]*\)\s*(?:throws\s+[\w.,\s]+)?\{")
_NOT_METHODS = frozenset({"if", "for", "while", "switch", "catch", "synchronized", "try", "else", "return", "new"})
_STRING = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])\'')
_RECORD_SUFFIXES = ("Record", "Layout")
#: Runtime-support classes the generators emit for a whole program set (not for one COBOL program).  They are traced
#: to the entry program with ``role=runtime-support`` rather than left without an origin; any other class that cannot
#: be matched stays untraced.
SUPPORT_CLASSES = frozenset({"ServiceRegistry"})


def normalise_name(name: str) -> str:
    """Case- and separator-insensitive key joining a COBOL name (``MY-PROG``) to its Java spelling (``MyProg``)."""
    return re.sub(r"[-_$\s]", "", name).lower()


@dataclass(frozen=True)
class JavaClassInfo:
    name: str
    path: str
    sha256: str
    line: int
    methods: tuple[tuple[str, int], ...] = ()


@dataclass
class TraceReport:
    """What :func:`trace_generation` recorded; ``untraced`` must be empty for criterion 9 to hold."""
    classes: list[str] = field(default_factory=list)
    methods: list[str] = field(default_factory=list)
    untraced: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"classes": sorted(self.classes), "methods": sorted(self.methods), "untraced": sorted(self.untraced)}


def load_graph_document(path: str | Path) -> dict[str, Any]:
    """Read a discovery graph document; anything but an object with node and edge lists is refused."""
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(document.get("nodes"), list) \
            or not isinstance(document.get("edges"), list):
        raise TraceabilityError(f"{path} is not a knowledge-graph document")
    return document


def program_closure(document: dict[str, Any], entry_program: str) -> list[str]:
    """Program names (upper case) reachable from ``entry_program`` over ``calls`` edges, entry included.

    This is the program set a transformation of that entry point must cover; it comes from the graph, not from a
    second scan.  Unknown entry raises ``KeyError``.
    """
    entry = f"program:{entry_program.upper()}"
    if not any(n.get("id") == entry for n in document["nodes"]):
        raise KeyError(f"program {entry_program!r} is not in the knowledge graph")
    calls = {"nodes": document["nodes"], "edges": [e for e in document["edges"] if e.get("relation") == "calls"]}
    found = {entry} | reachable(calls, entry, "out", None)
    return sorted(n.split(":", 1)[1] for n in found if n.startswith("program:"))


# -- generated Java ------------------------------------------------------------------------------------------------
def _scan_text(text: str, rel: str, sha: str) -> list[JavaClassInfo]:
    """Top-level classes with their depth-1 methods, by brace depth (string literals neutralised first)."""
    classes: list[JavaClassInfo] = []
    depth = 0
    current: tuple[str, int] | None = None
    methods: list[tuple[str, int]] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = _STRING.sub('""', raw)
        if depth == 0:
            match = _CLASS.match(line)
            if match and current is None:
                current = (match.group(1), number)
                methods = []
        elif depth == 1 and current is not None:
            match = _METHOD.match(line)
            if match and match.group(1) not in _NOT_METHODS:
                methods.append((match.group(1), number))
        depth += line.count("{") - line.count("}")
        if depth <= 0 and current is not None:
            classes.append(JavaClassInfo(current[0], rel, sha, current[1], tuple(methods)))
            current, depth = None, 0
    return classes


def scan_java_project(project_dir: str | Path) -> list[JavaClassInfo]:
    """Every Java class under ``project_dir`` (sorted by path), with POSIX relative paths and file digests."""
    root = Path(project_dir)
    found: list[JavaClassInfo] = []
    for java in sorted(p for p in root.rglob("*.java") if p.is_file()):
        data = java.read_bytes()
        found.extend(_scan_text(data.decode("utf-8", errors="replace"), java.relative_to(root).as_posix(),
                                hashlib.sha256(data).hexdigest()))
    return found


def _index(document: dict[str, Any]) -> tuple[dict[str, str], dict[str, str], dict[str, dict[str, str]]]:
    """program key -> node id, copybook key -> node id, program node id -> {paragraph key -> node id}."""
    programs: dict[str, str] = {}
    copybooks: dict[str, str] = {}
    paragraphs: dict[str, dict[str, str]] = {}
    ambiguous: set[str] = set()
    for node in document["nodes"]:
        node_id, kind = str(node["id"]), str(node["kind"])
        if kind in ("program", "copybook") and node.get("origin", "input") == "input":
            table = programs if kind == "program" else copybooks
            key = normalise_name(node_id.split(":", 1)[1])
            if key in table:
                ambiguous.add(f"{kind}:{key}")
            table[key] = node_id
        elif kind == "paragraph" and "/" in node_id:
            owner, para = node_id.split(":", 1)[1].split("/", 1)
            paragraphs.setdefault(f"program:{owner}", {})[normalise_name(para)] = node_id
    for entry in ambiguous:  # two names that differ only by separators/case: refuse to guess
        kind, key = entry.split(":", 1)
        (programs if kind == "program" else copybooks).pop(key, None)
    return programs, copybooks, paragraphs


def trace_generation(overlay: TraceabilityOverlay, project_dir: str | Path, *, source_digest: str = "",
                     program_ids: Iterable[str] | None = None, entry_program: str = "") -> TraceReport:
    """Record ``generated-from`` for every Java class (and every method of a program class) under ``project_dir``.

    Classes that cannot be tied to exactly one program or copybook node are *not* guessed: they are returned in
    ``TraceReport.untraced`` and the caller must treat them as a failure (criterion 9).
    ``program_ids`` (when given) restricts which graph programs generated code may map to.  Runtime-support classes
    (:data:`SUPPORT_CLASSES`) are traced to ``entry_program`` (default: the first of ``program_ids``).
    """
    document = overlay.document()
    programs, copybooks, paragraphs = _index(document)
    if program_ids is not None:
        wanted = {normalise_name(p) for p in program_ids}
        programs = {k: v for k, v in programs.items() if k in wanted}
    report = TraceReport()
    ordered = list(program_ids) if program_ids is not None else []
    support_origin = programs.get(normalise_name(entry_program or (ordered[0] if ordered else "")))
    for info in scan_java_project(project_dir):
        key = normalise_name(info.name)
        origin = programs.get(key)
        is_program = origin is not None
        if origin is None:
            for suffix in _RECORD_SUFFIXES:
                if info.name.endswith(suffix):
                    origin = copybooks.get(normalise_name(info.name[: -len(suffix)]))
                    break
        class_id = java_class_id(info.name)
        support = origin is None and info.name in SUPPORT_CLASSES and support_origin is not None
        if support:
            origin = support_origin
        if origin is None:
            report.untraced.append(class_id)
            continue
        overlay.record_generated_from(class_id, "java-class", origin, path=info.path, sha256=info.sha256,
                                      line=info.line, source_digest=source_digest,
                                      extra={"role": "runtime-support"} if support else None)
        report.classes.append(class_id)
        if support:
            for method, line in info.methods:  # ``callSubpgm`` dispatches to program SUBPGM
                target = programs.get(normalise_name(method[4:])) if method.startswith("call") else None
                if target is not None:
                    method_id = java_method_id(info.name, method)
                    overlay.record_generated_from(method_id, "java-method", target, path=info.path,
                                                  sha256=info.sha256, line=line, source_digest=source_digest,
                                                  extra={"role": "runtime-support"})
                    overlay.record_contains(class_id, method_id, path=info.path, line=line)
                    report.methods.append(method_id)
            continue
        if not is_program:
            continue
        for method, line in info.methods:
            paragraph = paragraphs.get(origin, {}).get(normalise_name(method))
            method_id = java_method_id(info.name, method)
            overlay.record_generated_from(method_id, "java-method", paragraph or origin, path=info.path,
                                          sha256=info.sha256, line=line, source_digest=source_digest)
            overlay.record_contains(class_id, method_id, path=info.path, line=line)
            report.methods.append(method_id)
    return report


# -- evidence ------------------------------------------------------------------------------------------------------
def record_verification(overlay: TraceabilityOverlay, *, run_id: str, manifest_hash: str, verdict_state: str,
                        artifact_path: str, subjects: Iterable[str],
                        test_cases: Iterable[tuple[str, str, str]] = ()) -> list[str]:
    """Record ``verified-by`` from each subject to the run (and tests) that produced the evidence.

    Only a ``VERIFIED`` verdict yields edges: an equivalence run that did not verify is not evidence, and recording
    it as ``certain`` would be a false claim.  Returns the evidence node ids recorded (empty when nothing verified).
    ``test_cases`` is ``(name, checksum, artifact_path)`` triples, each attached to every subject.
    """
    if str(verdict_state).upper() != "VERIFIED":
        return []
    recorded: list[str] = []
    for subject in sorted(set(subjects)):
        edge = overlay.record_verified_by(subject, "run", run_id, checksum=manifest_hash, artifact_path=artifact_path)
        recorded.append(edge.dst)
        for name, checksum, path in test_cases:
            recorded.append(overlay.record_verified_by(subject, "test-case", name, checksum=checksum,
                                                       artifact_path=path).dst)
    return sorted(set(recorded))


def lineage_pairs(overlay: TraceabilityOverlay) -> tuple[tuple[str, str], ...]:
    """The pairs the sealed evidence manifest carries: the discovery graph id and this overlay's id."""
    return (("graph_id", overlay.parent_graph_id), ("traceability_overlay_id", overlay.overlay_id))
