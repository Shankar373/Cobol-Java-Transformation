"""Project a Layer 5 semantic-facts document into the canonical Application IR, serialise it, and prove it faithful.

``project`` is a pure function of the document (``SemanticFacts.as_dict()``): same document, same IR, byte for byte.  It reads
no source, no graph and no clock.  ``coverage`` checks the no-loss rule - every document fact is represented (by a
declaration, a reference, an edge or a note) - and ``verify`` re-projects the document and compares: an IR that is not
exactly the projection of its facts is reported, whatever its digest says.
"""

from __future__ import annotations

import hashlib
from typing import Any, Mapping

from engine.application_ir.model import (
    EDGE_KINDS,
    NOTE_KINDS,
    ApplicationIR,
    IRDeclaration,
    IREdge,
    IRNote,
    IRProgram,
    IRReference,
    resolution_dict,
    span_dict,
)
from engine.semantic_facts.references import Resolution
from engine.semantic_facts.span import CopyFrame, Span
from enterprise.discovery.graph import canonical_bytes

SCHEMA = "systemaops.application-ir/1.0"
TOOL = "systemaops-application-ir"

#: Fact kinds that are represented by a Layer 5 declaration (checked by ``coverage``, not stored twice).
DECLARATION_FACTS = frozenset({"program", "entry", "paragraph", "file", "record", "data-item", "condition-name",
                               "index-name", "linkage-param", "special-register", "contains", "occurs"})
REFERENCE_FACTS = frozenset({"data-ref", "paragraph-ref", "file-ref", "condition-ref", "index-ref", "host-var-ref"})
#: Facts that become a typed edge of the same name.
EDGE_FACTS = frozenset(EDGE_KINDS) - {"reads-item", "writes-item"}
_ITEM_KINDS = frozenset({"data", "condition", "index", "host-var"})
_BINDING_KEYS = ("checkpoint_id", "facts_digest", "graph_bound", "graph_id", "semantic_id", "source_digest", "tool_version")


def sha256_of(payload: Any) -> str:
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def span_of(raw: Mapping[str, Any] | None) -> Span | None:
    if not raw:
        return None
    via = tuple(CopyFrame(str(f["file"]), int(f["line"]), str(f["target"])) for f in raw.get("via_copy", ()))
    return Span(str(raw["file"]), int(raw["line"]), int(raw["column"]), int(raw.get("end_line", 0)),
                int(raw.get("end_column", 0)), via, str(raw.get("basis", "token")), bool(raw.get("exact", True)),
                str(raw.get("note", "")))


def resolution_of(raw: Mapping[str, Any]) -> Resolution:
    return Resolution(str(raw["state"]), tuple(raw.get("candidates", ())), str(raw.get("reason", "")),
                      str(raw.get("variable", "")), str(raw.get("confidence", "certain")), str(raw.get("rule", "")))


def _pairs(raw: Mapping[str, Any] | None) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((str(k), str(v)) for k, v in (raw or {}).items()))


def _first(resolution: Resolution) -> str:
    return resolution.candidates[0] if resolution.state == "resolved" and resolution.candidates else ""


def _edge_id(kind: str, source: str, target: str, provenance: str) -> str:
    return "edge:" + hashlib.sha256(f"{kind}|{source}|{target}|{provenance}".encode()).hexdigest()[:16]


def _owner_program(stmt_id: str, scopes: list[tuple[str, str]]) -> str:
    """The program declaration id of the scope a ``stmt:<scope>/...`` id belongs to (longest scope prefix wins)."""
    for scope, program in scopes:
        if stmt_id.startswith(f"stmt:{scope}/"):
            return program
    return ""


def _fact_edge(fact: Mapping[str, Any], scopes: list[tuple[str, str]]) -> IREdge:
    kind, subject = str(fact["kind"]), str(fact["subject"])
    attributes = fact.get("attributes") or {}
    resolution = resolution_of(fact["resolution"])
    source, target = subject, _first(resolution)
    if kind == "call":
        source = _owner_program(subject, scopes) or subject
    elif kind in ("call-arity", "call-size-compat"):
        source, target = subject, str(attributes.get("callee", ""))
        if kind == "call-arity":
            target = ""
    elif kind == "call-binding":
        source = str(attributes.get("caller", subject))
    return IREdge(_edge_id(kind, source, target, str(fact["fact_id"])), kind, source, target, resolution,
                  span_of(fact.get("span")), str(fact["fact_id"]), _pairs(attributes))


def _reference_edges(ref: Mapping[str, Any]) -> list[IREdge]:
    if ref["kind"] not in _ITEM_KINDS:
        return []
    access = str(ref["access"])
    kinds = [k for k, hit in (("reads-item", access in ("read", "modify")), ("writes-item", access in ("write", "modify")))
             if hit]
    resolution = resolution_of(ref["resolution"])
    attrs = _pairs({"access": access, "name": ref["name"], "role": ref["role"]})
    return [IREdge(_edge_id(k, str(ref["owner_stmt"]), _first(resolution), str(ref["ref_id"])), k, str(ref["owner_stmt"]),
                   _first(resolution), resolution, span_of(ref.get("span")), str(ref["ref_id"]), attrs) for k in kinds]


