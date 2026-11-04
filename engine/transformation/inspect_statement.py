"""INSPECT statement: tokenising the certified TALLYING / REPLACING / CONVERTING subset.

The certified subset operates on literal operands only.  A phrase is one of

* ``TALLYING counter FOR {CHARACTERS | ALL lit | LEADING lit} ...``
* ``REPLACING {CHARACTERS BY lit | ALL lit BY lit | LEADING lit BY lit | FIRST lit BY lit} ...``
* ``CONVERTING lit TO lit``

each optionally narrowed by ``BEFORE INITIAL lit`` and/or ``AFTER INITIAL lit``.  Everything
else (data-name operands, hex or ALL literals, HIGH-VALUE/LOW-VALUE/QUOTE, ``TRAILING``,
a combined ``TALLYING ... REPLACING``, unequal replacement lengths) is recorded as a
*reason*; the mapper turns a reason into an unresolvable symbol so the statement fails closed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_TOKEN = re.compile(r'"(?:[^"]|"")*"|\'(?:[^\']|\'\')*\'|[^\s]+')
_FIGURATIVE = {"SPACE": " ", "SPACES": " ", "ZERO": "0", "ZEROS": "0", "ZEROES": "0"}
_KINDS = ("CHARACTERS", "ALL", "LEADING", "FIRST")
_STOP = {"BEFORE", "AFTER", "CHARACTERS", "ALL", "LEADING", "FIRST", "BY", "FOR", "TO",
         "TALLYING", "REPLACING", "CONVERTING", "TRAILING"}


@dataclass(frozen=True)
class InspectPhrase:
    """One counting, replacing or converting phrase with its BEFORE/AFTER bounds."""

    kind: str  # CHARACTERS | ALL | LEADING | FIRST | CONVERTING
    pattern: str = ""  # searched text (CONVERTING: the from-set)
    replacement: str = ""  # REPLACING BY / CONVERTING TO
    order: str = ""  # "", "A", "B", "AB" (after first), "BA" (before first)
    after: str = ""
    before: str = ""
    counter: str = ""  # TALLYING receiving item


def _literal(token: str) -> str | None:
    """Decoded alphanumeric literal or one-character figurative; ``None`` if unsupported."""
    if len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'":
        body = token[1:-1].replace(token[0] * 2, token[0])
        return body if body else None
    return _FIGURATIVE.get(token.upper())


def parse_inspect(text: str) -> tuple[str, str, tuple[InspectPhrase, ...], tuple[str, ...]]:
    """Return ``(target, mode, phrases, reasons)`` for one joined INSPECT statement."""
    tokens = _TOKEN.findall(text.strip().rstrip("."))
    reasons: list[str] = []
    if tokens and tokens[0].upper() == "INSPECT":
        tokens = tokens[1:]
    if not tokens:
        return "", "", (), ("EMPTY",)
    target = tokens[0]
    pos = 1
    upper = [t.upper() for t in tokens]
    if pos >= len(tokens) or upper[pos] not in ("TALLYING", "REPLACING", "CONVERTING"):
        return target, "", (), ("FORM",)
    mode = upper[pos]
    if "TALLYING" in upper[pos + 1:] or "REPLACING" in upper[pos + 1:] or (
            "CONVERTING" in upper[pos + 1:]):
        return target, mode, (), ("COMBINED",)
    pos += 1
    phrases: list[InspectPhrase] = []

    def literal_at(i: int, what: str) -> str | None:
        if i >= len(tokens):
            reasons.append(what + "_MISSING")
            return None
        value = _literal(tokens[i])
        if value is None:
            reasons.append(what + "_OPERAND")
        return value

    def bounds(i: int) -> tuple[int, str, str, str]:
        order, after, before = "", "", ""
        while i < len(tokens) and upper[i] in ("BEFORE", "AFTER"):
            which = upper[i]
            i += 1
            if i < len(tokens) and upper[i] == "INITIAL":
                i += 1
            value = literal_at(i, which)
            i += 1
            if which == "AFTER" and "A" not in order:
                order, after = order + "A", value or ""
            elif which == "BEFORE" and "B" not in order:
                order, before = order + "B", value or ""
            else:
                reasons.append("DUPLICATE_" + which)
        return i, order, after, before

    if mode == "CONVERTING":
        src = literal_at(pos, "CONVERTING")
        pos += 1
        if pos >= len(tokens) or upper[pos] != "TO":
            return target, mode, (), ("FORM",)
        dst = literal_at(pos + 1, "TO")
        pos, order, after, before = bounds(pos + 2)
        if src is not None and dst is not None and len(src) != len(dst):
            reasons.append("CONVERTING_LENGTHS")
        if pos < len(tokens):
            reasons.append("TRAILING_TEXT")
        phrases.append(InspectPhrase("CONVERTING", src or "", dst or "", order, after, before))
        return target, mode, tuple(phrases), tuple(dict.fromkeys(reasons))

    counter = ""
    last_kind = ""
    while pos < len(tokens):
        if mode == "TALLYING" and upper[pos] not in _STOP and tokens[pos][0] not in "\"'":
            if counter and tokens[pos] != counter:
                reasons.append("MULTIPLE_COUNTERS")
            counter = tokens[pos]
            last_kind = ""
            pos += 1
            if pos < len(tokens) and upper[pos] == "FOR":
                pos += 1
            else:
                reasons.append("FOR_MISSING")
            continue
        if last_kind and last_kind != "CHARACTERS" and tokens[pos][0] in "\"'":
            kind = last_kind  # ALL "A" "B": the kind carries over to the next literal
        else:
            kind = upper[pos]
            if kind not in _KINDS:
                reasons.append("CLAUSE_" + re.sub(r"[^A-Z0-9]", "_", kind))
                break
            pos += 1
        last_kind = kind
        pattern = ""
        replacement = ""
        if kind != "CHARACTERS":
            value = literal_at(pos, kind)
            pattern = value or ""
            pos += 1
        if mode == "REPLACING":
            if pos >= len(tokens) or upper[pos] != "BY":
                reasons.append("BY_MISSING")
                break
            value = literal_at(pos + 1, "BY")
            replacement = value or ""
            pos += 2
            if kind != "CHARACTERS" and value is not None and len(value) != len(pattern):
                reasons.append("REPLACING_LENGTHS")
            if kind == "CHARACTERS" and value is not None and len(value) != 1:
                reasons.append("REPLACING_LENGTHS")
        elif kind == "FIRST":
            reasons.append("CLAUSE_FIRST")
        pos, order, after, before = bounds(pos)
        phrases.append(InspectPhrase(kind, pattern, replacement, order, after, before,
                                     counter if mode == "TALLYING" else ""))
    if mode == "TALLYING":
        if not counter:
            reasons.append("COUNTER_MISSING")
        if not phrases:
            reasons.append("FOR_MISSING")
    elif not phrases:
        reasons.append("PHRASE_MISSING")
    return target, mode, tuple(phrases), tuple(dict.fromkeys(reasons))
