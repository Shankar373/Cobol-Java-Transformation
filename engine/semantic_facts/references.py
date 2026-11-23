"""Typed references, access classification and resolution (Layer 5, phase P3).

Every name the IR uses in a statement becomes one :class:`Reference`: what it names (``kind``), how the statement
touches it (``access``), the statement it is in (a deterministic ``stmt_id``), and a complete
:class:`Resolution`.  Nothing here parses source text or resolves a name by a second algorithm: the declarations come
from the P2 :class:`~engine.semantic_facts.symbols.SymbolTable`, the statement walk matches the P1 span walk, and the
classification table is one function per IR statement class (:data:`STATEMENT_RULES`, checked against the ``Statement``
union by a test, so a new IR class without a row fails).

What an IR operand string cannot tell is never guessed: a statement the parser only partly understood
(``reasons``), a condition with no structured form, a literal-or-name ambiguity in INSPECT phrases, an unparseable
operand - each is an :class:`UnsupportedUse` with a named code at the statement's span.  CALL program names are P5.

Qualification: ``qualified_names`` has already rewritten a resolvable ``A OF G`` to the unique generated name before
the IR exists, so a use is looked up by the IR spelling first (``derived`` confidence when that is a generated name),
then by source name: several declarations of one source name are ``ambiguous`` with all candidates listed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Iterator

from engine.semantic_facts.span import Span, SpanTable
from engine.semantic_facts.symbols import Declaration, SymbolTable
from engine.transformation.parse_trace import ParseTrace

REF_KINDS = ("data", "paragraph", "file", "condition", "index", "host-var")
ACCESS = ("read", "write", "modify", "perform", "goto", "open", "close", "call", "none")
RESOLUTION_STATES = ("resolved", "ambiguous", "unresolved", "dynamic", "unsupported")
#: The graph's own vocabulary subset used here (a test compares each with ``graph.UNRESOLVED_REASONS``).
REASONS = ("missing-data-item", "missing-paragraph", "missing-logical-file", "missing-program", "missing-dd",
           "unbound-ddname", "external-table")
CONFIDENCE = ("certain", "derived", "heuristic", "unresolved")
L5_RULES = ("l5.data-name", "l5.data-name-generated", "l5.data-name-qualified", "l5.special-register",
            "l5.paragraph-name", "l5.file-name",
            # P4: the rules that produce the non-reference facts of the document
            "l5.declaration", "l5.reference", "l5.structure", "l5.flow", "l5.unsupported", "l5.diagnostic",
            "l5.option",
            # P5: cross-program facts
            "l5.call-literal", "l5.call-external", "l5.call-dynamic", "l5.call-flat", "l5.call-arity",
            "l5.call-binding", "l5.call-size", "l5.cancel",
            # P6: external resources read from the graph
            "l5.file-binding", "l5.sql-table", "l5.sql-host-var", "l5.jcl-dd")
UNSUPPORTED_USE_CODES = (
    "STATEMENT_PARTLY_PARSED", "CONDITION_UNSTRUCTURED", "OPERAND_UNPARSED", "INSPECT_OPERAND_KIND_UNKNOWN",
    "GOTO_TARGET_UNPARSED",
)

_DATA_DECLS = ("data-item", "linkage-param", "record", "condition-name", "index-name", "special-register")


@dataclass(frozen=True)
class Resolution:
    state: str
    candidates: tuple[str, ...] = ()
    reason: str = ""
    variable: str = ""
    confidence: str = "certain"
    rule: str = ""

    def __post_init__(self) -> None:
        if self.state not in RESOLUTION_STATES or self.confidence not in CONFIDENCE:
            raise ValueError(f"bad resolution {self.state}/{self.confidence}")
        if self.state == "resolved" and len(self.candidates) != 1:
            raise ValueError("a resolved reference names exactly one declaration")
        if self.state == "ambiguous" and len(self.candidates) < 2:
            raise ValueError("an ambiguous reference lists its candidates")
        if self.state == "unresolved" and (self.reason not in REASONS or self.confidence != "unresolved"):
            raise ValueError("an unresolved reference carries a graph reason and 'unresolved' confidence")
        if self.state not in ("resolved",) and not (self.reason or self.candidates):
            raise ValueError("a non-resolved state needs a reason or candidates")
        if self.rule and self.rule not in L5_RULES:
            raise ValueError(f"unknown rule {self.rule}")


@dataclass(frozen=True)
class Reference:
    ref_id: str
    kind: str
    access: str
    owner_stmt: str
    name: str               # IR spelling, upper-case
    qualifiers: tuple[str, ...]
    resolution: Resolution
    span: Span | None
    role: str               # which operand of the statement (``source``, ``target``, ``condition`` ...)
    subscripts: tuple[str, ...] = ()    # ref_ids
    refmod: bool = False


@dataclass(frozen=True)
class UnsupportedUse:
    owner_stmt: str
    code: str
    detail: str
    span: Span | None


@dataclass(frozen=True)
class StatementRow:
    stmt_id: str
    cls: str
    paragraph: str
    span: Span | None


@dataclass(frozen=True)
class ReferenceTable:
    statements: tuple[StatementRow, ...]
    references: tuple[Reference, ...]
    unsupported: tuple[UnsupportedUse, ...]


# ----- operands -----------------------------------------------------------------------------------------------

_NUMBER = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)$")
_FIGURATIVE = frozenset({"ZERO", "ZEROS", "ZEROES", "SPACE", "SPACES", "HIGH-VALUE", "HIGH-VALUES", "LOW-VALUE",
                         "LOW-VALUES", "QUOTE", "QUOTES", "NULL", "NULLS", "TRUE", "FALSE", "OMITTED"})
_NAME = re.compile(r"^([A-Z0-9][\w-]*)((?:\s+(?:OF|IN)\s+[A-Z0-9][\w-]*)*)\s*(?:\((.*)\))?$", re.IGNORECASE)
_QUALIFIER = re.compile(r"\s+(?:OF|IN)\s+([A-Z0-9][\w-]*)", re.IGNORECASE)
_ARITHMETIC = frozenset({"+", "-", "*", "/", "**"})
#: Words the IR leaves inside an operand string of a condition (``IF A NOT = B`` is stored as the name ``"A NOT"``);
#: reserved words, so never a data name.
_CONDITION_WORDS = frozenset({"NOT", "IS", "ARE", "THAN", "EQUAL", "GREATER", "LESS", "AND", "OR"})


def split_operands(text: str) -> list[str]:
    """Split on whitespace and commas outside quotes and parentheses (a subscript list stays inside its operand)."""
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    quote = ""
    for char in text:
        if quote:
            current.append(char)
            if char == quote:
                quote = ""
        elif char in "'\"":
            quote = char
            current.append(char)
        elif char == "(":
            depth += 1
            current.append(char)
        elif char == ")":
            depth = max(0, depth - 1)
            current.append(char)
        elif (char.isspace() or char == ",") and depth == 0:
            if current:
                parts.append("".join(current))
                current = []
        else:
            current.append(char)
    if current:
        parts.append("".join(current))
    return parts


@dataclass(frozen=True)
class Operand:
    kind: str                       # literal | figurative | name | intrinsic | unparsed
    name: str = ""
    qualifiers: tuple[str, ...] = ()
    subscripts: tuple[str, ...] = ()    # raw subscript operand texts
    refmod: bool = False
    arguments: tuple[str, ...] = ()     # raw argument texts of an intrinsic


def parse_operand(raw: str) -> Operand:
    text = raw.strip().rstrip(".")
    if not text:
        return Operand("unparsed")
    if text[0] in "'\"" or (len(text) > 1 and text[0].upper() in "XNZGB" and text[1] in "'\""):
        return Operand("literal")
    if _NUMBER.match(text):
        return Operand("literal")
    upper = text.upper()
    if upper in _FIGURATIVE or upper.startswith("ALL "):
        return Operand("figurative")
    if upper in _CONDITION_WORDS:
        return Operand("keyword")
    if upper.startswith("FUNCTION "):
        inner = text[len("FUNCTION "):]
        opened = inner.find("(")
        if opened < 0:
            return Operand("intrinsic")
        args = inner[opened + 1:inner.rfind(")")] if ")" in inner else inner[opened + 1:]
        return Operand("intrinsic", arguments=tuple(split_operands(args)))
    found = _NAME.match(text)
    if found is None:
        return Operand("unparsed")
    name = found.group(1).upper()
    qualifiers = tuple(q.group(1).upper() for q in _QUALIFIER.finditer(found.group(2) or ""))
    inner = found.group(3)
    subscripts: tuple[str, ...] = ()
    refmod = False
    if inner is not None:
        refmod = ":" in _mask(inner)
        pieces = inner.split(":") if refmod else [inner]
        tokens = [t for piece in pieces for t in split_operands(piece) if t not in _ARITHMETIC]
        subscripts = tuple(tokens)
    return Operand("name", name, qualifiers, subscripts, refmod)


def _mask(text: str) -> str:
    out: list[str] = []
    quote = ""
    for char in text:
        if quote:
            out.append(" ")
            quote = "" if char == quote else quote
        elif char in "'\"":
            quote = char
            out.append(" ")
        else:
            out.append(char)
    return "".join(out)


# ----- classification table -----------------------------------------------------------------------------------

@dataclass(frozen=True)
class Use:
    raw: str
    access: str
    role: str
    kind: str = "data"      # data | paragraph | file | host-var


def _each(raws: Iterable[str], access: str, role: str, kind: str = "data") -> list[Use]:
    """One use per operand: an IR field may hold several (``ADD A B TO C`` stores the sources as ``"A B"``)."""
    return [Use(operand, access, role, kind) for raw in raws if raw for operand in _operands(raw)]


def _operands(text: str) -> list[str]:
    """Operands of ``text`` with each ``name OF group`` chain kept together."""
    merged: list[str] = []
    for token in split_operands(text) if text else []:
        if merged and (merged[-1].upper() in ("OF", "IN") or token.upper() in ("OF", "IN")):
            merged[-1] = f"{merged[-1]} {token}"
        else:
            merged.append(token)
    return merged


def _expression_names(expression: Any) -> list[str]:
    """Raw operand texts of the names inside an IR expression tree, left to right."""
    kind = type(expression).__name__
    if kind == "FieldReference":
        return [expression.name]
    if kind == "IntrinsicCall":
        return [f"FUNCTION {expression.name}({expression.arguments})"
                if expression.arguments and "(" not in expression.arguments else expression.arguments]
    if kind in ("BinaryExpression", "Comparison", "LogicalCondition"):
        return _expression_names(expression.left) + _expression_names(expression.right)
    if kind == "UnaryExpression":
        return _expression_names(expression.operand)
    if kind == "NegatedCondition":
        return _expression_names(expression.condition)
    if kind == "BooleanCondition":
        return [expression.field.name] + ([expression.condition_name] if expression.condition_name else [])
    return []


def _condition(stmt: Any, role: str = "condition") -> list[Use]:
    cond = getattr(stmt, "structured_condition", None)
    return [] if cond is None else _each(_expression_names(cond), "read", role)


def _expr_or_raw(expr: Any, raw: str, access: str, role: str) -> list[Use]:
    if expr is not None:
        return _each(_expression_names(expr), access, role)
    return _each(_operands(raw), access, role)


def _move(s: Any) -> list[Use]:
    return (_expr_or_raw(s.source_expr, s.source, "read", "source")
            + _each(s.targets or (s.target,), "write", "target"))


def _add(s: Any) -> list[Use]:
    out = _expr_or_raw(s.source_expr, s.source, "read", "source")
    if s.giving_target:
        return out + _each(_operands(s.target), "read", "operand") + _each(_operands(s.giving_target), "write", "giving")
    return out + _each(_operands(s.target), "modify", "target")


def _subtract(s: Any) -> list[Use]:
    sources = s.sources or tuple(_operands(s.source))
    out = _each(sources, "read", "source")
    if s.to_field:
        return out + _each(_operands(s.from_field), "read", "minuend") + _each(_operands(s.to_field), "write", "giving")
    return out + _each(_operands(s.from_field), "modify", "target")


def _multiply(s: Any) -> list[Use]:
    out = _expr_or_raw(s.source_expr, s.source, "read", "source")
    if s.target:
        return out + _each(_operands(s.multiplicand), "read", "operand") + _each(_operands(s.target), "write", "giving")
    return out + _each(_operands(s.multiplicand), "modify", "target")


def _divide(s: Any) -> list[Use]:
    # ``DIVIDE a INTO b`` is stored with target == dividend (b is read and written); with GIVING the target is only
    # written.  ``modify`` where target == source is the same effect as read+write, so the two forms need no guess.
    access = "modify" if s.target == s.source else "write"
    return (_each(_operands(s.source), "read", "dividend") + _each(_operands(s.divisor), "read", "divisor")
            + _each(_operands(s.target), access, "target") + _each(_operands(s.remainder), "write", "remainder"))


def _compute(s: Any) -> list[Use]:
    return _each(_operands(s.target), "write", "target") + _expr_or_raw(s.expression_expr, s.expression, "read", "expression")


def _call(s: Any) -> list[Use]:
    out: list[Use] = []
    if s.is_dynamic:
        out += _each(_operands(s.program_name), "read", "program")
    modes = list(s.passing_modes) + ["REFERENCE"] * (len(s.arguments) - len(s.passing_modes))
    for raw, mode in zip(s.arguments, modes):
        out += [Use(raw, "modify" if mode.upper() == "REFERENCE" else "read", f"argument:{mode.upper()}")]
    return out + _each(_operands(s.returning), "write", "returning")


def _read(s: Any) -> list[Use]:
    return ([Use(s.file_name, "read", "file", "file")] + _each(_operands(s.key), "read", "key")
            + _each(_operands(s.into_field), "write", "into") + _each(_operands(s.record_name), "write", "record"))


def _write_like(s: Any) -> list[Use]:
    # ``WRITE rec FROM x`` fills the record from x (record written, x read); ``WRITE rec`` alone only reads it
    record_access = "write" if s.from_field else "read"
    return ([Use(s.file_name, "write", "file", "file")] + _each(_operands(s.record_name), record_access, "record")
            + _each(_operands(s.from_field), "read", "from"))


def _perform(s: Any) -> list[Use]:
    out = _each([s.paragraph_name], "perform", "paragraph", "paragraph") if s.paragraph_name else []
    if s.thru_target:
        out += _each([s.thru_target], "perform", "thru", "paragraph")
    return out + _varying(s.until_condition or "") + _condition(s, "until")


def _varying(text: str) -> list[Use]:
    """``VARYING idx FROM a BY b`` of an unstructured PERFORM: the index is modified, ``a`` and ``b`` are read.  The
    UNTIL part stays unsupported (``CONDITION_UNSTRUCTURED``): no condition is scraped from text."""
    tokens = split_operands(text)
    upper = [t.upper() for t in tokens]
    if not upper or upper[0] != "VARYING":
        return []
    uses: list[Use] = []
    for keyword, access, role in (("VARYING", "modify", "varying"), ("FROM", "read", "from"), ("BY", "read", "by")):
        if keyword in upper and upper.index(keyword) + 1 < len(tokens):
            uses.append(Use(tokens[upper.index(keyword) + 1], access, role))
    return uses


def _string(s: Any) -> list[Use]:
    delimiters = [e for e in s.delimiter_exprs if e is not None]
    out = _each(s.parts, "read", "source") + _each(_operands(s.target), "write", "target")
    for expr in delimiters:
        out += _each(_expression_names(expr), "read", "delimiter")
    return out + _each(_operands(s.pointer or s.varying_pointer), "modify", "pointer")


def _unstring(s: Any) -> list[Use]:
    return (_each(_operands(s.source), "read", "source") + _each(_operands(s.delimiter), "read", "delimiter")
            + _each(s.targets, "write", "target")
            + _each(_operands(s.pointer or s.varying_pointer), "modify", "pointer")
            + _each(_operands(s.tallying_pointer), "modify", "tallying"))


def _display(s: Any) -> list[Use]:
    return _each(s.parts, "read", "part")


def _initialize(s: Any) -> list[Use]:
    out = _each(s.targets, "write", "target")
    tokens = split_operands(s.replacing)
    for index, token in enumerate(tokens):
        if token.upper() == "BY" and index + 1 < len(tokens):
            out += _each([tokens[index + 1]], "read", "replacing")
    return out


def _inspect(s: Any) -> list[Use]:
    return (_each(_operands(s.target), "modify" if s.mode != "TALLYING" else "read", "target")
            + _each(_operands(s.counter), "modify", "counter"))


def _exec_sql(s: Any) -> list[Use]:
    host = lambda names: [n.lstrip(":") for n in names]  # noqa: E731
    return (_each(host(s.inputs), "read", "input", "host-var") + _each(host(s.outputs), "write", "output", "host-var")
            + _each(host(s.indicators), "write", "indicator", "host-var"))


def _sort(s: Any) -> list[Use]:
    out = [Use(s.sort_file, "read", "sort-file", "file")] if s.sort_file else []
    out += _each([key[0] for key in s.keys if key], "read", "key")
    return out + [Use(f, "read", "using", "file") for f in s.using] + [Use(f, "write", "giving", "file") for f in s.giving]


def _set_index(s: Any) -> list[Use]:
    access = "write" if s.mode.upper() == "TO" else "modify"
    return _each(s.targets, access, "target") + _each(_operands(s.value), "read", "value")


def _search(s: Any) -> list[Use]:
    return (_each(_operands(s.table), "read", "table") + _each(_operands(s.varying), "modify", "varying"))


def _none(_s: Any) -> list[Use]:
    return []


#: One row per statement class of the IR ``Statement`` union, plus the two non-statement dataclasses the walker also
#: reaches (``SearchWhen``, ``InspectPhrase``).  ``tests/semantic_facts/test_references_p3.py`` enumerates the union.
STATEMENT_RULES: dict[str, Callable[[Any], list[Use]]] = {
    "OpenStatement": lambda s: [Use(s.file_name, "open", "file", "file")],
    "CloseStatement": lambda s: [Use(s.file_name, "close", "file", "file")],
    "ReadStatement": _read,
    "StartStatement": lambda s: [Use(s.file_name, "read", "file", "file")] + _each(_operands(s.key), "read", "key"),
    "WriteStatement": _write_like,
    "RewriteStatement": _write_like,
    "DeleteStatement": lambda s: [Use(s.file_name, "write", "file", "file")],
    "MoveStatement": _move,
    "AddStatement": _add,
    "SubtractStatement": _subtract,
    "MultiplyStatement": _multiply,
    "ComputeStatement": _compute,
    "CallStatement": _call,
    "DivideStatement": _divide,
    "IfStatement": _condition,
    "PerformStatement": _perform,
    "UnstringStatement": _unstring,
    "StringStatement": _string,
    "DisplayStatement": _display,
    "SetConditionStatement": lambda s: _each(_operands(s.target), "write", "condition"),
    "GoToStatement": lambda s: _each([s.target], "goto", "paragraph", "paragraph"),
    "StopRunStatement": _none,
    "ExitProgramStatement": _none,
    "GobackStatement": _none,
    "InitializeStatement": _initialize,
    "AcceptStatement": lambda s: _each(_operands(s.target), "write", "target"),
    "InspectStatement": _inspect,
    "ExecSqlStatement": _exec_sql,
    "SortStatement": _sort,
    "SetIndexStatement": _set_index,
    "SearchStatement": _search,
    "ExitPerformStatement": _none,
    "SearchWhen": _condition,
    "InspectPhrase": _none,
    # expression nodes the walker also reaches inside a statement's tuples; the owning statement's row reads them
    "FieldReference": _none, "Literal": _none, "FigurativeConstant": _none, "IntrinsicCall": _none,
    "UnaryExpression": _none, "BinaryExpression": _none,
}


# ----- resolution ---------------------------------------------------------------------------------------------

class Resolver:
    """Resolve names against one program's :class:`SymbolTable` (the one declaration authority)."""

    def __init__(self, table: SymbolTable) -> None:
        self.by_ir: dict[str, list[Declaration]] = {}
        self.by_source: dict[str, list[Declaration]] = {}
        self.paragraphs: dict[str, list[Declaration]] = {}
        self.files: dict[str, list[Declaration]] = {}
        for decl in table.declarations:
            if not decl.addressable:
                continue
            if decl.kind in _DATA_DECLS:
                ir_name = dict(decl.attributes).get("generated_name", decl.name)
                self.by_ir.setdefault(ir_name, []).append(decl)
                self.by_source.setdefault(decl.name, []).append(decl)
            elif decl.kind == "paragraph":
                self.paragraphs.setdefault(decl.name, []).append(decl)
            elif decl.kind == "file":
                self.files.setdefault(decl.name, []).append(decl)

    @staticmethod
    def _pick(found: list[Declaration], rule: str, confidence: str = "certain") -> Resolution:
        ids = tuple(sorted(d.decl_id for d in found))
        if len(ids) == 1:
            return Resolution("resolved", ids, confidence=confidence, rule=rule)
        return Resolution("ambiguous", ids, confidence="heuristic", rule=rule)

    def data(self, name: str, qualifiers: tuple[str, ...]) -> tuple[Resolution, Declaration | None]:
        name = name.upper()
        found: list[Declaration] = []
        if qualifiers:
            found = [d for d in self.by_source.get(name, []) if _has_chain(d.qualification, qualifiers)]
            if not found:
                return Resolution("unresolved", reason="missing-data-item", confidence="unresolved",
                                  rule="l5.data-name-qualified"), None
            resolution = self._pick(found, "l5.data-name-qualified", "derived")
        else:
            found = self.by_ir.get(name, [])
            if found:
                generated = "generated_name" in dict(found[0].attributes)
                resolution = self._pick(found, "l5.data-name-generated" if generated else "l5.data-name",
                                        "derived" if generated else "certain")
            else:
                found = self.by_source.get(name, [])
                if len(found) > 1:
                    resolution = Resolution("ambiguous", tuple(sorted(d.decl_id for d in found)),
                                            confidence="heuristic", rule="l5.data-name")
                else:
                    return Resolution("unresolved", reason="missing-data-item", confidence="unresolved",
                                      rule="l5.data-name"), None
        if resolution.state == "resolved":
            decl = next(d for d in found if d.decl_id == resolution.candidates[0])
            if decl.kind == "special-register":
                resolution = Resolution("resolved", resolution.candidates, rule="l5.special-register")
            return resolution, decl
        return resolution, None

    def paragraph(self, name: str) -> Resolution:
        found = self.paragraphs.get(name.upper(), [])
        if not found:
            return Resolution("unresolved", reason="missing-paragraph", confidence="unresolved",
                              rule="l5.paragraph-name")
        return self._pick(found, "l5.paragraph-name")

    def file(self, name: str) -> Resolution:
        found = self.files.get(name.upper(), [])
        if not found:
            return Resolution("unresolved", reason="missing-logical-file", confidence="unresolved",
                              rule="l5.file-name")
        return self._pick(found, "l5.file-name")


