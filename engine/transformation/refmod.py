"""Reference modification ``name(start:length)`` in MOVE, DISPLAY and conditions (roadmap unit 32).

Certified subset, proven against GnuCOBOL 3.1.2 in ``tests/integration/test_refmod_oracle.py``:

* the base is a plain (unsubscripted) elementary alphanumeric item, or an unsigned integer DISPLAY item whose digits are
  addressed as characters; ``start`` and ``length`` are integer literals, unsigned integer DISPLAY items of at most nine
  digits, or ``item +/- literal``; ``length`` may be omitted (to the end of the item);
* a MOVE sender or receiver (receiver: an alphanumeric item), a DISPLAY operand, an operand of an alphanumeric relation
  in IF / WHEN / UNTIL;
* refused by name: a subscripted or numeric-edited base, signed or decimal numeric bases, a numeric receiver, any other
  statement (ADD, COMPUTE, STRING, INSPECT ...), a reference outside the item (a runtime error in Java: its meaning in
  COBOL is storage-dependent).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_REFMOD = re.compile(
    r"^\s*([A-Za-z][\w-]*)\s*\(\s*([^():]+?)\s*:\s*([^():]*?)\s*\)\s*$")

#: ``name(...:...)`` anywhere in a (masked) text
REFMOD_ANYWHERE = re.compile(r"[A-Za-z0-9][\w-]*\s*\([^()'\"]*:[^()'\"]*\)")


@dataclass(frozen=True)
class RefMod:
    name: str
    start: str
    length: str  # "" when omitted


def parse_refmod(text: str) -> RefMod | None:
    """``NAME(start:length)`` / ``NAME(start:)`` as written, or None when ``text`` is not a reference modification."""
    match = _REFMOD.match(text or "")
    if match is None:
        return None
    return RefMod(match.group(1).upper(), match.group(2).strip(), match.group(3).strip())


def split_outside_parentheses(text: str) -> list[str]:
    """Whitespace-separated words of ``text``, keeping a parenthesised group (``A(N + 1:L)``) in one piece."""
    words: list[str] = []
    depth = 0
    current: list[str] = []
    for char in text:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char.isspace() and depth <= 0:
            if current:
                words.append("".join(current))
                current = []
            continue
        current.append(char)
    if current:
        words.append("".join(current))
    return words
