"""Structural scan of COBOL source: divisions, sections, paragraphs, data descriptions, control flow, file verbs,
intra-program data flow and the ``COPY ... REPLACING`` clause.

No parsing, no execution, no LLM: every finding is a token span with an exact ``(line, column)``.  The module is
deliberately free of the scanner's own state so the same REPLACING parser can be shared with the transformation side
(the only other REPLACING parser in the repository lives in ``engine/transformation/copybook_resolver.py``).

Scope and honesty about limits:

* Data flow (``MOVE``/arithmetic/conditions) is **intra-file**: a name is only followed when it is described in the
  file being scanned.  A name a ``COPY`` brings in belongs to the copybook and is linked through the ``copies`` edge
  and the copybook's own data items, never re-emitted per reference.
* ``REPLACING`` pairs — pseudo-text, COBOL-word and literal operands — are recorded in source order and never
  applied here; the name a pair produces is linked to the including program by the resolver.  ``LEADING``/
  ``TRAILING``/``PARTIAL`` and an unpaired operand are reported as ``COPY_REPLACING_UNSUPPORTED``, never
  approximated.
* Sections, paragraphs and control flow are only recognised inside a ``PROCEDURE DIVISION``.  A source with no such
  header (a data-only copybook) contributes data descriptions only, never a guessed paragraph.
* ``PERFORM <data-name> TIMES`` is a repetition count, not a paragraph reference, and is not emitted; ``GO TO``
  over a data name is a run-time transfer and is emitted as dynamic, never as a guessed paragraph.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .cobol_text import Token, split_indexed

__all__ = ["StructureScan", "Unit", "FlowRef", "DataDecl", "scan_structure", "parse_replacing", "data_node_id",
           "scoped_node_id", "SUPPORTED_REPLACING_FORMS", "UNSUPPORTED_REPLACING_FORMS"]

#: ``COPY ... REPLACING`` forms this scanner understands.  Anything else is refused by name, never guessed.
SUPPORTED_REPLACING_FORMS = ("BY",)
UNSUPPORTED_REPLACING_FORMS = ("LEADING", "TRAILING", "PARTIAL")

#: Levels that introduce a record layout rather than a plain field.
_RECORD_LEVELS = frozenset({"1", "01"})
#: Levels a data description entry may carry.
_VALID_LEVELS = frozenset(str(n) for n in range(1, 50)) | {"66", "77", "78", "88"}


def scoped_node_id(owner: str, name: str, kind: str) -> str:
    """Node id of something declared under ``owner`` (``program:PAYROLL`` or ``file:cpy/C.cpy``).

    Scoping by the declaring owner is what makes two programs that both have a ``MAIN-PARA`` two different nodes,
    and what makes a data item found in a copybook a different node from the same name in a program.
    """
    kind_name, _, rest = owner.partition(":")
    scope = rest if rest else kind_name
    return f"{kind}:{scope}/{name.upper()}"


def data_node_id(owner: str, name: str, kind: str = "data-item") -> str:
    """Node id of a data description owned by ``owner`` (``program:PAYROLL`` or ``file:cpy/C.cpy``)."""
    return scoped_node_id(owner, name, kind)


@dataclass(frozen=True)
class Unit:
    """A section or paragraph header in a ``PROCEDURE DIVISION``."""

    kind: str  # "section" | "paragraph"
    name: str
    line: int
    column: int
    section: str
    program: str


@dataclass(frozen=True)
class FlowRef:
    """One reference found by the structural pass: control flow, a file verb or a data-flow step."""

    relation: str
    target_kind: str
    target: str
    line: int
    column: int
    clause: str
    mode: str = ""
    detail: tuple[tuple[str, str], ...] = ()
    #: Program that owns the reference (empty for a file-level owner).
    program: str = ""
    #: The transfer target is held in a data item at run time (``GO TO WS-PARA``): no static target exists.
    dynamic: bool = False
    #: The data item that carries the dynamic target.
    variable: str = ""


@dataclass(frozen=True)
class DataDecl:
    """One data description entry (or the record it belongs to)."""

    kind: str  # "data-item" | "record-layout" | "screen-field"
    name: str
    level: str
    line: int
    column: int
    owner: str
    record: str = ""
    file: str = ""


@dataclass
class StructureScan:
    units: list[Unit] = field(default_factory=list)
    refs: list[FlowRef] = field(default_factory=list)
    data: list[DataDecl] = field(default_factory=list)
    #: ``(line, code, message)`` — a construct the scanner could not read the way it is specified.
    problems: list[tuple[int, str, str]] = field(default_factory=list)


# --- divisions and program nesting -------------------------------------------------------------------------

_DIVISIONS = ("IDENTIFICATION", "ID", "ENVIRONMENT", "DATA", "PROCEDURE")
_DIVISION_WORDS = frozenset(_DIVISIONS) | {"DIVISION"}


def _program_and_division(tokens: list[Token]) -> tuple[list[str], list[str]]:
    """Per token: the program id that encloses it and the division it sits in.  Both reset at ``PROGRAM-ID``."""
    owners = [""] * len(tokens)
    divisions = [""] * len(tokens)
    open_programs: list[str] = []
    division = ""
    for index, token in enumerate(tokens):
        if token.kind == "word" and token.upper == "PROGRAM-ID":
            open_programs.append(_program_name(tokens, index))
            division = ""
        elif token.kind == "word" and token.upper == "END" and index + 1 < len(tokens) \
                and tokens[index + 1].upper == "PROGRAM":
            if open_programs:
                open_programs.pop()
            division = ""
        elif token.kind == "word" and token.upper in ("IDENTIFICATION", "ID", "ENVIRONMENT", "DATA", "PROCEDURE") \
                and index + 1 < len(tokens) and tokens[index + 1].upper == "DIVISION":
            division = "PROCEDURE" if token.upper == "PROCEDURE" else ("DATA" if token.upper == "DATA" else token.upper)
        owners[index] = open_programs[-1] if open_programs else ""
        divisions[index] = division
    return owners, divisions


def _program_name(tokens: list[Token], index: int) -> str:
    """The program name after ``PROGRAM-ID`` (``PROGRAM-ID. NAME.`` or ``PROGRAM-ID IS NAME.``)."""
    for cursor in range(index + 1, min(index + 6, len(tokens))):
        token = tokens[cursor]
        if token.text == ".":
            if cursor + 1 < len(tokens) and tokens[cursor + 1].kind in ("word", "literal") \
                    and tokens[cursor + 1].upper not in _DIVISION_WORDS:
                return tokens[cursor + 1].upper
            continue
        if token.kind in ("word", "literal") and token.upper not in {"IS", "ARE"} | _DIVISION_WORDS:
            return token.upper
    return ""


# --- COPY REPLACING -----------------------------------------------------------------------------------------


def parse_replacing(tokens: list[Token], start: int, end: int) -> tuple[list[tuple[str, str]], list[str]]:
    """Pairs and unsupported forms of the ``REPLACING`` clause in ``tokens[start:end]``.

    Returns ``(pairs, unsupported)`` where a pair is ``(left, right)`` as written (pseudo-text without the ``==``
    delimiters, a literal in single quotes), in source order, and ``unsupported`` names every form this scanner
    refuses to approximate.  Pseudo-text, COBOL-word and literal operands are all *recorded* — discovery never
    expands them, so recording is a superset of what the transformation side applies, never a silent drop.
    """
    pairs: list[tuple[str, str]] = []
    unsupported: list[str] = []
    cursor = start
    while cursor < end and not (tokens[cursor].kind == "word" and tokens[cursor].upper == "REPLACING"):
        cursor += 1
    if cursor >= end:
        return pairs, unsupported
    cursor += 1
    pending: list[str] = []
    while cursor < end:
        token = tokens[cursor]
        if token.kind == "pseudo":
            pending.append(token.text.upper())
        elif token.kind == "literal":
            text = token.text
            pending.append(text if text[:1] in ("'", '"') else f"'{text}'")
        elif token.kind == "number":
            pending.append(token.text)
        elif token.kind == "word":
            if token.upper in UNSUPPORTED_REPLACING_FORMS:
                if token.upper not in unsupported:
                    unsupported.append(token.upper)
            elif token.upper != "BY":
                pending.append(token.upper)
        cursor += 1
    # Operands arrive left, BY, right; pairing them in order is the only reading the grammar allows here.
    for index in range(0, len(pending) - 1, 2):
        pairs.append((pending[index], pending[index + 1]))
    if len(pending) % 2:
        unsupported.append("UNPAIRED-PSEUDO-TEXT")
    return pairs, unsupported


# --- the structural pass ------------------------------------------------------------------------------------


def scan_structure(tokens: list[Token], *, path: str, copybook: bool = False) -> StructureScan:
    """Sections, paragraphs, data descriptions, control flow, file verbs and data flow of one source."""
    out = StructureScan()
    if not tokens:
        return out
    owners, divisions = _program_and_division(tokens)
    sentences = sorted(split_indexed(tokens))
    section = ""
    record = ""
    record_file = ""
    screen_section = False
    #: owner -> data names described in that owner (data flow only ever follows a real data name).
    described: dict[str, set[str]] = {}

    for start, sentence in sentences:
        if not sentence:
            continue
        owner_index = min(start, len(owners) - 1)
        program = owners[owner_index]
        division = divisions[owner_index]
        owner = f"program:{program}" if program else f"file:{path}"
        head = sentence[0]
        if head.text.isdigit():
            sentence = _merge_tagged_name(sentence)

        if division == "PROCEDURE":
            unit = _procedure_header(sentence, program, section)
            if unit is not None:
                if unit.kind == "section":
                    section = unit.name
                out.units.append(unit)
                continue
            out.refs.extend(_procedure_sentence(sentence, program, owner, described))
            continue

        # Everything outside PROCEDURE DIVISION: data descriptions, file descriptions, screen sections.  A level
        # number can never start a procedure statement, so this is unambiguous; a source with no division header
        # (a copybook) is treated the same way.  ``tokenize`` classifies a level number as a word (it is a COBOL
        # word, not a numeric literal), so the digits are what identify it.
        if head.text.isdigit() and len(sentence) >= 2 and sentence[1].kind == "word":
            level = str(int(head.text))
            if level in _VALID_LEVELS:
                decl, record, record_file, is_screen = _data_sentence(sentence, owner, screen_section, record,
                                                                      record_file)
                # ``FILLER`` cannot be addressed by name, so it is never a node and never a data-flow endpoint;
                # the record it belongs to is still tracked for the entries under it.
                if not (decl.name.upper() == "FILLER" and decl.kind != "record-layout"):
                    out.data.append(decl)
                    described.setdefault(owner, set()).add(decl.name.upper())
                if decl.kind == "record-layout":
                    screen_section = is_screen
            elif division in ("", "DATA"):
                out.problems.append((head.line, "DATA_DECL_LEVEL_UNKNOWN",
                                     f"level {level} is not a data description level"))
            continue
        if head.kind == "word" and head.upper == "SCREEN" and len(sentence) > 1 and sentence[1].upper == "SECTION":
            screen_section = True
            continue
        if head.kind == "word" and head.upper in ("FD", "SD") and len(sentence) > 1:
            record, record_file, screen_section = "", sentence[1].upper, False
            continue
    return out


def _merge_tagged_name(sentence: list[Token]) -> list[Token]:
    """Join a pseudo-text tagged data name (``:TR:-REC``) back into one word token.

    The tokenizer cuts ``:TR:-REC`` into ``:`` ``TR`` ``:`` ``-`` ``REC``.  A copybook written with such tags is
    only meaningful after ``COPY ... REPLACING ==:TR:== BY ==PAY==``, but its entries are still declarations, so the
    name (the adjacent tokens that start with a colon) is merged to one word and the tag is expanded by the resolver.
    """
    if len(sentence) < 2 or sentence[1].kind != "punct" or sentence[1].text != ":":
        return sentence
    first = sentence[1]
    end, text = 2, first.text
    previous = first
    while end < len(sentence):
        token = sentence[end]
        adjacent = token.line == previous.line and token.column == previous.column + len(previous.text)
        allowed = token.kind in ("word", "number") or (token.kind == "punct" and token.text in (":", "-"))
        if not adjacent or not allowed:
            break
        text += token.text
        previous = token
        end += 1
    if text.count(":") < 2:
        return sentence
    return [sentence[0], Token("word", text, first.line, first.column), *sentence[end:]]


def _procedure_header(sentence: list[Token], program: str, section: str) -> Unit | None:
    """A paragraph (``NAME.``) or section (``NAME SECTION.``) header — only inside a ``PROCEDURE DIVISION``.

    Sentences arrive with their terminating period already consumed by :func:`split_indexed`, so a paragraph is a
    single word and a section is exactly two.
    """
    head = sentence[0]
    if head.kind != "word":
        return None
    if len(sentence) >= 2 and sentence[1].upper == "SECTION" and sentence[1].kind == "word":
        return Unit("section", head.upper, head.line, head.column, "", program)
    if len(sentence) == 1 and head.upper not in _VERB_WORDS:
        return Unit("paragraph", head.upper, head.line, head.column, section, program)
    return None


#: Verbs and clause words that end a sentence on their own and are therefore never a paragraph name.
_VERB_WORDS = frozenset({
    "MOVE", "IF", "PERFORM", "DISPLAY", "ADD", "COMPUTE", "CALL", "GO", "STOP", "EVALUATE", "READ", "WRITE", "OPEN",
    "CLOSE", "EXIT", "GOBACK", "SET", "STRING", "UNSTRING", "INITIALIZE", "ACCEPT", "END-CALL", "ELSE", "END-IF",
    "WHEN", "NOT", "ON", "RETURNING", "EXEC", "COPY", "INSPECT", "SORT", "MERGE", "SEARCH", "SUBTRACT", "MULTIPLY",
    "DIVIDE", "CONTINUE", "RETURN", "REWRITE", "DELETE", "START", "RELEASE", "CANCEL", "ENTRY", "USE", "ALTER",
    "END-PERFORM", "END-EVALUATE", "END-READ", "END-WRITE", "EXCEPTION", "OVERFLOW", "INVALID", "AT", "END",
    "END-STRING", "END-UNSTRING", "END-ADD", "END-SUBTRACT", "END-MULTIPLY", "END-DIVIDE", "OTHERWISE", "TRUE",
    "FALSE", "OTHER", "NEXT", "SENTENCE", "DECLARATIVES", "END-DECLARATIVES", "SECTION",
})

#: Words that follow ``PERFORM`` when it has no paragraph target (inline or conditional forms).
_PERFORM_NO_TARGET = frozenset({"UNTIL", "VARYING", "WITH", "TEST", "TIME", "TIMES", "BEFORE", "AFTER", "FROM", "TO",
                                "BY", "THRU", "THROUGH", "ON", "EXIT"})


def _procedure_sentence(sentence: list[Token], program: str, owner: str, described: dict[str, set[str]]
                        ) -> list[FlowRef]:
    refs: list[FlowRef] = []
    words = [t.upper if t.kind == "word" else "" for t in sentence]
    head = words[0] if words else ""

    if head == "PERFORM":
        refs.extend(_perform(sentence, program, owner, described))
        # Inline ``PERFORM ... END-PERFORM`` bodies hold further statements; each nested PERFORM is its own edge.
        for index in range(1, len(sentence)):
            if words[index] == "PERFORM":
                refs.extend(_perform(sentence[index:], program, owner, described))
    elif head == "GO":
        refs.extend(_go_to(sentence, program, owner, described))
    elif head in ("READ", "WRITE", "REWRITE"):
        refs.extend(_file_verb(sentence, program, head))
    elif head == "MOVE":
        refs.extend(_move(sentence, program, owner, described))
    elif head in ("ADD", "SUBTRACT", "MULTIPLY", "DIVIDE", "COMPUTE", "SET", "INITIALIZE", "STRING", "UNSTRING"):
        refs.extend(_assign(sentence, program, owner, described, head))
    elif head in ("IF", "EVALUATE"):
        refs.extend(_condition_reads(sentence, program, owner, described))
    return refs


def _perform(sentence: list[Token], program: str, owner: str, described: dict[str, set[str]]) -> list[FlowRef]:
    names = described.get(owner, set())
    cursor = 1
    if cursor >= len(sentence):
        return []
    target = sentence[cursor]
    if target.kind != "word" or target.text.isdigit() or target.upper in _PERFORM_NO_TARGET or target.upper in names:
        # ``PERFORM n TIMES`` / ``PERFORM WS-COUNT ...``: a repetition count, not a paragraph reference.
        return []
    detail: tuple[tuple[str, str], ...] = ()
    refs: list[FlowRef] = []
    for index in range(cursor + 1, len(sentence)):
        token = sentence[index]
        if token.kind == "word" and token.upper in ("THRU", "THROUGH") and index + 1 < len(sentence):
            thru = sentence[index + 1]
            detail = (("thru", thru.upper),)
            if thru.kind == "word" and not thru.text.isdigit() and thru.upper != target.upper \
                    and thru.upper not in names:
                refs.append(FlowRef("performs", "paragraph", thru.upper, thru.line, thru.column, "PERFORM THRU",
                                    mode="control", program=program))
            break
        if token.kind == "word" and token.upper in ("UNTIL", "VARYING", "WITH", "TEST"):
            break
    refs.insert(0, FlowRef("performs", "paragraph", target.upper, target.line, target.column, "PERFORM",
                           mode="control", detail=detail, program=program))
    return refs


def _go_to(sentence: list[Token], program: str, owner: str, described: dict[str, set[str]]) -> list[FlowRef]:
    names = described.get(owner, set())
    refs: list[FlowRef] = []
    for token in sentence[1:]:
        if token.kind != "word":
            continue
        if token.upper == "DEPENDING":
            break
        if token.upper in ("TO", "BACK"):
            continue
        if token.upper in names:
            # ``GO TO WS-PARA``: the destination lives in a data item, so no static paragraph exists.
            refs.append(FlowRef("goes-to", "paragraph", "", token.line, token.column, "GO TO", mode="control", program=program,
                                dynamic=True, variable=token.upper))
            continue
        refs.append(FlowRef("goes-to", "paragraph", token.upper, token.line, token.column, "GO TO", mode="control", program=program))
    return refs


def _file_verb(sentence: list[Token], program: str, verb: str) -> list[FlowRef]:
    relation = {"READ": "reads-file", "WRITE": "writes-file", "REWRITE": "rewrites-file"}[verb]
    mode = {"READ": "read", "WRITE": "write", "REWRITE": "update"}[verb]
    if len(sentence) < 2 or sentence[1].kind != "word":
        return []
    operand = sentence[1]
    detail: tuple[tuple[str, str], ...] = (("record", operand.upper),) if verb != "READ" else ()
    return [FlowRef(relation, "logical-file", operand.upper, operand.line, operand.column, verb, mode=mode,
                    detail=detail, program=program)]


def _move(sentence: list[Token], program: str, owner: str, described: dict[str, set[str]]) -> list[FlowRef]:
    names = described.get(owner, set())
    words = [t for t in sentence[1:] if t.kind == "word"]
    try:
        to = next(index for index, token in enumerate(words) if token.upper == "TO")
    except StopIteration:
        return []
    source = words[:to]
    targets = words[to + 1:]
    if not source or source[0].upper not in names:
        return []
    refs = []
    for target in targets:
        if target.upper not in names or target.upper == source[0].upper:
            continue
        refs.append(FlowRef("moves-to", "data-item", target.upper, target.line, target.column, "MOVE", mode="write",
                            detail=(("source", source[0].upper),), program=program))
    return refs


#: Statements whose destination is a data name written by the statement.
_ASSIGN_RELATIONS = {
    "ADD": "TO", "SUBTRACT": "FROM", "MULTIPLY": "BY", "DIVIDE": "INTO", "COMPUTE": "=",
}


def _assign(sentence: list[Token], program: str, owner: str, described: dict[str, set[str]], verb: str
            ) -> list[FlowRef]:
    names = described.get(owner, set())
    words = [t for t in sentence[1:] if t.kind == "word"]
    anchors = {"SET": ("TO", "BY"), "INITIALIZE": (), "STRING": ("INTO",), "UNSTRING": ("INTO",)}
    if verb in anchors:
        keys = anchors[verb]
        if verb == "INITIALIZE":
            targets = words
        else:
            hits = [index for index, token in enumerate(words) if token.upper in keys]
            if not hits:
                return []
            targets = words[hits[-1] + 1:]
    else:
        key = _ASSIGN_RELATIONS[verb]
        hits = [index for index, token in enumerate(words) if token.upper == key]
        if not hits:
            return []
        targets = words[hits[-1] + 1:]
    refs = []
    for target in targets:
        if target.upper not in names:
            continue
        refs.append(FlowRef("writes-item", "data-item", target.upper, target.line, target.column, verb, mode="write",
                            program=program))
    return refs


def _condition_reads(sentence: list[Token], program: str, owner: str, described: dict[str, set[str]]) -> list[FlowRef]:
    names = described.get(owner, set())
    refs = []
    seen: set[str] = set()
    for token in sentence[1:]:
        if token.kind != "word" or token.upper not in names or token.upper in seen:
            continue
        seen.add(token.upper)
        refs.append(FlowRef("reads-item", "data-item", token.upper, token.line, token.column,
                            sentence[0].upper, mode="read", program=program))
    return refs


def _data_sentence(sentence: list[Token], owner: str, screen_section: bool, record: str,
                   record_file: str) -> tuple[DataDecl, str, str, bool]:
    """One level-numbered sentence -> its declaration, plus the record/screen state it leaves behind."""
    head = sentence[0]
    name_token = sentence[1]
    level = str(int(head.text))
    words = [t.upper for t in sentence if t.kind == "word"]
    is_screen = screen_section or "SCREEN" in words
    if level in _RECORD_LEVELS:
        decl = DataDecl("record-layout", name_token.upper, level, name_token.line, name_token.column, owner,
                        file=record_file)
        return decl, name_token.upper, record_file, is_screen
    kind = "screen-field" if is_screen else "data-item"
    decl = DataDecl(kind, name_token.upper, level, name_token.line, name_token.column, owner, record=record,
                    file=record_file)
    return decl, record, record_file, False