def _has_chain(ancestors: tuple[str, ...], qualifiers: tuple[str, ...]) -> bool:
    """``qualifiers`` appear in ``ancestors`` in order (not necessarily adjacent): the OF/IN rule ``qualified_names`` uses."""
    position = 0
    for qualifier in qualifiers:
        try:
            position = ancestors.index(qualifier, position) + 1
        except ValueError:
            return False
    return True


# ----- walk ---------------------------------------------------------------------------------------------------

def _walk_paths(statements: Iterable[Any], prefix: str = "") -> Iterator[tuple[Any, str]]:
    """``(statement, path)`` depth first in the order the P1 span walk yields; children of one parent are numbered
    consecutively across all its nested bodies (``3``, ``3.1``, ``3.2`` ...), so a path is deterministic from the IR."""
    for index, statement in enumerate(statements, 1):
        yield from _single(statement, f"{prefix}{index}")


def _single(statement: Any, path: str) -> Iterator[tuple[Any, str]]:
    yield statement, path
    counter = 0
    for value in getattr(statement, "__dict__", {}).values():
        if isinstance(value, (tuple, list)):
            for child in [v for v in value if hasattr(v, "__dataclass_fields__")]:
                counter += 1
                yield from _single(child, f"{path}.{counter}")


def _token_span(source_lines: tuple[str, ...] | None, statement_span: Span | None, token: str,
                *, inline: bool) -> Span | None:
    """Exact span of ``token`` re-read from the *physical* line the statement starts on: claimed only when the token
    occurs exactly once on that line from the statement's column on, outside quotes, and the statement's own column is
    exact.  Without the source text, in a COPY expansion, for an inline fragment or for a token on a continuation line
    there is no claim (``None``): the caller keeps the statement's line, marked inexact."""
    if (source_lines is None or statement_span is None or not statement_span.exact or inline
            or statement_span.via_copy or not 1 <= statement_span.line <= len(source_lines)):
        return None
    physical = source_lines[statement_span.line - 1]
    start = statement_span.column - 1
    text = _mask(physical)
    pattern = re.compile(r"(?<![\w-])" + re.escape(token.upper()) + r"(?![\w-])", re.IGNORECASE)
    hits = [m.start() for m in pattern.finditer(text, max(start, 0))]
    if len(hits) != 1 or text[hits[0]:hits[0] + len(token)].upper() != token.upper():
        return None
    column = hits[0] + 1
    return Span(statement_span.file, statement_span.line, column, end_line=statement_span.line,
                end_column=column + len(token), basis="token", exact=True)


