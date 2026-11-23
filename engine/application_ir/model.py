"""The canonical COBOL Application IR (Layer 6): immutable, typed, and a pure projection of Layer 5 semantic facts.

Every element keeps the Layer 5 identity, span (with its COPY chain), resolution state, confidence, rule and named
unsupported reason *verbatim*; there is no free-text field and nothing here is computed from source text.  An element that
cannot name the Layer 5 id it came from does not exist (``provenance`` is mandatory).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.semantic_facts.references import Resolution
from engine.semantic_facts.span import Span

#: Closed vocabulary of typed edges (each is one Layer 5 fact kind; see ``project.EDGE_OF_FACT``).
EDGE_KINDS = (
    "call", "call-arity", "call-binding", "call-size-compat", "performs", "goes-to", "falls-through", "redefines",
    "reads-item", "writes-item", "file-binding", "sql-table", "sql-host-var", "jcl-dd-binding", "copy-site",
)
#: Meta facts kept as notes (they say what is *not* known).
NOTE_KINDS = ("unsupported", "diagnostic", "refusal", "option", "cancel")


@dataclass(frozen=True)
class IRDeclaration:
    decl_id: str
    kind: str
    name: str
    level: int
    file: str
    scope: str
    parent: str
    qualification: tuple[str, ...]
    section: str
    span: Span | None
    span_code: str
    attributes: tuple[tuple[str, str], ...]
    unsupported: str
    graph_node_id: str
    graph_node_collapsed: bool
    origin_member: str
    template_id: str
    addressable: bool


@dataclass(frozen=True)
class IRReference:
    ref_id: str
    kind: str
    access: str
    owner_stmt: str
    name: str
    qualifiers: tuple[str, ...]
    resolution: Resolution
    span: Span | None
    role: str
    subscripts: tuple[str, ...]
    refmod: bool


@dataclass(frozen=True)
class IREdge:
    """A typed relationship.  ``source`` and ``target`` are Layer 5 ids (or ``""`` for an unresolved target); ``provenance``
    is the Layer 5 fact (or reference) id it was projected from."""

    edge_id: str
    kind: str
    source: str
    target: str
    resolution: Resolution
    span: Span | None
    provenance: str
    attributes: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class IRNote:
    note_id: str
    kind: str
    subject: str
    code: str
    span: Span | None
    provenance: str
    attributes: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class IRProgram:
    decl_id: str
    name: str
    file: str
    scope: str
    entries: tuple[str, ...]
    paragraphs: tuple[str, ...]
    files: tuple[str, ...]
    data_roots: tuple[str, ...]
    unsupported: tuple[str, ...]     # named reasons attached to this program's declarations, sorted, unique


@dataclass(frozen=True)
class ApplicationIR:
    bindings: tuple[tuple[str, str], ...]        # semantic_id, facts_digest, graph_id, checkpoint_id, ... (strings)
    complete: bool
    unsupported_summary: tuple[tuple[str, int], ...]
    programs: tuple[IRProgram, ...]
    declarations: tuple[IRDeclaration, ...]
    references: tuple[IRReference, ...]
    edges: tuple[IREdge, ...]
    notes: tuple[IRNote, ...]

    def binding(self, key: str) -> str:
        return dict(self.bindings).get(key, "")


def span_dict(span: Span | None) -> dict[str, Any] | None:
    return None if span is None else span.as_dict()


def resolution_dict(resolution: Resolution) -> dict[str, Any]:
    return {"candidates": list(resolution.candidates), "confidence": resolution.confidence,
            "reason": resolution.reason, "rule": resolution.rule, "state": resolution.state,
            "variable": resolution.variable}
