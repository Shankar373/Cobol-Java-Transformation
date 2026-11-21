"""COBOL program and copybook scanner (no parsing, no execution, no LLM).

Finds, with exact source positions: program ids and nesting, ``COPY``/``-INC``/``++INCLUDE`` members (including the
``REPLACING`` pairs, recorded not expanded), static and dynamic ``CALL``, ``SELECT``/``ASSIGN`` file bindings
(including VSAM-capable organisations), sections, paragraphs and data descriptions, ``PERFORM``/``GO TO`` control
flow, ``READ``/``WRITE``/``REWRITE`` file verbs and ``MOVE``-level data flow, ``SORT``/``MERGE``, embedded
``EXEC SQL|CICS|DLI`` blocks, IMS and MQ interface calls, environment access, compiler-option cards and the
signals that indicate a COBOL dialect.  Dynamic ``CALL`` targets are followed through ``VALUE`` clauses and
``MOVE literal TO`` so a program that always calls the same module is still tied to it, flagged as dynamic.
"""

from __future__ import annotations

import re

from . import cobol_structure, copy_replacing
from .cobol_text import Token, read_source, split_indexed, split_statements, tokenize
from .findings import Fact, FileScan, Ref, ScanProblem, detail
from .scan_embedded import classify_call, parse_exec

__all__ = ["scan_cobol", "DIALECT_SIGNALS"]

_CARD = re.compile(r"^\s*(CBL|PROCESS)\s+(.*)$", re.IGNORECASE)
_INCLUDE_LINE = re.compile(r"^\s*(?:-INC|\+\+INCLUDE|%INCLUDE)\s+([A-Za-z0-9@#$_-]+)", re.IGNORECASE)
_DDNAME_PREFIX = re.compile(r"^(?:UT|DA|DC|AS|SYS\d{3})-[A-Z]-", re.IGNORECASE)
_VERBS = frozenset({
    "MOVE", "IF", "PERFORM", "DISPLAY", "ADD", "COMPUTE", "CALL", "GO", "STOP", "EVALUATE", "READ", "WRITE", "OPEN",
    "CLOSE", "EXIT", "GOBACK", "SET", "STRING", "UNSTRING", "INITIALIZE", "ACCEPT", "END-CALL", "ELSE", "END-IF",
    "WHEN", "NOT", "ON", "RETURNING", "EXEC", "COPY", "INSPECT", "SORT", "MERGE", "SEARCH", "SUBTRACT", "MULTIPLY",
    "DIVIDE", "CONTINUE", "RETURN", "REWRITE", "DELETE", "START", "RELEASE", "CANCEL", "ENTRY", "USE", "ALTER",
    "END-PERFORM", "END-EVALUATE", "END-READ", "END-WRITE", "EXCEPTION", "OVERFLOW", "INVALID", "AT", "END",
})
_COPY_OPTIONS = frozenset({"SUPPRESS", "REPLACING", "OF", "IN"})

#: ``(signal, dialect hint)`` for single reserved words or word pairs; matched case-insensitively on tokens.
DIALECT_SIGNALS: tuple[tuple[str, str], ...] = (
    ("COMP-5", "extension"), ("COMP-X", "microfocus"), ("COMP-N", "microfocus"), ("PROCEDURE-POINTER", "ibm"),
    ("SCREEN", "gnucobol-or-microfocus"), ("ARGUMENT-NUMBER", "gnucobol"), ("ARGUMENT-VALUE", "gnucobol"),
    ("ENVIRONMENT-NAME", "gnucobol-or-microfocus"), ("ENVIRONMENT-VALUE", "gnucobol-or-microfocus"),
    ("JSON", "ibm"), ("XML", "ibm"), ("CLASS-ID", "object-oriented"), ("ILUSING", "microfocus"),
    ("DAY-OF-WEEK", "ibm-or-ansi"), ("GOBACK", "ibm-or-extension"), ("ALTER", "legacy-cobol74"),
    ("REPLACE", "ansi85"), ("FUNCTION", "cobol85-intrinsic"), ("NATIONAL", "ibm"), ("DBCS", "ibm"),
)