def _single_line(trace: ParseTrace, logical: int, boundaries: set[int]) -> bool:
    """True when logical line ``logical`` is the whole statement: the next logical line starts another statement or
    paragraph (or is an ``END-xxx`` / ``ELSE`` terminator), or there is none."""
    following = logical + 1
    if following >= len(trace.code) or following in boundaries:
        return True
    head = trace.code[following].split(None, 1)[0].upper().rstrip(".") if trace.code[following].strip() else ""
    return head.startswith("END-") or head == "ELSE"


def build_reference_table(program: Any, trace: ParseTrace, spans: SpanTable, symbols: SymbolTable, *,
                          source: str | None = None) -> ReferenceTable:
    """Every reference of ``program``'s statements with its access, resolution and span (or named unsupported use).

    ``source`` is the text handed to ``parse`` (the file itself): with it, an operand token is located on the
    statement's physical line and claimed exact when that is provable (see :func:`_token_span`)."""
    lines = tuple(source.replace("\r\n", "\n").split("\n")) if source is not None else None
    resolver = Resolver(symbols)
    scope = symbols.scopes[0].scope_id
    frames = trace.statement_index()
    boundaries = {f.start for f in trace.statements} | {i for _name, i in trace.paragraphs}
    by_object = {id(s.statement): s for s in spans.statements}
    statements: list[StatementRow] = []
    references: list[Reference] = []
    unsupported: list[UnsupportedUse] = []

    for paragraph in program.paragraphs:
        for statement, path in _walk_paths(paragraph.statements):
            spanned = by_object.get(id(statement))
            span = spanned.span if spanned is not None else None
            cls = type(statement).__name__
            stmt_id = f"stmt:{scope}/{paragraph.name.upper()}/{path}"
            statements.append(StatementRow(stmt_id, cls, paragraph.name.upper(), span))
            rule = STATEMENT_RULES.get(cls)
            if rule is None:
                unsupported.append(UnsupportedUse(stmt_id, "OPERAND_UNPARSED", f"no classification for {cls}", span))
                continue
            frame = frames.get(id(statement))
            inline = frame.inline if frame is not None else True
            if frame is not None and not _single_line(trace, frame.start, boundaries):
                inline = True       # a statement that continues past its first line: tokens there are not claimed
            _statement_refs(statement, cls, rule, stmt_id, span, inline, lines, resolver, symbols,
                            references, unsupported)
    return ReferenceTable(tuple(statements), tuple(references), tuple(unsupported))


