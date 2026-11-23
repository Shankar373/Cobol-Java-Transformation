"""Build the semantic-facts document from source files (Layer 5, phase P4).

``build_semantic_facts`` is the one entry point: for each COBOL source it runs the one parser (``parse_traced``), the P1
span table, the P2 symbol table and the P3 reference table, derives the document's facts, and assembles the canonical
:class:`~engine.semantic_facts.document.SemanticFacts`.  Nothing is parsed, resolved or read twice by another
authority.  A file that cannot be parsed is not dropped: it becomes a ``refusal`` fact with its diagnostics, and the
document is incomplete.

Inputs are ``(path, text)`` pairs; they are processed in sorted path order, so the result does not depend on the order
the caller supplies them (a test shuffles them).  Paths are checkpoint-relative, never absolute.
"""

from __future__ import annotations

import dataclasses
import hashlib
from typing import Iterable, Mapping, Sequence

from engine.semantic_facts.calls import build_call_facts
from engine.semantic_facts.document import (
    Fact,
    ProgramFacts,
    SemanticFacts,
    assemble,
    unsupported_fact,
    unsupported_rows,
)
from engine.semantic_facts.references import Reference, Resolution, build_reference_table
from engine.semantic_facts.span import build_span_table
from engine.semantic_facts.symbols import Declaration, SymbolTable, build_symbol_table
from engine.semantic_facts.references import ReferenceTable
from engine.transformation.cobol_parser import CobolParseError, CobolParser
from engine.transformation.control_flow import ends_run_unit
from engine.transformation.copybook_model import _find_copy_statements, _mask_comments
from engine.transformation.diagnostics import DiagnosticLevel
from enterprise.discovery.source_policy import classify_option

_REF_FACT = {"data": "data-ref", "paragraph": "paragraph-ref", "file": "file-ref", "condition": "condition-ref",
             "index": "index-ref", "host-var": "host-var-ref"}
COBOL_SUFFIXES = (".cbl", ".cob", ".cobol")


def source_digest_of(sources: Mapping[str, str]) -> str:
    """sha256 over the sorted ``(path, sha256(text))`` pairs: a digest of exactly the texts the document was built from."""
    rows = [f"{path}\0{hashlib.sha256(text.encode('utf-8')).hexdigest()}" for path, text in sorted(sources.items())]
    return hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()


def _resolved(candidate: str, rule: str) -> Resolution:
    return Resolution("resolved", (candidate,), rule=rule)


def _declaration_facts(symbols: SymbolTable) -> list[Fact]:
    facts: list[Fact] = []
    by_id = symbols.by_id()
    for decl in symbols.declarations:
        attributes = tuple(sorted((("level", str(decl.level)), ("name", decl.name), ("section", decl.section),
                                   ("qualification", "/".join(decl.qualification))) + decl.attributes))
        facts.append(Fact(decl.kind, decl.decl_id, decl.span, _resolved(decl.decl_id, "l5.declaration"),
                          "l5.declaration", attributes))
        if decl.parent and decl.kind in ("data-item", "record", "condition-name", "index-name", "linkage-param"):
            facts.append(Fact("contains", decl.decl_id, decl.span, _resolved(decl.parent, "l5.structure"),
                              "l5.structure", (("parent", decl.parent),)))
        attrs = dict(decl.attributes)
        if "occurs" in attrs:
            facts.append(Fact("occurs", decl.decl_id, decl.span, _resolved(decl.decl_id, "l5.structure"),
                              "l5.structure", (("count", attrs["occurs"]), ("depends_on", attrs.get("depends_on", "")))))
        if "redefines" in attrs:
            facts.append(_redefines(decl, attrs["redefines"], symbols, by_id))
        if decl.unsupported:
            facts.append(unsupported_fact(decl.unsupported, decl.decl_id, decl.span))
    return facts


def _redefines(decl: Declaration, base: str, symbols: SymbolTable, by_id: dict[str, Declaration]) -> Fact:
    candidates = tuple(sorted(d.decl_id for d in symbols.declarations
                              if d.addressable and d.scope == decl.scope and d.parent == decl.parent
                              and dict(d.attributes).get("generated_name", d.name) == base.upper()
                              and d.decl_id != decl.decl_id))
    if len(candidates) == 1:
        resolution = _resolved(candidates[0], "l5.structure")
    elif candidates:
        resolution = Resolution("ambiguous", candidates, confidence="heuristic", rule="l5.structure")
    else:
        resolution = Resolution("unresolved", reason="missing-data-item", confidence="unresolved", rule="l5.structure")
    return Fact("redefines", decl.decl_id, decl.span, resolution, "l5.structure", (("base", base.upper()),))