#: Data-description level numbers (written bare or zero-padded): a word preceded by one on the same
#: line is the data-name being declared, not a use of the construct the signal word names.
_LEVEL_NUMBERS = frozenset(
    [str(n) for n in range(1, 50)] + [f"{n:02d}" for n in range(1, 50)] + ["66", "77", "88"]
)


def _raw_cards(text: str) -> list[tuple[int, int, str]]:
    """Compiler-option cards (``CBL``/``PROCESS``) before the first IDENTIFICATION DIVISION: ``(line, col, options)``."""
    found = []
    for number, raw in enumerate(text.splitlines(), start=1):
        upper = raw.upper()
        if "IDENTIFICATION DIVISION" in upper or re.match(r"^\s*(?:\d{6}\s*)?ID\s+DIVISION", upper):
            break
        match = _CARD.match(raw)
        if match:
            found.append((number, match.start(1) + 1, match.group(2).strip()))
    return found


def _split_options(options: str) -> list[str]:
    return [item for item in re.split(r"[,\s]+", re.sub(r"\(([^)]*)\)", lambda m: "(" + m.group(1).replace(",", ";") + ")",
                                                        options)) if item]


class _State:
    def __init__(self, path: str, scan: FileScan) -> None:
        self.path = path
        self.scan = scan
        self.programs: list[str] = []
        self.finished: list[str] = []
        #: variable -> {literal: ("value" | "move", line, column)} used to follow dynamic targets.
        self.values: dict[str, dict[str, tuple[str, int, int]]] = {}
        #: Dynamic references ``(token, relation, kind, variable, clause, detail, mode)`` resolved once all values
        #: are known.
        self.deferred: list[tuple[Token, str, str, str, str, tuple[tuple[str, str], ...], str]] = []
        #: The structural pass (sections, paragraphs, data descriptions, control flow) run over the same tokens.
        self.structure: cobol_structure.StructureScan | None = None

    @property
    def owner(self) -> str:
        return f"program:{self.programs[-1]}" if self.programs else f"file:{self.path}"

    def fact(self, token: Token, category: str, name: str, **info: object) -> None:
        self.scan.facts.append(Fact(self.path, token.line, token.column, category, name, self.owner, detail(**info)))

    def ref(self, token: Token, relation: str, kind: str, target: str, **kw: object) -> None:
        self.scan.refs.append(Ref(self.path, token.line, token.column, relation, kind, target, self.owner, **kw))  # type: ignore[arg-type]


def scan_cobol(path: str, text: str, *, copybook: bool = False) -> FileScan:
    """Scan one COBOL source or copybook; ``path`` is the relative POSIX path recorded on every finding."""
    scan = FileScan(path=path, line_count=text.count("\n") + (0 if text.endswith("\n") or not text else 1))
    read = read_source(text)
    fmt, lines, directives, switches = read.format, read.lines, read.directives, read.switches
    scan.source_format = "variable" if fmt == "variable" else ("mixed" if switches else fmt)
    scan.format_switches = tuple(switches)
    scan.conditional = read.conditional
    if read.conditional == "unevaluated":
        scan.problems.append(ScanProblem(path, read.conditional_line, "CONDITIONAL_COMPILATION_UNEVALUATED",
                                         "conditional compilation directive outside the evaluated "
                                         ">>DEFINE/>>IF subset: both branches kept, refused by name"))
    if fmt == "variable":
        variable_line = next((line for line, new in switches if new == "variable"), 1)
        scan.problems.append(ScanProblem(path, variable_line, "REFERENCE_FORMAT_VARIABLE_UNSUPPORTED",
                                         "$SET SOURCEFORMAT VARIABLE is not supported: refused by name, "
                                         "never read as fixed"))
    tokens = tokenize(lines)
    state = _State(path, scan)
    for directive in directives:
        scan.facts.append(Fact(path, directive.line, 1, "directive", directive.text.upper()[:80]))
    # A dead conditional branch is never compiled: its cards and include cards are never processed.
    dead = frozenset(number for number, kind in read.skipped if kind == "dead-branch")
    for number, column, options in _raw_cards(text):
        if number in dead:
            continue
        marker = Token("word", "CBL", number, column)
        for option in _split_options(options):
            state.fact(marker, "compiler-option", option.upper(), card=options[:80])
    for number, raw in enumerate(text.splitlines(), start=1):
        if number in dead:
            continue
        match = _INCLUDE_LINE.match(raw)
        if match:
            marker = Token("word", match.group(1), number, match.start(1) + 1)
            state.ref(marker, "copies", "copybook", match.group(1).upper(), clause="-INC/++INCLUDE")
    _collect_values(tokens, state)
    state.structure = cobol_structure.scan_structure(tokens, path=path, copybook=copybook)
    _scan_flat(tokens, state)
    _structure_refs(state)
    _finish(tokens, state, copybook)
    for problem_line in _open_literal_lines(lines):
        scan.problems.append(ScanProblem(path, problem_line, "UNTERMINATED_LITERAL",
                                         "an alphanumeric literal is not closed before the end of its line"))
    return scan.sorted()


