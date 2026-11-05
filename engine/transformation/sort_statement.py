"""SORT and MERGE statements: tokenising the certified file-to-file subset.

``SORT|MERGE sd {ON ASCENDING|DESCENDING KEY key...}... [WITH DUPLICATES IN ORDER] USING file... GIVING file``

Everything else is recorded as a *reason* and fails closed in the lowering: ``INPUT PROCEDURE`` /
``OUTPUT PROCEDURE``, several ``GIVING`` files, a ``MERGE`` of fewer than two files, ``COLLATING SEQUENCE``, a statement with no key,
and any text the grammar does not recognise.  ``WITH DUPLICATES IN ORDER`` is accepted because the Java sort
is stable, as GnuCOBOL's is on the fuzzed inputs (``tests/integration/test_sort_oracle.py``).
"""

from __future__ import annotations

import re

_TOKEN = re.compile(r"\"(?:[^\"]|\"\")*\"|'(?:[^']|'')*'|[^\s]+")
_WORDS = {"ON", "ASCENDING", "DESCENDING", "KEY", "WITH", "DUPLICATES", "IN", "ORDER", "USING", "GIVING",
          "INPUT", "OUTPUT", "PROCEDURE", "COLLATING", "SEQUENCE", "IS", "THRU", "THROUGH"}


def parse_sort(text: str) -> tuple[str, tuple[tuple[str, str], ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """``(sort_file, keys, using, giving, reasons)`` for one joined SORT statement."""
    tokens = _TOKEN.findall(text.strip().rstrip("."))
    reasons: list[str] = []
    merge = bool(tokens) and tokens[0].upper() == "MERGE"
    if tokens and tokens[0].upper() in ("SORT", "MERGE"):
        tokens = tokens[1:]
    if not tokens:
        return "", (), (), (), ("EMPTY",)
    sort_file = tokens[0]
    upper = [t.upper() for t in tokens]
    keys: list[tuple[str, str]] = []
    using: list[str] = []
    giving: list[str] = []
    pos = 1
    direction = ""
    while pos < len(tokens):
        word = upper[pos]
        if word == "ON":
            pos += 1
            continue
        if word in ("ASCENDING", "DESCENDING"):
            direction = word
            pos += 1
            if pos < len(tokens) and upper[pos] == "KEY":
                pos += 1
            while pos < len(tokens) and upper[pos] not in _WORDS:
                keys.append((tokens[pos], direction))
                pos += 1
            continue
        if word == "WITH" and upper[pos:pos + 4] == ["WITH", "DUPLICATES", "IN", "ORDER"]:
            pos += 4
            continue
        if word in ("USING", "GIVING"):
            pos += 1
            target = using if word == "USING" else giving
            while pos < len(tokens) and upper[pos] not in _WORDS:
                target.append(tokens[pos])
                pos += 1
            continue
        if word in ("INPUT", "OUTPUT"):
            reasons.append(f"{word}_PROCEDURE")
            break
        if word == "COLLATING":
            reasons.append("COLLATING")
            break
        reasons.append("CLAUSE_" + re.sub(r"[^A-Z0-9]", "_", word))
        break
    if not keys:
        reasons.append("NO_KEYS")
    if not using and "INPUT_PROCEDURE" not in reasons:
        reasons.append("USING_COUNT")
    if merge and 0 < len(using) < 2:
        reasons.append("MERGE_NEEDS_TWO_FILES")
    if len(giving) != 1 and "OUTPUT_PROCEDURE" not in reasons:
        reasons.append("GIVING_COUNT")
    return sort_file, tuple(keys), tuple(using), tuple(giving), tuple(dict.fromkeys(reasons))