def _statement_refs(statement: Any, cls: str, rule: Callable[[Any], list[Use]], stmt_id: str, span: Span | None,
                    inline: bool, lines: tuple[str, ...] | None, resolver: Resolver, symbols: SymbolTable,
                    references: list[Reference], unsupported: list[UnsupportedUse]) -> None:
    reasons = getattr(statement, "reasons", ())
    if reasons:
        unsupported.append(UnsupportedUse(stmt_id, "STATEMENT_PARTLY_PARSED", ",".join(map(str, reasons)), span))
    if cls in ("IfStatement", "SearchWhen") and getattr(statement, "structured_condition", None) is None:
        if getattr(statement, "condition", ""):
            unsupported.append(UnsupportedUse(stmt_id, "CONDITION_UNSTRUCTURED", statement.condition, span))
    if cls == "PerformStatement" and statement.until_condition and statement.structured_condition is None:
        unsupported.append(UnsupportedUse(stmt_id, "CONDITION_UNSTRUCTURED", statement.until_condition, span))
    if cls == "InspectPhrase" or cls == "InspectStatement":
        for phrase in ([statement] if cls == "InspectPhrase" else statement.phrases):
            for text in (phrase.pattern, phrase.replacement, phrase.after, phrase.before):
                if text and (text.upper() in resolver.by_ir or text.upper() in resolver.by_source):
                    unsupported.append(UnsupportedUse(stmt_id, "INSPECT_OPERAND_KIND_UNKNOWN", text, span))
    ordinal = 0
    for use in rule(statement):
        ordinal = _emit(use, use.raw, stmt_id, span, inline, lines, resolver, references, unsupported,
                        ordinal)