def _structure_refs(state: _State) -> None:
    """Turn the structural pass into findings: declarations become ``contains`` references, control flow and data
    flow become their own relations.  Every reference keeps its exact ``(line, column)`` from the token stream."""
    structure = state.structure
    if structure is None:
        return
    for line, code, message in structure.problems:
        state.scan.problems.append(ScanProblem(state.path, line, code, message))
    for unit in structure.units:
        owner = f"program:{unit.program}" if unit.program else f"file:{state.path}"
        kind = "section" if unit.kind == "section" else "paragraph"
        state.scan.refs.append(Ref(state.path, unit.line, unit.column, "contains", kind, unit.name.upper(), owner,
                                   clause=f"{unit.kind.upper()} HEADER"))
    for decl in structure.data:
        state.scan.refs.append(Ref(state.path, decl.line, decl.column, "contains", decl.kind, decl.name.upper(),
                                   decl.owner, clause="DATA DESCRIPTION",
                                   detail=detail(level=decl.level, record=decl.record, file=decl.file)))
    for flow in structure.refs:
        owner = f"program:{flow.program}" if flow.program else f"file:{state.path}"
        state.scan.refs.append(Ref(state.path, flow.line, flow.column, flow.relation, flow.target_kind,
                                   flow.target.upper(), owner, clause=flow.clause, mode=flow.mode,
                                   dynamic=flow.dynamic, variable=flow.variable,
                                   detail=tuple(sorted(flow.detail))))


def _collect_values(tokens: list[Token], state: _State) -> None:
    """Gather ``name -> literals`` from data-item ``VALUE`` clauses and ``MOVE literal TO name`` statements."""
    for sentence in split_statements(tokens):
        head = sentence[0]
        if head.text.isdigit() and len(sentence) > 2 and sentence[1].kind == "word":
            name = sentence[1].upper
            for index, token in enumerate(sentence):
                if token.kind == "word" and token.upper in ("VALUE", "VALUES"):
                    for item in sentence[index + 1:index + 4]:
                        if item.kind == "literal":
                            state.values.setdefault(name, {}).setdefault(item.text, ("value", item.line, item.column))
                            break
                        if item.upper not in ("IS", "ARE"):
                            break
                    break
    for index, token in enumerate(tokens):
        if token.kind == "word" and token.upper == "MOVE" and index + 1 < len(tokens)                 and tokens[index + 1].kind == "literal":
            literal = tokens[index + 1]
            cursor = index + 2
            if cursor < len(tokens) and tokens[cursor].upper == "TO":
                cursor += 1
                while cursor < len(tokens) and tokens[cursor].kind == "word" and tokens[cursor].upper not in _VERBS:
                    state.values.setdefault(tokens[cursor].upper, {}).setdefault(
                        literal.text, ("move", literal.line, literal.column))
                    cursor += 1
                    if cursor < len(tokens) and tokens[cursor].text == ",":
                        cursor += 1


