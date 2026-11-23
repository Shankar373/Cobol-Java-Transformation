"""Cross-program facts: CALL, dynamic CALL, USING, LINKAGE, ENTRY, CANCEL and argument binding (Layer 5, phase P5).

Every ``CallStatement`` of every program in the document gets a ``call`` fact; a call whose callee is one program of
the document also gets ``call-arity`` (arguments passed against the callee's ``PROCEDURE DIVISION USING`` header, not
against a count of ``01`` items), one ``call-binding`` per argument (caller item <-> callee LINKAGE parameter, with the
passing mode) and one ``call-size-compat`` per binding.  All of it is derived from the P2/P3 tables and the IR; nothing
is parsed a second time, with one exception that is a check, not a source of facts: the parser splits ``USING`` on
white space, so the argument list is re-read from the statement's own logical lines with the shared operand tokenizer
and compared with the IR.  Any disagreement (``BY VALUE x RETURNING r`` is the known one) makes the call's arity and
bindings ``unsupported(CALL_USING_UNPARSED)`` at the call's span: a wrong binding is never reported.

Targets (design 6.1): a literal resolves against the document's ``program`` and ``entry`` declarations through the one
name normalisation; several matches are ``ambiguous``; a subsystem entry (MQI verbs, DL/I entries, or a caller-supplied
set) is resolved ``external``; anything else is ``unresolved(missing-program)``.  A dynamic target is ``dynamic`` with
the literals provable from the program's own ``MOVE 'literal' TO var`` statements and the item's ``VALUE`` clause.  The
IR has no CANCEL statement: each ``CANCEL`` line becomes ``unsupported(CANCEL_NOT_IN_IR)`` rather than vanishing.

Layout is claimed only where certified: an elementary DISPLAY item, or a group of such items, with no OCCURS, REDEFINES
or non-DISPLAY usage.  Anything else is ``unknown`` + ``unsupported(LAYOUT_USAGE_UNCERTIFIED)``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from engine.semantic_facts.document import Fact, ProgramFacts, unsupported_fact
from engine.semantic_facts.references import Resolution, Resolver, parse_operand, split_operands
from engine.semantic_facts.span import Span, _place
from engine.semantic_facts.symbols import Declaration
from engine.transformation.control_flow import walk_statements
from engine.transformation.ir import PicType, normalize_cobol_name
from engine.transformation.subsystem_calls import DLI_ENTRIES, MQI_VERBS

EXTERNAL_PROGRAMS = frozenset(MQI_VERBS | DLI_ENTRIES)
MODES = ("REFERENCE", "CONTENT", "VALUE")
_STOP_WORDS = frozenset({"RETURNING", "ON", "NOT", "END-CALL"})


def _resolved(candidate: str, rule: str, confidence: str = "certain") -> Resolution:
    return Resolution("resolved", (candidate,), confidence=confidence, rule=rule)


def _unquote(text: str) -> str:
    text = text.strip()
    return text[1:-1] if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"" else text


# ----- the argument list as written ---------------------------------------------------------------------------

def written_arguments(text: str) -> list[tuple[str, str]] | None:
    """``(operand, mode)`` pairs of the ``USING`` list of one CALL statement text, or ``None`` when there is no USING.

    Literals are single tokens; ``BY REFERENCE|CONTENT|VALUE`` sets the mode for the operands that follow (default
    REFERENCE); the list ends at ``RETURNING``, ``ON EXCEPTION``, ``NOT ON``, ``END-CALL`` or the period.
    """
    tokens = split_operands(text)
    upper = [t.upper() for t in tokens]
    if "USING" not in upper:
        return None
    pairs: list[tuple[str, str]] = []
    mode = "REFERENCE"
    index = upper.index("USING") + 1
    while index < len(tokens):
        word = upper[index].rstrip(".")
        if word in _STOP_WORDS:
            break
        if word == "BY":
            index += 1
            continue
        if word in MODES and upper[index - 1] == "BY":
            mode = word
            index += 1
            continue
        pairs.append((tokens[index].rstrip("."), mode))
        if tokens[index].endswith(".") and not tokens[index].startswith(("'", '"')):
            break
        index += 1
    return pairs


def _statement_text(trace: Any, start: int) -> str:
    """The logical lines from the statement's first line up to the next statement's first line."""
    starts = sorted({frame.start for frame in trace.statements if frame.start > start})
    end = starts[0] if starts else len(trace.code)
    return " ".join(trace.code[start:end])


def header_parameters(program: Any) -> tuple[str, ...]:
    """The parameter names of ``PROCEDURE DIVISION USING``.  The parser keeps the ``BY REFERENCE|CONTENT|VALUE`` words
    in ``using_parameters`` (``USING BY REFERENCE X`` is stored as three entries); they are reserved words, never a
    name, so they are dropped here and the IR is left as it is."""
    return tuple(name for name in program.using_parameters if name.upper() not in ("BY", *MODES))


# ----- layout ------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Layout:
    size: int
    klass: str          # "numeric" | "alphanumeric"
    elementary: bool


def layout_of(item: Any) -> Layout | None:
    """The certified storage size and class of ``item``, or ``None`` when it is not certified."""
    if item is None or item.occurs or item.occurs_depending_on or item.redefines or item.usage:
        return None
    if item.children:
        parts = [layout_of(c) for c in item.children if c.level != 88]
        if not parts or any(p is None for p in parts):
            return None
        return Layout(sum(p.size for p in parts if p is not None), "alphanumeric", False)
    if item.pic_length <= 0:
        return None
    klass = "numeric" if item.pic_type == PicType.NUMERIC and not item.edit_pic else "alphanumeric"
    size = item.pic_length + (1 if item.sign_separate else 0)
    return Layout(size, klass, True)


def size_verdict(caller: Layout | None, callee: Layout | None, mode: str) -> str:
    if caller is None or callee is None:
        return "unknown"
    if mode == "VALUE" and not (caller.elementary and callee.elementary and caller.klass == callee.klass == "numeric"):
        return "class_mismatch"
    if caller.klass != callee.klass and caller.elementary and callee.elementary:
        return "class_mismatch"
    if caller.size == callee.size:
        return "equal"
    return "caller_smaller" if caller.size < callee.size else "caller_larger"


# ----- dynamic targets ---------------------------------------------------------------------------------------

def literal_values(program: Any, variable: str) -> tuple[str, ...]:
    """Quoted literals ``variable`` provably holds in ``program``: its VALUE clause and every ``MOVE 'lit' TO variable``."""
    found: set[str] = set()
    target = variable.upper()
    for paragraph in program.paragraphs:
        for statement in walk_statements(paragraph.statements):
            if type(statement).__name__ == "MoveStatement":
                source = statement.source_expr
                if (type(source).__name__ == "Literal" and not source.is_numeric
                        and target in {t.upper() for t in (statement.targets or (statement.target,))}):
                    found.add(source.value.upper())
    for root in (*program.working_storage, *program.linkage_section):
        stack = [root]
        while stack:
            item = stack.pop()
            if item.name.upper() == target and item.value and item.value.strip()[:1] in "'\"":
                found.add(_unquote(item.value).upper())
            stack.extend(item.children)
    return tuple(sorted(found))


# ----- the pass ----------------------------------------------------------------------------------------------

@dataclass
class CallFacts:
    facts: dict[str, list[Fact]]
    unsupported: dict[str, list[tuple[str, str]]]

    def add(self, file: str, fact: Fact) -> None:
        self.facts.setdefault(file, []).append(fact)
        if fact.resolution.state == "unsupported":
            self.unsupported.setdefault(file, []).append((fact.resolution.reason, fact.subject))


def build_call_facts(programs: Sequence[ProgramFacts], *, external: Iterable[str] = ()) -> CallFacts:
    """Cross-program facts for ``programs`` (sorted by file by the caller); ``external`` adds subsystem names."""
    external_names = {normalize_cobol_name(n) for n in external} | EXTERNAL_PROGRAMS
    registry: dict[str, list[tuple[ProgramFacts, Declaration]]] = {}
    nested: set[str] = set()
    for program in programs:
        for decl in program.symbols.declarations:
            if decl.kind in ("program", "entry"):
                registry.setdefault(normalize_cobol_name(decl.name), []).append((program, decl))
        nested |= {u.subject.upper() for u in program.symbols.unsupported if u.code == "NESTED_PROGRAM_NOT_MODELLED"}
    out = CallFacts({}, {})
    for caller in programs:
        if caller.program is None:
            continue
        flat = any(u.code == "NESTED_PROGRAM_NOT_MODELLED" for u in caller.symbols.unsupported)
        resolver = Resolver(caller.symbols)
        rows = caller.references.statements
        walked = [s for p in caller.program.paragraphs for s in walk_statements(p.statements)]
        frames = caller.trace.statement_index()
        for statement, row in zip(walked, rows):
            if type(statement).__name__ != "CallStatement":
                continue
            frame = frames.get(id(statement))
            _call(out, caller, statement, row.stmt_id, row.span, frame, registry, nested, external_names, flat,
                  resolver)
        _cancels(out, caller)
    return out


def _call(out: CallFacts, caller: ProgramFacts, statement: Any, stmt_id: str, span: Span | None, frame: Any,
          registry: dict[str, list[tuple[ProgramFacts, Declaration]]], nested: set[str], external: set[str],
          flat: bool, resolver: Resolver) -> None:
    file = caller.file
    base_confidence = "derived" if flat else "certain"
    attrs: list[tuple[str, str]] = [("arguments", str(len(statement.arguments))),
                                    ("returning", statement.returning.upper()), ("statement", stmt_id)]
    callee_program: ProgramFacts | None = None
    callee_decl: Declaration | None = None
    if statement.is_dynamic:
        variable = statement.program_name.rstrip(".")
        _carrier_resolution, carrier_decl = resolver.data(variable.split("(")[0].strip(), ())
        literals = literal_values(caller.program, variable)
        carrier = carrier_decl.decl_id if carrier_decl is not None else ""
        resolution = Resolution(
            "dynamic", literals, reason="" if literals else "dynamic-target", variable=carrier,
            confidence="heuristic" if literals else "unresolved", rule="l5.call-dynamic")
        attrs += [("target", variable.upper()), ("call_type", "DYNAMIC")]
        out.add(file, Fact("call", stmt_id, span, resolution, "l5.call-dynamic", tuple(sorted(attrs))))
        return
    target = normalize_cobol_name(statement.program_name.rstrip("."))
    attrs += [("target", target), ("call_type", "STATIC")]
    found = registry.get(target, [])
    if len(found) == 1:
        callee_program, callee_decl = found[0]
        attrs.append(("self_call", str(callee_program is caller and callee_decl.kind == "program").lower()))
        if callee_decl.kind == "entry":
            attrs.append(("via_entry", "true"))
        resolution = _resolved(callee_decl.decl_id, "l5.call-flat" if flat else "l5.call-literal", base_confidence)
    elif found:
        resolution = Resolution("ambiguous", tuple(sorted(d.decl_id for _p, d in found)), confidence="heuristic",
                                rule="l5.call-literal")
    elif target in nested:
        resolution = Resolution("unsupported", reason="NESTED_PROGRAM_NOT_MODELLED", rule="l5.call-literal")
    elif target in external:
        resolution = _resolved(f"external:{target}", "l5.call-external")
        attrs.append(("external", "true"))
    else:
        resolution = Resolution("unresolved", reason="missing-program", confidence="unresolved", rule="l5.call-literal")
    out.add(file, Fact("call", stmt_id, span, resolution, resolution.rule or "l5.call-literal", tuple(sorted(attrs))))
    if callee_program is None or callee_decl is None or callee_program.program is None:
        return
    entry_params = dict(callee_decl.attributes).get("parameters") if callee_decl.kind == "entry" else None
    header = (tuple(p for p in entry_params.split(",") if p) if entry_params is not None
              else header_parameters(callee_program.program))
    _arguments(out, caller, callee_program, statement, stmt_id, span, frame, resolver, header)


def _arguments(out: CallFacts, caller: ProgramFacts, callee: ProgramFacts, statement: Any, stmt_id: str,
               span: Span | None, frame: Any, resolver: Resolver, header: tuple[str, ...]) -> None:
    file = caller.file
    written = None
    if frame is not None and 0 <= frame.start < len(caller.trace.code):
        written = written_arguments(_statement_text(caller.trace, frame.start))
    ir_pairs = list(zip((a.upper() for a in statement.arguments), (m.upper() for m in statement.passing_modes)))
    if written is None:
        written_pairs: list[tuple[str, str]] = []
    else:
        written_pairs = [(raw.upper(), mode) for raw, mode in written]
    if written is None and statement.arguments or written is not None and written_pairs != ir_pairs:
        out.add(file, unsupported_fact("CALL_USING_UNPARSED", stmt_id, span,
                                       f"IR {ir_pairs} != written {written_pairs}"))
        return
    arity_ok = len(statement.arguments) == len(header)
    out.add(file, Fact("call-arity", stmt_id, span, _resolved(stmt_id, "l5.call-arity"), "l5.call-arity",
                       tuple(sorted((("arity_ok", str(arity_ok).lower()), ("expected", str(len(header))),
                                     ("passed", str(len(statement.arguments))),
                                     ("callee_file", callee.file))))))
    callee_params = {d.name: d for d in callee.symbols.declarations if d.kind == "linkage-param"}
    for index, ((raw, mode), param_name) in enumerate(zip(((a, m) for a, m in ir_pairs), header), 1):
        subject = f"{stmt_id}#arg{index}"
        operand = parse_operand(raw)
        param = callee_params.get(param_name.upper())
        caller_decl: Declaration | None = None
        if operand.kind == "name":
            _res, caller_decl = resolver.data(operand.name, operand.qualifiers)
        attributes = [("index", str(index)), ("mode", mode), ("operand", raw), ("parameter", param_name.upper())]
        if caller_decl is not None:
            attributes.append(("caller", caller_decl.decl_id))
        if param is None:
            out.add(file, Fact("call-binding", subject, span,
                               Resolution("unresolved", reason="missing-data-item", confidence="unresolved",
                                          rule="l5.call-binding"), "l5.call-binding", tuple(sorted(attributes))))
            continue
        attributes.append(("callee", param.decl_id))
        out.add(file, Fact("call-binding", subject, span, _resolved(param.decl_id, "l5.call-binding"),
                           "l5.call-binding", tuple(sorted(attributes))))
        if operand.kind == "literal" or operand.kind == "figurative" or caller_decl is None:
            verdict, why = "unknown", "ARGUMENT_NOT_A_DATA_ITEM"
        else:
            caller_layout = layout_of(caller_decl.item)
            callee_layout = layout_of(param.item)
            verdict = size_verdict(caller_layout, callee_layout, mode)
            why = "LAYOUT_USAGE_UNCERTIFIED" if verdict == "unknown" else ""
        size_attrs = tuple(sorted((("verdict", verdict), ("mode", mode), ("callee", param.decl_id)) +
                                  ((("caller", caller_decl.decl_id),) if caller_decl is not None else ())))
        if verdict == "unknown" and why == "LAYOUT_USAGE_UNCERTIFIED":
            out.add(file, Fact("call-size-compat", subject, span,
                               Resolution("unsupported", reason=why, rule="l5.call-size"), "l5.call-size", size_attrs))
        else:
            out.add(file, Fact("call-size-compat", subject, span, _resolved(subject, "l5.call-size"), "l5.call-size",
                               size_attrs + ((("detail", why),) if why else ())))


def _cancels(out: CallFacts, caller: ProgramFacts) -> None:
    """Each ``CANCEL`` logical line as an unsupported fact (the IR has no CANCEL statement)."""
    trace = caller.trace
    if trace is None:
        return
    for index, line in enumerate(trace.code):
        words = split_operands(line)
        if words and words[0].upper() == "CANCEL":
            span = _place(trace, index, file=caller.file, origins=None)
            targets = ",".join(w.rstrip(".") for w in words[1:])
            out.add(caller.file, Fact(
                "cancel", f"cancel:{caller.file}:{index}", span,
                Resolution("unsupported", reason="CANCEL_NOT_IN_IR", rule="l5.cancel"), "l5.cancel",
                (("target", targets.upper()),)))
