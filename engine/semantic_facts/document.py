"""The canonical, content-addressed semantic-facts document (Layer 5, phase P4).

``SemanticFacts`` is the one object later layers read.  It lists scopes, declarations, references and facts of every
program in a checkpoint, each with a span and a resolution, and carries two content addresses (design 5.5):

* ``facts_digest`` - sha256 of the canonical bytes of the **body** alone, so two checkpoints can be compared on content;
* ``semantic_id`` - sha256 of the body *and* its bindings (checkpoint id, source digest, graph id, profile ids), so the
  same facts under another graph or profile are a different document.

Canonical bytes are ``graph.canonical_bytes`` (sorted keys, compact separators, ASCII).  There are no timestamps, no
absolute paths, no ``id()`` and no dict-order dependence: the same inputs give identical bytes on every run and under any
input-file order.  ``complete`` is false whenever anything is named unsupported or refused: a consumer must read
``unsupported_summary`` and never take an absent fact as proof.

``verify`` recomputes both addresses from the document's own content and reports every mismatch.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from engine.semantic_facts.references import Reference, ReferenceTable, Resolution
from engine.semantic_facts.span import Span
from engine.semantic_facts.symbols import Declaration, Scope, SymbolTable, UnsupportedFact
from enterprise.discovery.graph import canonical_bytes

SCHEMA = "systemaops.semantic-facts/1.0"
TOOL = "systemaops-semantic-facts"

FACT_KINDS = (
    # declarations
    "program", "entry", "paragraph", "file", "record", "data-item", "condition-name", "index-name",
    "linkage-param", "special-register",
    # references
    "data-ref", "paragraph-ref", "file-ref", "condition-ref", "index-ref", "host-var-ref",
    # structure and flow
    "contains", "redefines", "occurs", "performs", "goes-to", "falls-through",
    # meta
    "unsupported", "diagnostic", "refusal", "option",
    # cross-program (P5) and external resources (P6)
    "call", "call-arity", "call-binding", "call-size-compat", "cancel", "file-binding",
)

def sha256_of(payload: Any) -> str:
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def _span_dict(span: Span | None) -> dict[str, Any] | None:
    return None if span is None else span.as_dict()


def _span_key(span: Span | None) -> str:
    return "" if span is None else f"{span.file}:{span.line}:{span.column}:{span.end_line}:{span.end_column}"


def _sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
    span = row.get("span") or {}
    return (span.get("file", ""), span.get("line", 0), span.get("column", 0), row.get("kind", ""),
            row.get("subject", ""), row.get("fact_id", row.get("ref_id", row.get("decl_id", ""))))


def resolution_dict(resolution: Resolution) -> dict[str, Any]:
    return {"candidates": list(resolution.candidates), "confidence": resolution.confidence,
            "reason": resolution.reason, "rule": resolution.rule, "state": resolution.state,
            "variable": resolution.variable}


@dataclass(frozen=True)
class Fact:
    kind: str
    subject: str
    span: Span | None
    resolution: Resolution
    rule: str
    attributes: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in FACT_KINDS:
            raise ValueError(f"unknown fact kind {self.kind!r}")
        if self.rule != self.resolution.rule and self.resolution.rule:
            raise ValueError("a fact's rule is its resolution's rule")

    @property
    def fact_id(self) -> str:
        digest = hashlib.sha256(
            f"{self.kind}|{self.subject}|{_span_key(self.span)}|{self.rule}|{self.attributes}".encode()).hexdigest()
        return "fact:" + digest[:16]

    def as_dict(self) -> dict[str, Any]:
        return {"attributes": dict(self.attributes), "fact_id": self.fact_id, "kind": self.kind,
                "resolution": resolution_dict(self.resolution), "rule": self.rule,
                "span": _span_dict(self.span), "subject": self.subject}


def declaration_dict(decl: Declaration, file: str) -> dict[str, Any]:
    return {
        "addressable": decl.addressable, "attributes": dict(decl.attributes), "decl_id": decl.decl_id, "file": file,
        "graph_node_collapsed": decl.graph_node_collapsed, "graph_node_id": decl.graph_node_id, "kind": decl.kind,
        "level": decl.level, "name": decl.name, "origin_member": decl.origin_member, "parent": decl.parent,
        "qualification": list(decl.qualification), "scope": decl.scope, "section": decl.section,
        "span": _span_dict(decl.span), "span_code": decl.span_code, "template_id": decl.template_id,
        "unsupported": decl.unsupported,
    }


def reference_dict(ref: Reference) -> dict[str, Any]:
    return {"access": ref.access, "kind": ref.kind, "name": ref.name, "owner_stmt": ref.owner_stmt,
            "qualifiers": list(ref.qualifiers), "ref_id": ref.ref_id, "refmod": ref.refmod,
            "resolution": resolution_dict(ref.resolution), "role": ref.role, "span": _span_dict(ref.span),
            "subscripts": list(ref.subscripts)}


def scope_dict(scope: Scope, file: str) -> dict[str, Any]:
    return {"file": file, "global_names": sorted(scope.global_names), "kind": scope.kind, "parent": scope.parent,
            "scope_id": scope.scope_id}


@dataclass(frozen=True)
class ProgramFacts:
    """Everything derived for one source file (one parse)."""

    file: str
    symbols: SymbolTable
    references: ReferenceTable
    facts: tuple[Fact, ...]
    unsupported: tuple[tuple[str, str, str], ...]     # (code, subject, file) for the document's summary


@dataclass(frozen=True)
class SemanticFacts:
    header: dict[str, Any]
    scopes: tuple[dict[str, Any], ...]
    declarations: tuple[dict[str, Any], ...]
    references: tuple[dict[str, Any], ...]
    facts: tuple[dict[str, Any], ...]

    def body(self) -> dict[str, Any]:
        return {"declarations": list(self.declarations), "facts": list(self.facts),
                "references": list(self.references), "scopes": list(self.scopes)}

    def as_dict(self) -> dict[str, Any]:
        return {"schema": SCHEMA, "header": self.header, **self.body()}

    def canonical(self) -> bytes:
        return canonical_bytes(self.as_dict())

    @property
    def semantic_id(self) -> str:
        return str(self.header["semantic_id"])

    @property
    def facts_digest(self) -> str:
        return str(self.header["facts_digest"])

    @property
    def complete(self) -> bool:
        return bool(self.header["complete"])


def bindings_of(header: dict[str, Any]) -> dict[str, Any]:
    return {"checkpoint_id": header["checkpoint_id"], "graph_id": header["graph_id"],
            "profile_ids": header["profile_ids"], "source_digest": header["source_digest"]}


def assemble(programs: list[ProgramFacts], *, checkpoint_id: str = "", source_digest: str = "", graph_id: str = "",
             profile_ids: tuple[tuple[str, str], ...] = (), tool_version: str = "") -> SemanticFacts:
    """The document for ``programs`` (any order: everything is sorted by content, never by arrival)."""
    scopes: list[dict[str, Any]] = []
    declarations: list[dict[str, Any]] = []
    references: list[dict[str, Any]] = []
    facts: list[dict[str, Any]] = []
    summary: dict[str, int] = {}
    for program in sorted(programs, key=lambda p: p.file):
        scopes.extend(scope_dict(s, program.file) for s in program.symbols.scopes)
        declarations.extend(declaration_dict(d, program.file) for d in program.symbols.declarations)
        references.extend(reference_dict(r) for r in program.references.references)
        facts.extend(f.as_dict() for f in program.facts)
        for code, _subject, _file in program.unsupported:
            summary[code] = summary.get(code, 0) + 1
    scopes.sort(key=lambda r: (r["file"], r["scope_id"]))
    declarations.sort(key=lambda r: (r["file"], r["span"]["line"] if r["span"] else 0, r["decl_id"]))
    references.sort(key=lambda r: (r["span"]["file"] if r["span"] else "", r["span"]["line"] if r["span"] else 0,
                                   r["ref_id"]))
    facts.sort(key=_sort_key)
    ids = [d["decl_id"] for d in declarations]
    if len(set(ids)) != len(ids):
        raise ValueError("declaration ids are not unique across the document")
    body = {"declarations": declarations, "facts": facts, "references": references, "scopes": scopes}
    header: dict[str, Any] = {
        "checkpoint_id": checkpoint_id, "complete": not summary, "graph_id": graph_id,
        "id_algorithm": "sha256", "profile_ids": [list(pair) for pair in sorted(profile_ids)],
        "source_digest": source_digest, "tool": TOOL, "tool_version": tool_version,
        "unsupported_summary": dict(sorted(summary.items())),
    }
    header["facts_digest"] = sha256_of(body)
    header["semantic_id"] = sha256_of({"bindings": bindings_of(header), "body": body})
    return SemanticFacts(header, tuple(scopes), tuple(declarations), tuple(references), tuple(facts))


def verify(document: dict[str, Any]) -> list[str]:
    """Every way ``document`` (a parsed ``as_dict()``) disagrees with itself; empty when it is intact."""
    problems: list[str] = []
    header = document.get("header") or {}
    if document.get("schema") != SCHEMA:
        problems.append(f"schema is {document.get('schema')!r}, expected {SCHEMA!r}")
    body = {key: document.get(key, []) for key in ("declarations", "facts", "references", "scopes")}
    digest = sha256_of(body)
    if header.get("facts_digest") != digest:
        problems.append("facts_digest does not match the body")
    try:
        semantic = sha256_of({"bindings": bindings_of(header), "body": body})
    except KeyError as missing:
        return problems + [f"header lacks {missing}"]
    if header.get("semantic_id") != semantic:
        problems.append("semantic_id does not match the body and its bindings")
    declared = {d.get("decl_id") for d in body["declarations"]}
    if len(declared) != len(body["declarations"]):
        problems.append("duplicate decl_id")
    for ref in body["references"]:
        res = ref.get("resolution", {})
        if res.get("state") == "resolved" and not set(res.get("candidates", [])) <= declared:
            problems.append(f"{ref.get('ref_id')} resolves to an undeclared id")
        if res.get("state") not in ("resolved",) and not (res.get("reason") or res.get("candidates")):
            problems.append(f"{ref.get('ref_id')} is not resolved and says neither why nor to what")
    fact_ids = [f.get("fact_id") for f in body["facts"]]
    if len(set(fact_ids)) != len(fact_ids):
        problems.append("duplicate fact_id")
    return problems


def unsupported_rows(symbols: SymbolTable, references: ReferenceTable, file: str,
                     extra: list[tuple[str, str]]) -> tuple[tuple[str, str, str], ...]:
    """``(code, subject, file)`` of everything named unsupported or refused for one file."""
    rows = [(u.code, u.subject, file) for u in symbols.unsupported]
    rows += [(d.unsupported, d.decl_id, file) for d in symbols.declarations if d.unsupported]
    rows += [(u.code, u.owner_stmt, file) for u in references.unsupported]
    rows += [(code, subject, file) for code, subject in extra]
    return tuple(sorted(rows))


def unsupported_fact(code: str, subject: str, span: Span | None, detail: str = "") -> Fact:
    attributes = (("detail", detail[:200]),) if detail else ()
    return Fact("unsupported", subject, span, Resolution("unsupported", reason=code, rule="l5.unsupported"),
                "l5.unsupported", attributes)


__all__ = [
    "FACT_KINDS", "Fact", "ProgramFacts", "SCHEMA", "SemanticFacts", "UnsupportedFact", "assemble", "bindings_of",
    "declaration_dict", "reference_dict", "sha256_of", "unsupported_fact", "unsupported_rows", "verify",
]