def _scan_sentence(sentence: list[Token], state: _State) -> None:
    head = sentence[0]
    word = head.upper if head.kind == "word" else ""
    if word == "SELECT":
        _scan_select(sentence, state)
    elif word in ("FD", "SD") and len(sentence) > 1:
        state.fact(sentence[1], "file-description", sentence[1].upper, kind=word)
    elif word == "CBL" or word == "PROCESS":
        return


def _scan_select(sentence: list[Token], state: _State) -> None:
    body = [t for t in sentence[1:] if not (t.kind == "word" and t.upper == "OPTIONAL")]
    if not body:
        return
    name = body[0]
    words = [t.upper if t.kind == "word" else "" for t in body]

    def after(*keys: str) -> Token | None:
        for index, value in enumerate(words):
            if value in keys:
                cursor = index + 1
                while cursor < len(body) and body[cursor].upper in ("TO", "IS", "ARE", "USING", "MODE", "EXTERNAL"):
                    cursor += 1
                return body[cursor] if cursor < len(body) else None
        return None

    assign = after("ASSIGN")
    organization = after("ORGANIZATION", "ORGANISATION")
    access = after("ACCESS")
    key = after("KEY") if "RECORD" in words else None
    status = after("STATUS")
    alternates = []
    for i, value in enumerate(words):
        if value == "ALTERNATE":
            cursor = i + 1
            while cursor < len(body) and words[cursor] in ("RECORD", "KEY", "IS"):
                cursor += 1
            if cursor < len(body):
                alternates.append(body[cursor].upper)
    org = organization.upper if organization else "SEQUENTIAL"
    if org == "LINE":
        org = "LINE SEQUENTIAL"
    ddname = ""
    assign_text = assign.text if assign else ""
    is_literal = bool(assign and assign.kind == "literal")
    if assign and not is_literal:
        ddname = _DDNAME_PREFIX.sub("", assign.text).upper()
    vsam = org in ("INDEXED", "RELATIVE")
    state.fact(name, "file-select", name.upper, assign=assign_text, ddname=ddname, organization=org,
               access=access.upper if access else "", record_key=key.upper if key else "",
               alternate_keys=",".join(alternates), file_status=status.upper if status else "",
               vsam_candidate="yes" if vsam else "no", literal_assign="yes" if is_literal else "no")
    if assign is None:
        return
    if is_literal:
        state.ref(assign, "assigns-file", "external-file", assign.text, clause="SELECT ASSIGN",
                  detail=detail(logical_file=name.upper, organization=org))
    else:
        state.ref(assign, "assigns-file", "dd", ddname, clause="SELECT ASSIGN",
                  detail=detail(logical_file=name.upper, organization=org, vsam_candidate="yes" if vsam else "no"))


def _scan_flat(tokens: list[Token], state: _State) -> None:
    index, count = 0, len(tokens)
    sentence_at = dict(split_indexed(tokens))
    while index < count:
        if index in sentence_at:
            _scan_sentence(sentence_at[index], state)
        token = tokens[index]
        word = token.upper if token.kind == "word" else ""
        advance = 1
        if word == "PROGRAM-ID":
            advance = _program_id(tokens, index, state)
        elif word == "END" and _next_is(tokens, index, "PROGRAM"):
            _end_program(tokens, index, state)
            advance = 2
        elif word in ("CLASS-ID", "INTERFACE-ID", "FUNCTION-ID"):
            name = _name_after(tokens, index + 1)
            if name is not None:
                state.fact(name, "program-id", name.text.upper(), kind=word, nested="no")
        elif word == "COPY":
            advance = _copy(tokens, index, state)
        elif word == "CALL" or word == "CANCEL":
            advance = _call(tokens, index, state, word)
        elif word == "ENTRY" and index + 1 < count and tokens[index + 1].kind == "literal":
            state.fact(tokens[index + 1], "entry-point", tokens[index + 1].text.upper())
            if tokens[index + 1].text.upper() == "DLITCBL":
                state.ref(tokens[index + 1], "uses-ims", "ims-interface", "DLITCBL", clause="ENTRY")
        elif word == "EXEC" and index + 1 < count:
            advance = _exec_block(tokens, index, state)
        elif word in ("SORT", "MERGE") and _starts_statement(tokens, index):
            state.fact(token, "sort-verb", word)
            state.ref(token, "runs-utility", "utility", "SORT", clause=word)
        elif word == "ACCEPT" or word == "DISPLAY":
            _environment(tokens, index, state)
        elif word == "ALTER" and _starts_statement(tokens, index):
            state.fact(token, "legacy-construct", "ALTER")
        _dialect(tokens, index, state)
        index += max(advance, 1)