def _reference_facts(references: Iterable[Reference]) -> list[Fact]:
    return [Fact(_REF_FACT[r.kind], r.ref_id, r.span, r.resolution, "l5.reference" if not r.resolution.rule
                 else r.resolution.rule,
                 tuple(sorted((("access", r.access), ("name", r.name), ("owner_stmt", r.owner_stmt),
                               ("role", r.role)))))
            for r in references]


def _flow_facts(program, symbols: SymbolTable, references: Iterable[Reference]) -> list[Fact]:
    facts: list[Fact] = []
    for ref in references:
        if ref.kind == "paragraph" and ref.access in ("perform", "goto"):
            kind = "performs" if ref.access == "perform" else "goes-to"
            facts.append(Fact(kind, ref.owner_stmt, ref.span, ref.resolution, ref.resolution.rule,
                              (("target", ref.name), ("ref", ref.ref_id))))
    paragraph_ids = {d.name: d for d in symbols.declarations if d.kind == "paragraph" and not d.unsupported}
    paragraphs = list(program.paragraphs)
    for current, following in zip(paragraphs, paragraphs[1:]):
        if ends_run_unit(current) or (current.statements and type(current.statements[-1]).__name__ == "GoToStatement"):
            continue
        here, there = paragraph_ids.get(current.name.upper()), paragraph_ids.get(following.name.upper())
        if here is not None and there is not None:
            facts.append(Fact("falls-through", here.decl_id, here.span, _resolved(there.decl_id, "l5.flow"),
                              "l5.flow", (("next", there.decl_id),)))
    return facts


def _unsupported_use_facts(table) -> list[Fact]:
    return [unsupported_fact(u.code, u.owner_stmt, u.span, u.detail) for u in table.unsupported]


def _option_facts(file: str, options: Sequence[str]) -> tuple[list[Fact], list[tuple[str, str]]]:
    facts: list[Fact] = []
    extra: list[tuple[str, str]] = []
    for option in options:
        verdict = classify_option(option)
        attributes = (("class", verdict.klass), ("keyword", verdict.keyword), ("option", verdict.option))
        if verdict.unmodelled:
            facts.append(Fact("option", f"option:{file}:{verdict.option}", None,
                              Resolution("unsupported", reason="COMPILER_OPTION_UNMODELLED", rule="l5.option"),
                              "l5.option", attributes))
            extra.append(("COMPILER_OPTION_UNMODELLED", verdict.option))
        else:
            facts.append(Fact("option", f"option:{file}:{verdict.option}", None, _resolved(verdict.option, "l5.option"),
                              "l5.option", attributes))
    return facts, extra


def _refused(file: str, error: Exception) -> ProgramFacts:
    """A file the parser raised on: kept in the document as a refusal (never dropped), with no declarations."""
    subject = f"parse:{file}"
    fact = Fact("refusal", subject, None, Resolution("unsupported", reason="PARSE_ERROR", rule="l5.diagnostic"),
                "l5.diagnostic", (("code", "PARSE_ERROR"), ("message", str(error)[:200])))
    return ProgramFacts(file, SymbolTable(file, (), ()), ReferenceTable((), (), ()), (fact,),
                        (("PARSE_ERROR", subject, file),))


def _program_id(text: str) -> str:
    try:
        return CobolParser().parse(text).program_id.upper() or "UNKNOWN"
    except CobolParseError:
        return "UNKNOWN"


