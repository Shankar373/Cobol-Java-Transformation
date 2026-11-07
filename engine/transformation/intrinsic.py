"""Certified intrinsic functions: ``FUNCTION UPPER-CASE / LOWER-CASE / REVERSE / TRIM / LENGTH (argument)``.

Certified only as a DISPLAY operand or a MOVE sender, and only on an argument whose value the lowering knows exactly: a
quoted literal, a plain alphanumeric DISPLAY item or a reference modification of one. Every other function, argument
form or context keeps failing closed (the parser names it and the mapper emits an undefined symbol), so no function
result is ever invented. Behaviour pinned by the GnuCOBOL 3.1.2 differential ``tests/integration/test_intrinsic_oracle.py``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

FUNCTION_CALL = re.compile(r"^FUNCTION\s+([A-Z][A-Z0-9-]*)\s*\((.*)\)$", re.IGNORECASE | re.DOTALL)
# one ``FUNCTION NAME(arg)`` operand inside a DISPLAY operand list (one level of nested parentheses: a refmod)
FUNCTION_OPERAND = r"FUNCTION\s+[A-Z][A-Z0-9-]*\s*\((?:[^()]|\([^()]*\))*\)"

STRING_FUNCTIONS = frozenset({"UPPER-CASE", "LOWER-CASE", "REVERSE", "TRIM"})
CERTIFIED_FUNCTIONS = STRING_FUNCTIONS | {"LENGTH"}


@dataclass(frozen=True)
class FunctionCall:
    name: str
    argument: str  # the argument text (without a TRIM LEADING / TRAILING keyword)
    trim: str = "BOTH"  # TRIM only: BOTH, LEADING or TRAILING


def parse_function(text: str) -> FunctionCall | None:
    """The certified function call that ``text`` is, or ``None`` (a different function, other text, a bad shape)."""
    found = FUNCTION_CALL.match((text or "").strip())
    if found is None:
        return None
    name = found.group(1).upper()
    argument = found.group(2).strip()
    if name not in CERTIFIED_FUNCTIONS or not argument or "," in argument.replace("','", "").replace("', '", ""):
        return None
    trim = "BOTH"
    if name == "TRIM":
        tail = re.search(r"\s+(LEADING|TRAILING)$", argument, re.IGNORECASE)
        if tail is not None:
            trim = tail.group(1).upper()
            argument = argument[: tail.start()].strip()
    return FunctionCall(name=name, argument=argument, trim=trim)