def _dialect(tokens: list[Token], index: int, state: _State) -> None:
    token = tokens[index]
    if token.kind != "word":
        return
    upper = token.upper
    for signal, hint in DIALECT_SIGNALS:
        if upper == signal and (signal != "FUNCTION" or _next_kind(tokens, index) == "word"):
            # Criterion 7: a data item that happens to be named like a signal
            # (``05 JSON PIC X``) declares a data-name; it is not vendor evidence.
            if index and tokens[index - 1].line == token.line and tokens[index - 1].text in _LEVEL_NUMBERS:
                return
            state.fact(token, "dialect-signal", signal, hint=hint)
            return


def _next_kind(tokens: list[Token], index: int) -> str:
    return tokens[index + 1].kind if index + 1 < len(tokens) else ""


def _next_is(tokens: list[Token], index: int, word: str) -> bool:
    return index + 1 < len(tokens) and tokens[index + 1].kind == "word" and tokens[index + 1].upper == word


def _starts_statement(tokens: list[Token], index: int) -> bool:
    """True when the verb at ``index`` is not just a data name that happens to equal a verb."""
    if index == 0:
        return True
    previous = tokens[index - 1]
    return previous.line != tokens[index].line or previous.text in ".,;" or previous.upper in ("THEN", "ELSE", "WHEN")


def _name_after(tokens: list[Token], index: int) -> Token | None:
    if index < len(tokens) and tokens[index].text == ".":
        index += 1
    return tokens[index] if index < len(tokens) and tokens[index].kind in ("word", "literal") else None


def _program_id(tokens: list[Token], index: int, state: _State) -> int:
    name = _name_after(tokens, index + 1)
    if name is None:
        state.scan.problems.append(ScanProblem(state.path, tokens[index].line, "PROGRAM_ID_MISSING_NAME",
                                               "PROGRAM-ID has no program name"))
        return 1
    attrs: list[str] = []
    cursor = tokens.index(name) + 1
    while cursor < len(tokens) and tokens[cursor].text != "." and tokens[cursor].upper != "AUTHOR" and len(attrs) < 6:
        if tokens[cursor].kind == "word":
            attrs.append(tokens[cursor].upper)
        cursor += 1
    nested = bool(state.programs)
    upper = name.text.upper()
    state.programs.append(upper)
    state.fact(name, "program-id", upper, kind="PROGRAM-ID", nested="yes" if nested else "no",
               attributes=",".join(a for a in attrs if a in ("COMMON", "INITIAL", "RECURSIVE", "PROTOTYPE")),
               external_name=next((t.text for t in tokens[tokens.index(name):cursor] if t.kind == "literal"
                                   and t is not name), ""))
    return 1


def _end_program(tokens: list[Token], index: int, state: _State) -> None:
    name = _name_after(tokens, index + 2)
    ended = name.text.upper() if name else ""
    if state.programs and (not ended or state.programs[-1] == ended):
        state.finished.append(state.programs.pop())
    elif ended in state.programs:
        while state.programs and state.programs[-1] != ended:
            state.finished.append(state.programs.pop())
        state.finished.append(state.programs.pop())
    else:
        state.scan.problems.append(ScanProblem(state.path, tokens[index].line, "END_PROGRAM_MISMATCH",
                                               f"END PROGRAM {ended or '?'} closes no open program"))