def _emit(use: Use, text: str, stmt_id: str, span: Span | None, inline: bool, lines: tuple[str, ...] | None,
          resolver: Resolver, references: list[Reference], unsupported: list[UnsupportedUse], ordinal: int) -> int:
    if use.kind == "paragraph":
        if len(split_operands(text)) != 1:
            unsupported.append(UnsupportedUse(stmt_id, "GOTO_TARGET_UNPARSED", text, span))
            return ordinal
        ordinal += 1
        name = text.strip().upper().rstrip(".")
        references.append(Reference(f"ref:{stmt_id}#{ordinal}", "paragraph", use.access, stmt_id, name, (),
                                    resolver.paragraph(name), _located(lines, span, name, inline), use.role))
        return ordinal
    if use.kind == "file":
        ordinal += 1
        name = text.strip().upper()
        references.append(Reference(f"ref:{stmt_id}#{ordinal}", "file", use.access, stmt_id, name, (),
                                    resolver.file(name), _located(lines, span, name, inline), use.role))
        return ordinal
    operand = parse_operand(text)
    if operand.kind in ("literal", "figurative", "keyword"):
        return ordinal
    if operand.kind == "unparsed":
        unsupported.append(UnsupportedUse(stmt_id, "OPERAND_UNPARSED", text, span))
        return ordinal
    if operand.kind == "intrinsic":
        for argument in operand.arguments:
            ordinal = _emit(Use(argument, "read", use.role, "data"), argument, stmt_id, span, inline, lines,
                            resolver, references, unsupported, ordinal)
        return ordinal
    resolution, decl = resolver.data(operand.name, operand.qualifiers)
    kind = use.kind if use.kind == "host-var" else (
        "condition" if decl is not None and decl.kind == "condition-name" else
        "index" if decl is not None and decl.kind == "index-name" else "data")
    ordinal += 1
    base_id = f"ref:{stmt_id}#{ordinal}"
    subscript_refs: list[Reference] = []
    for subscript in operand.subscripts:
        ordinal = _emit(Use(subscript, "read", "subscript", "data"), subscript, stmt_id, span, inline, lines,
                        resolver, subscript_refs, unsupported, ordinal)
    references.append(Reference(
        base_id, kind, use.access, stmt_id, operand.name, operand.qualifiers, resolution,
        _located(lines, span, decl.name if decl is not None else operand.name, inline), use.role,
        tuple(r.ref_id for r in subscript_refs), operand.refmod))
    references.extend(subscript_refs)
    return ordinal


def _located(lines: tuple[str, ...] | None, span: Span | None, token: str, inline: bool) -> Span | None:
    """The token's exact span when provable, else the statement's own span as a ``statement``-basis inexact one."""
    exact = _token_span(lines, span, token, inline=inline)
    if exact is not None:
        return exact
    if span is None:
        return None
    return Span(span.file, span.line, 0, via_copy=span.via_copy, basis="statement", exact=False,
                note="SPAN_OPERAND_NOT_LOCATED")
