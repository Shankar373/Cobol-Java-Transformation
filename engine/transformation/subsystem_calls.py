"""Real IBM MQ and IMS call forms (classification only; nothing is transformed).

``EXEC MQI`` is not IBM syntax. Real programs call the queue manager and DL/I
through ordinary COBOL calls::

    CALL 'MQCONN'  USING QMGR HCONN CC RC
    CALL 'MQOPEN'  USING HCONN MQOD OPTS HOBJ CC RC
    CALL 'CBLTDLI' USING DLI-GU IMSPCB IO-AREA SSA-CUST
    CALL 'AIBTDLI' USING DLI-GN AIBBLK IO-AREA

The registry scanner strips every literal before matching (so ``DISPLAY
"CALL 'MQOPEN'"`` can never match), which also hides the called name; this
module reads the text the compiler reads, keeps literals only where a CALL
statement names its target, and resolves the argument names it can resolve
from ``VALUE`` clauses. Dynamic calls (``CALL WS-PROG`` with the name in a
data item) are not detected here; an unresolved CALL target is already
blocked by the static-CALL dependency check.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Queue manager verbs called by name (MQI).
MQI_VERBS = frozenset({
    "MQCONN", "MQCONNX", "MQDISC", "MQOPEN", "MQCLOSE", "MQGET", "MQPUT", "MQPUT1",
    "MQINQ", "MQSET", "MQBEGIN", "MQCMIT", "MQBACK", "MQSUB", "MQSUBRQ", "MQCB",
    "MQCTL", "MQSTAT",
})
#: DL/I call entry points (IMS batch, BMP, MPP; language interfaces).
DLI_ENTRIES = frozenset({"CBLTDLI", "AIBTDLI", "CEETDLI", "PLITDLI"})

_LITERAL = r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\""
# A CALL whose target is a literal, or any other literal (consumed so text
# inside a string can never be read as code).
_CALL_OR_LITERAL = re.compile(
    r"(?<![\w-])CALL\s+(?P<q>['\"])(?P<name>[^'\"\r\n]*)(?P=q)|(?P<lit>" + _LITERAL + ")",
    re.IGNORECASE,
)
_PRECHECK = re.compile(
    r"CALL\s+['\"](?:MQ|CBLTDLI|AIBTDLI|CEETDLI|PLITDLI)", re.IGNORECASE
)
_PROCEDURE = re.compile(r"(?<![\w-])PROCEDURE\s+DIVISION(?![\w-])", re.IGNORECASE)
_LITERAL_RE = re.compile(_LITERAL)
_ARG_TOKEN = re.compile(_LITERAL + r"|[^\s]+")
_ARG_END = re.compile(
    r"(?<![\w-])END-CALL(?![\w-])|(?<![\w-])ON\s+EXCEPTION(?![\w-])|(?<![\w-])NOT\s+ON(?![\w-])"
    r"|\.(?:\s|$)",
    re.IGNORECASE,
)
_NOISE = {"BY", "REFERENCE", "CONTENT", "VALUE"}


@dataclass(frozen=True)
class SubsystemCall:
    subsystem: str  # "MQ" | "IMS"
    name: str  # upper-case called name, e.g. MQOPEN, CBLTDLI
    args: tuple[str, ...]  # argument tokens as written (quotes kept)


def _comment_free(source: str) -> str:
    """The compiler-visible text with comment lines and inline ``*>`` removed.

    Literals are kept. Inline ``*>`` is located on a copy where every literal
    is blanked to the same length, so a ``*>`` inside a string never cuts.
    """
    from engine.transformation.source_format import compiler_visible_text, detect_source_format

    fixed = detect_source_format(source) == "fixed"
    kept: list[str] = []
    for line in compiler_visible_text(source).splitlines():
        if fixed and len(line) > 6 and line[6] in "*/Dd":
            continue
        stripped = line.lstrip()
        if stripped.startswith("*>") or (not fixed and stripped[:1] == "*"):
            continue
        blanked = _LITERAL_RE.sub(lambda m: " " * len(m.group(0)), line)
        marker = blanked.find("*>")
        kept.append(line[:marker] if marker >= 0 else line)
    return "\n".join(kept)


def _split_divisions(text: str) -> tuple[str, str]:
    blanked = _LITERAL_RE.sub(lambda m: " " * len(m.group(0)), text)
    match = _PROCEDURE.search(blanked)
    if not match:
        return text, ""
    return text[: match.start()], text[match.start():]


def _args(tail: str) -> tuple[str, ...]:
    using = re.match(r"\s*USING\s+", tail, re.IGNORECASE)
    if not using:
        return ()
    body = tail[using.end():]
    end = _ARG_END.search(_LITERAL_RE.sub(lambda m: " " * len(m.group(0)), body))
    body = body[: end.start()] if end else body
    tokens = [t for t in _ARG_TOKEN.findall(body) if t.upper() not in _NOISE]
    out: list[str] = []
    for token in tokens:
        if token.upper() == "RETURNING":
            break
        out.append(token)
    return tuple(out)


def find_subsystem_calls(source: str) -> list[SubsystemCall]:
    """MQ and IMS calls in the PROCEDURE DIVISION, in source order."""
    if not _PRECHECK.search(source):
        return []  # the common case: no such call anywhere (masking only removes text)
    _, procedure = _split_divisions(_comment_free(source))
    calls: list[SubsystemCall] = []
    for match in _CALL_OR_LITERAL.finditer(procedure):
        if match.group("name") is None:
            continue  # some other literal: consumed, never code
        name = match.group("name").strip().upper()
        if name in MQI_VERBS:
            subsystem = "MQ"
        elif name in DLI_ENTRIES:
            subsystem = "IMS"
        else:
            continue
        calls.append(SubsystemCall(subsystem, name, _args(procedure[match.end():])))
    return calls


_VALUE_ENTRY = re.compile(
    r"(?im)^\s*\d{1,2}\s+(?P<name>[A-Z0-9][\w-]*)\b[^.]*?\bVALUE\s+(?:IS\s+)?(?P<lit>" + _LITERAL + ")"
)


def value_literals(source: str) -> dict[str, str]:
    """``{DATA-NAME: literal}`` for every elementary item with a ``VALUE`` literal."""
    data, _ = _split_divisions(_comment_free(source))
    out: dict[str, str] = {}
    for match in _VALUE_ENTRY.finditer(data):
        out.setdefault(match.group("name").upper(), unquote(match.group("lit")))
    return out


def unquote(token: str) -> str:
    if len(token) >= 2 and token[0] == token[-1] and token[0] in "'\"":
        return token[1:-1].replace(token[0] * 2, token[0])
    return token


_MOVE_OBJECT = re.compile(
    r"(?<![\w-])MOVE\s+(?P<lit>" + _LITERAL + r")\s+TO\s+(?P<target>[\w-]*OBJECTNAME)(?![\w-])",
    re.IGNORECASE,
)


def queue_names(source: str) -> list[str]:
    """Queue names reaching an MQOD ``OBJECTNAME`` field (VALUE or MOVE literal)."""
    text = _comment_free(source)
    names: list[str] = []
    for name, value in value_literals(source).items():
        if name.endswith("OBJECTNAME") and not name.endswith("QMGRNAME"):
            names.append(value.strip())
    for match in _MOVE_OBJECT.finditer(text):
        names.append(unquote(match.group("lit")).strip())
    return [n for n in dict.fromkeys(names) if n]


def queue_manager_names(source: str, calls: list[SubsystemCall]) -> list[str]:
    """Queue managers: the MQCONN/MQCONNX first argument and ``OBJECTQMGRNAME`` values."""
    values = value_literals(source)
    names: list[str] = []
    for call in calls:
        if call.name in {"MQCONN", "MQCONNX"} and call.args:
            first = call.args[0]
            names.append(unquote(first) if first[0] in "'\"" else values.get(first.upper(), ""))
    for name, value in values.items():
        if name.endswith("OBJECTQMGRNAME"):
            names.append(value)
    return [n.strip() for n in dict.fromkeys(names) if n.strip()]