def _copy(tokens: list[Token], index: int, state: _State) -> int:
    name = tokens[index + 1] if index + 1 < len(tokens) else None
    if name is None or name.kind not in ("word", "literal") or name.upper in _COPY_OPTIONS:
        return 1
    qualifier, cursor, replacing = "", index + 2, 0
    while cursor < len(tokens) and tokens[cursor].text != ".":
        current = tokens[cursor]
        if current.upper in ("OF", "IN") and cursor + 1 < len(tokens):
            qualifier = tokens[cursor + 1].text.upper()
            cursor += 2
            continue
        if current.upper == "REPLACING":
            replacing = 1
        elif current.kind == "pseudo" and replacing:
            replacing += 1
        elif current.kind == "word" and current.upper not in ("SUPPRESS", "BY", "LEADING", "TRAILING"):
            if replacing == 0:
                break
        cursor += 1
    state.ref(name, "copies", "copybook", name.text.upper(), clause="COPY", qualifier=qualifier,
              detail=_replacing_detail(tokens, index, cursor, replacing, state))
    return cursor - index if cursor > index else 1


def _replacing_detail(tokens: list[Token], start: int, end: int, replacing: int, state: _State) -> tuple[tuple[str, str], ...]:
    """``COPY`` detail carrying the ``REPLACING`` pairs exactly as written, plus the shared refusal when the clause
    cannot be applied.

    Discovery records what the clause says; it does not expand it.  The clause is read by the one REPLACING grammar
    (:func:`copy_replacing.parse_tokens`), so the problem code reported here is exactly the code generation reports
    for the same clause — ``COPYBOOK_REPLACING_UNSUPPORTED`` for a form neither side applies (layer 4, acceptance
    criterion 8), ``COPYBOOK_REPLACING_MALFORMED`` for a clause that does not parse — with the grammar's own
    message naming ``REPLACING``.
    """
    if not replacing:
        return detail()
    clause = copy_replacing.parse_tokens(tokens, start, end)
    if clause.error:
        code, message = clause.error
        state.scan.problems.append(ScanProblem(state.path, tokens[start].line, code, message))
    info: dict[str, object] = {"replacing": "yes"}
    if clause.pairs:
        info["replacing_pairs"] = "; ".join(f"{left} BY {right}" for left, right in clause.pairs)
        info["replacing_count"] = str(len(clause.pairs))
    return detail(**info)


def _call(tokens: list[Token], index: int, state: _State, verb: str) -> int:
    target = tokens[index + 1] if index + 1 < len(tokens) else None
    if target is None or not _starts_statement(tokens, index) and verb == "CALL" and target.kind == "punct":
        return 1
    if target.kind == "word" and target.upper in ("PROCEDURE-POINTER", "FUNCTION", "ADDRESS"):
        return 1
    if target.kind not in ("literal", "word"):
        return 1
    args = _call_args(tokens, index + 2)
    if target.kind == "literal":
        name = target.text.upper().strip()
        if not classify_call(state, target, name, args, verb):
            state.ref(target, "calls", "program", name, clause=verb, detail=detail(arguments=len(args)))
    else:
        state.deferred.append((target, "calls", "program", target.upper, verb, detail(arguments=",".join(args)), ""))
    return 2


def _call_args(tokens: list[Token], start: int) -> list[str]:
    if start >= len(tokens) or tokens[start].upper != "USING":
        return []
    args: list[str] = []
    for token in tokens[start + 1:start + 40]:
        if token.kind == "word":
            if token.upper in ("BY", "REFERENCE", "CONTENT", "VALUE", "OMITTED"):
                continue
            if token.upper in _VERBS:
                break
            args.append(token.upper)
        elif token.kind == "literal":
            args.append(f"'{token.text}'")
        elif token.text == ".":
            break
    return args