def _note(fact: Mapping[str, Any]) -> IRNote:
    attributes = fact.get("attributes") or {}
    resolution = fact["resolution"]
    code = str(resolution.get("reason") or attributes.get("code") or attributes.get("class") or "")
    return IRNote(str(fact["fact_id"]), str(fact["kind"]), str(fact["subject"]), code, span_of(fact.get("span")),
                  str(fact["fact_id"]), _pairs(attributes))


def _declaration(raw: Mapping[str, Any]) -> IRDeclaration:
    return IRDeclaration(
        str(raw["decl_id"]), str(raw["kind"]), str(raw["name"]), int(raw["level"]), str(raw["file"]), str(raw["scope"]),
        str(raw["parent"]), tuple(raw["qualification"]), str(raw["section"]), span_of(raw.get("span")),
        str(raw.get("span_code", "")), _pairs(raw.get("attributes")), str(raw.get("unsupported", "")),
        str(raw.get("graph_node_id", "")), bool(raw.get("graph_node_collapsed", False)), str(raw.get("origin_member", "")),
        str(raw.get("template_id", "")), bool(raw.get("addressable", True)))


def _reference(raw: Mapping[str, Any]) -> IRReference:
    return IRReference(str(raw["ref_id"]), str(raw["kind"]), str(raw["access"]), str(raw["owner_stmt"]), str(raw["name"]),
                       tuple(raw["qualifiers"]), resolution_of(raw["resolution"]), span_of(raw.get("span")), str(raw["role"]),
                       tuple(raw["subscripts"]), bool(raw["refmod"]))


def _programs(declarations: tuple[IRDeclaration, ...]) -> tuple[IRProgram, ...]:
    out = []
    for program in (d for d in declarations if d.kind == "program"):
        mine = [d for d in declarations if d.scope == program.scope]
        under = lambda kinds: tuple(sorted(d.decl_id for d in mine if d.kind in kinds and d.parent == program.decl_id))  # noqa: E731
        out.append(IRProgram(
            program.decl_id, program.name, program.file, program.scope, under(("entry",)), under(("paragraph",)),
            under(("file",)), under(("data-item", "record", "linkage-param")),
            tuple(sorted({d.unsupported for d in mine if d.unsupported}))))
    return tuple(sorted(out, key=lambda p: (p.file, p.decl_id)))


def project(document: Mapping[str, Any]) -> ApplicationIR:
    """The Application IR of one facts document (pure; raises ``ValueError``/``KeyError`` on a malformed document)."""
    header = document["header"]
    declarations = tuple(sorted((_declaration(d) for d in document["declarations"]),
                                key=lambda d: (d.file, d.span.line if d.span else 0, d.decl_id)))
    program_of_scope = {d.scope: d.decl_id for d in declarations if d.kind == "program"}
    scopes = sorted(program_of_scope.items(), key=lambda kv: -len(kv[0]))
    references = tuple(sorted((_reference(r) for r in document["references"]),
                              key=lambda r: ((r.span.file, r.span.line) if r.span else ("", 0), r.ref_id)))
    edges = [_fact_edge(f, scopes) for f in document["facts"] if f["kind"] in EDGE_FACTS]
    for raw in document["references"]:
        edges.extend(_reference_edges(raw))
    notes = tuple(sorted((_note(f) for f in document["facts"] if f["kind"] in NOTE_KINDS), key=lambda n: n.note_id))
    bindings = tuple(sorted((k, str(header.get(k, ""))) for k in _BINDING_KEYS))
    summary = tuple(sorted((str(k), int(v)) for k, v in header.get("unsupported_summary", {}).items()))
    return ApplicationIR(
        bindings, bool(header.get("complete")), summary, _programs(declarations), declarations, references,
        tuple(sorted(edges, key=lambda e: (e.span.file if e.span else "", e.span.line if e.span else 0, e.kind, e.edge_id))),
        notes)


# ----- serialisation and identity -------------------------------------------------------------------------------

def _decl_dict(d: IRDeclaration) -> dict[str, Any]:
    return {"addressable": d.addressable, "attributes": dict(d.attributes), "decl_id": d.decl_id, "file": d.file,
            "graph_node_collapsed": d.graph_node_collapsed, "graph_node_id": d.graph_node_id, "kind": d.kind,
            "level": d.level, "name": d.name, "origin_member": d.origin_member, "parent": d.parent,
            "qualification": list(d.qualification), "scope": d.scope, "section": d.section, "span": span_dict(d.span),
            "span_code": d.span_code, "template_id": d.template_id, "unsupported": d.unsupported}