def build_program_facts(file: str, text: str, *, options: Sequence[str] = (), scope_id: str = "") -> ProgramFacts:
    parser = CobolParser()
    try:
        program, trace = parser.parse_traced(text)
    except CobolParseError as error:
        return _refused(file, error)
    spans = build_span_table(program, trace, file=file)
    symbols = build_symbol_table(program, trace, spans, scope_id=scope_id)
    references = build_reference_table(program, trace, spans, symbols, source=text)
    facts = _declaration_facts(symbols)
    facts += _reference_facts(references.references)
    facts += _flow_facts(program, symbols, references.references)
    facts += _unsupported_use_facts(references)
    extra: list[tuple[str, str]] = []
    for diagnostic in parser.diagnostics.all:
        refusal = diagnostic.level == DiagnosticLevel.ERROR or diagnostic.code.name == "UNSUPPORTED_CONSTRUCT"
        kind = "refusal" if refusal else "diagnostic"
        subject = f"diag:{file}:{diagnostic.code.name}:{diagnostic.location}"
        facts.append(Fact(kind, subject, None,
                          Resolution("unsupported", reason=diagnostic.code.name, rule="l5.diagnostic") if refusal
                          else _resolved(subject, "l5.diagnostic"), "l5.diagnostic",
                          (("code", diagnostic.code.name), ("level", diagnostic.level.name),
                           ("message", diagnostic.message[:200]))))
        if refusal:
            extra.append((diagnostic.code.name, subject))
    members = sorted({target for _start, _end, target in _find_copy_statements(_mask_comments(text))})
    if members:
        # COPY text is not expanded here: names declared by a copybook are `unresolved` until the caller supplies the
        # materialised program, and the document says so instead of looking complete.  The statements are found by the
        # COPY finder the copybook expansion itself uses (comments masked), not by a second pattern.
        for member in members:
            facts.append(unsupported_fact("COPYBOOK_NOT_EXPANDED", f"copy:{file}:{member}", None, member))
            extra.append(("COPYBOOK_NOT_EXPANDED", member))
    option_facts, option_extra = _option_facts(file, options)
    facts += option_facts
    extra += option_extra
    unique: dict[str, Fact] = {}
    for fact in facts:
        unique.setdefault(fact.fact_id, fact)
    return ProgramFacts(file, symbols, references, tuple(unique.values()),
                        unsupported_rows(symbols, references, file, extra), program, trace)


def _unique(facts: Iterable[Fact]) -> tuple[Fact, ...]:
    unique: dict[str, Fact] = {}
    for fact in facts:
        unique.setdefault(fact.fact_id, fact)
    return tuple(unique.values())


def build_semantic_facts(sources: Mapping[str, str], *, checkpoint_id: str = "", source_digest: str = "",
                         graph_id: str = "", profile_ids: Sequence[tuple[str, str]] = (),
                         options: Mapping[str, Sequence[str]] | None = None,
                         external_programs: Iterable[str] = (),
                         tool_version: str = "") -> SemanticFacts:
    """The facts document of ``sources`` (``path -> text``; only COBOL program texts, checkpoint-relative paths).

    ``source_digest`` defaults to a digest of exactly these texts.  ``options`` maps a path to its compiler options (the
    discovery profile's ``compiler_options``).  ``external_programs`` names CALL targets that are subsystem or platform
    programs outside the document (the graph's classification; MQI verbs and DL/I entries are always external).
    """
    options = options or {}
    ordered = sorted(sources)
    # two files declaring the same PROGRAM-ID would collide on scope ids: qualify those scopes with their file
    first_pass = {path: _program_id(sources[path]) for path in ordered}
    counts: dict[str, int] = {}
    for name in first_pass.values():
        counts[name] = counts.get(name, 0) + 1
    programs: list[ProgramFacts] = []
    for path in ordered:
        name = first_pass[path]
        scope = f"program:{name}@{path}" if counts[name] > 1 else ""
        programs.append(build_program_facts(path, sources[path], options=options.get(path, ()), scope_id=scope))
    calls = build_call_facts(programs, external=external_programs)
    programs = [dataclasses.replace(
        p, facts=_unique(p.facts + tuple(calls.facts.get(p.file, ()))),
        unsupported=tuple(sorted(p.unsupported + tuple((code, subject, p.file)
                                                       for code, subject in calls.unsupported.get(p.file, ())))))
        for p in programs]
    return assemble(programs, checkpoint_id=checkpoint_id, source_digest=source_digest or source_digest_of(sources),
                    graph_id=graph_id, profile_ids=tuple(profile_ids), tool_version=tool_version)


__all__ = ["COBOL_SUFFIXES", "build_program_facts", "build_semantic_facts", "source_digest_of"]