def _exec_block(tokens: list[Token], index: int, state: _State) -> int:
    """Parse one ``EXEC ... END-EXEC`` block.

    A block that lost its ``END-EXEC`` (typically cut off by the column-72 limit of fixed format) ends where the
    next ``EXEC`` begins, so it cannot swallow the following statement; the damage is reported as a problem.
    """
    end = None
    unclosed = False
    for i in range(index + 1, len(tokens)):
        token = tokens[i]
        if token.kind != "word":
            continue
        if token.upper == "END-EXEC":
            end = i
            break
        if token.upper == "EXEC":
            end, unclosed = i, True
            break
    if end is None:
        state.scan.problems.append(ScanProblem(state.path, tokens[index].line, "EXEC_NOT_CLOSED",
                                               "EXEC block has no END-EXEC"))
        return 1
    if unclosed:
        state.scan.problems.append(ScanProblem(state.path, tokens[index].line, "EXEC_NOT_CLOSED",
                                               "EXEC block has no END-EXEC before the next EXEC "
                                               "(text past column 72 is ignored in fixed format)"))
    parse_exec(state, tokens[index], tokens[index + 1:end])
    return end - index + (0 if unclosed else 1)


def _environment(tokens: list[Token], index: int, state: _State) -> None:
    window = tokens[index:index + 6]
    words = [t.upper for t in window if t.kind == "word"]
    if tokens[index].upper == "ACCEPT" and "ENVIRONMENT" in words:
        literal = next((t for t in window if t.kind == "literal"), None)
        state.fact(tokens[index], "environment", literal.text if literal else "(dynamic)", access="ACCEPT FROM ENVIRONMENT")
    elif tokens[index].upper == "DISPLAY" and "ENVIRONMENT-NAME" in [t.upper for t in tokens[index:index + 6]
                                                                  if t.kind == "word"]:
        literal = next((t for t in window if t.kind == "literal"), None)
        state.fact(tokens[index], "environment", literal.text if literal else "(dynamic)", access="DISPLAY UPON ENVIRONMENT-NAME")


def _finish(tokens: list[Token], state: _State, copybook: bool) -> None:
    for target, relation, kind, variable, clause, info, mode in state.deferred:
        candidates = state.values.get(variable, {})
        if not candidates:
            state.ref(target, relation, kind, "", clause=clause, dynamic=True, variable=variable, detail=info,
                      mode=mode)
            continue
        for literal, (source, _line, _column) in sorted(candidates.items()):
            state.ref(target, relation, kind, literal.upper().strip(), clause=clause, dynamic=True, variable=variable,
                      detail=tuple(sorted(info + (("value_source", source),))), mode=mode)
    for variable, candidates in sorted(state.values.items()):
        if "OBJECTNAME" in variable or variable.endswith(("-QNAME", "-QUEUE-NAME")):
            for literal, (source, line, column) in sorted(candidates.items()):
                marker = Token("literal", literal, line, column)
                state.ref(marker, "uses-queue", "mq-queue", literal.upper().strip(), clause=f"{source} {variable}",
                          detail=detail(heuristic="queue name moved to an MQ object descriptor field"))
    if len(state.programs) > 1:
        state.scan.problems.append(ScanProblem(state.path, tokens[-1].line if tokens else 1, "PROGRAM_NOT_CLOSED",
                                               f"no END PROGRAM for nested program {state.programs[-1]}"))
    has_program = any(f.category == "program-id" for f in state.scan.facts)
    if not copybook and not has_program and tokens:
        state.scan.problems.append(ScanProblem(state.path, 1, "NO_PROGRAM_ID",
                                               "classified as a COBOL program but contains no PROGRAM-ID"))


def _open_literal_lines(lines) -> list[int]:
    """Logical lines that end inside an alphanumeric literal (after continuation folding): a reference-format error."""
    bad = []
    for line in lines:
        quote = ""
        for ch in line.text:
            if not quote and ch in "\"'":
                quote = ch
            elif ch == quote:
                quote = ""
        if quote:
            bad.append(line.number)
    return bad