def body_dict(ir: ApplicationIR) -> dict[str, Any]:
    return {
        "complete": ir.complete,
        "declarations": [_decl_dict(d) for d in ir.declarations],
        "edges": [{"attributes": dict(e.attributes), "edge_id": e.edge_id, "kind": e.kind, "provenance": e.provenance,
                   "resolution": resolution_dict(e.resolution), "source": e.source, "span": span_dict(e.span),
                   "target": e.target} for e in ir.edges],
        "notes": [{"attributes": dict(n.attributes), "code": n.code, "kind": n.kind, "note_id": n.note_id,
                   "provenance": n.provenance, "span": span_dict(n.span), "subject": n.subject} for n in ir.notes],
        "programs": [{"data_roots": list(p.data_roots), "decl_id": p.decl_id, "entries": list(p.entries),
                      "file": p.file, "files": list(p.files), "name": p.name, "paragraphs": list(p.paragraphs),
                      "scope": p.scope, "unsupported": list(p.unsupported)} for p in ir.programs],
        "references": [{"access": r.access, "kind": r.kind, "name": r.name, "owner_stmt": r.owner_stmt,
                        "qualifiers": list(r.qualifiers), "ref_id": r.ref_id, "refmod": r.refmod,
                        "resolution": resolution_dict(r.resolution), "role": r.role, "span": span_dict(r.span),
                        "subscripts": list(r.subscripts)} for r in ir.references],
        "unsupported_summary": dict(ir.unsupported_summary),
    }


def ir_id_of(ir: ApplicationIR) -> str:
    """Content address: the body and every binding to the facts it was projected from."""
    return sha256_of({"bindings": dict(ir.bindings), "body": body_dict(ir), "tool": TOOL})


def to_dict(ir: ApplicationIR) -> dict[str, Any]:
    return {"schema": SCHEMA, "header": {"bindings": dict(ir.bindings), "ir_id": ir_id_of(ir), "tool": TOOL},
            **body_dict(ir)}


def canonical(ir: ApplicationIR) -> bytes:
    return canonical_bytes(to_dict(ir))


# ----- proofs ---------------------------------------------------------------------------------------------------

def coverage(ir: ApplicationIR, document: Mapping[str, Any]) -> list[str]:
    """Everything in the document the IR does not represent (empty = nothing lost), plus anything in the IR that names no
    Layer 5 id (nothing invented)."""
    problems: list[str] = []
    decls = {d.decl_id: d for d in ir.declarations}
    refs = {r.ref_id for r in ir.references}
    provenance = {e.provenance for e in ir.edges} | {n.provenance for n in ir.notes}
    for fact in document["facts"]:
        kind, subject, fact_id = fact["kind"], fact["subject"], fact["fact_id"]
        if kind in DECLARATION_FACTS:
            decl = decls.get(subject)
            if decl is None:
                problems.append(f"{fact_id} ({kind}) lost: no declaration {subject}")
            elif kind == "contains" and decl.parent != fact["resolution"]["candidates"][0]:
                problems.append(f"{fact_id} (contains) disagrees with the declaration's parent")
            elif kind == "occurs" and "occurs" not in dict(decl.attributes):
                problems.append(f"{fact_id} (occurs) lost from the declaration's attributes")
        elif kind in REFERENCE_FACTS:
            if subject not in refs:
                problems.append(f"{fact_id} ({kind}) lost: no reference {subject}")
        elif kind in EDGE_FACTS or kind in NOTE_KINDS:
            if fact_id not in provenance:
                problems.append(f"{fact_id} ({kind}) lost: no edge or note")
        else:
            problems.append(f"{fact_id}: fact kind {kind!r} has no projection")
    known = {f["fact_id"] for f in document["facts"]} | {r["ref_id"] for r in document["references"]}
    problems += [f"edge {e.edge_id} invented: provenance {e.provenance} is not in the document"
                 for e in ir.edges if e.provenance not in known]
    problems += [f"note {n.note_id} invented: provenance {n.provenance} is not in the document"
                 for n in ir.notes if n.provenance not in known]
    return problems


def verify(ir_dict: Mapping[str, Any], document: Mapping[str, Any]) -> list[str]:
    """Why ``ir_dict`` (a serialised IR) is not the faithful projection of ``document``; empty when it is."""
    problems: list[str] = []
    try:
        expected = project(document)
    except (KeyError, ValueError, TypeError) as exc:
        return [f"the document cannot be projected: {exc}"]
    if ir_dict.get("schema") != SCHEMA:
        problems.append("schema differs")
    header = ir_dict.get("header") or {}
    body = {k: v for k, v in ir_dict.items() if k not in ("schema", "header")}
    if header.get("ir_id") != sha256_of({"bindings": header.get("bindings", {}), "body": body, "tool": header.get("tool")}):
        problems.append("ir_id does not match the IR's own content")
    if body != body_dict(expected):
        problems.append("the IR is not the projection of the document it names")
    if header.get("bindings") != dict(expected.bindings):
        problems.append("bindings differ from the document's")
    return problems + coverage(expected, document)
