"""COBOL sign conditions as ordinary relations.

``X IS [NOT] POSITIVE | NEGATIVE | ZERO`` tests the algebraic value of a
numeric item against zero (GnuCOBOL 3.1.2, ``tests/test_condition_operands.py``:
a negative zero stored by ``MOVE -0`` is ZERO, not NEGATIVE).  The parser
and the mapper both rewrite the condition text with :func:`rewrite_sign_conditions`
before reading it, so the IR and the Java see one relation instead of a
condition-name lookup on ``X IS NEGATIVE`` (which used to emit the
undeclared Java name ``NEGATIVE``).
"""

from __future__ import annotations

import re

#: Relations to the figurative constant ZERO (not the literal 0), so the IR
#: carries a FigurativeConstant exactly where the source names ZERO.
_RELATION = {
    ("POSITIVE", False): "> ZERO",
    ("NEGATIVE", False): "< ZERO",
    ("ZERO", False): "= ZERO",
    ("POSITIVE", True): "<= ZERO",
    ("NEGATIVE", True): ">= ZERO",
    ("ZERO", True): "NOT = ZERO",
}

#: Words that can precede POSITIVE/NEGATIVE/ZERO without being the subject
#: of a sign condition (``A = 1 OR ZERO`` is an abbreviated relation).
_NOT_A_SUBJECT = frozenset({
    "AND", "OR", "NOT", "IS", "THAN", "TO", "EQUAL", "EQUALS", "GREATER",
    "LESS", "WHEN", "UNTIL", "IF", "ALL",
})

_SIGN_CONDITION = re.compile(
    r"(?<![\w'\"-])(?P<subject>[A-Z0-9][\w-]*(?:\s*\([^()]*\))?)"
    r"\s+(?:IS\s+)?(?P<negated>NOT\s+)?(?P<sign>POSITIVE|NEGATIVE|ZERO)(?![\w-])",
    re.IGNORECASE,
)


def _mask_literals(text: str) -> str:
    return re.sub(
        r"([\"'])((?:(?!\1).)*)\1",
        lambda m: m.group(1) + "_" * len(m.group(2)) + m.group(1),
        text,
    )


def rewrite_sign_conditions(condition: str) -> str:
    """``condition`` with every sign condition replaced by its relation."""
    masked = _mask_literals(condition)
    pieces: list[str] = []
    last = 0
    for m in _SIGN_CONDITION.finditer(masked):
        subject = m.group("subject")
        if subject.split("(", 1)[0].strip().upper() in _NOT_A_SUBJECT:
            continue
        relation = _RELATION[(m.group("sign").upper(), bool(m.group("negated")))]
        pieces.append(condition[last:m.start()])
        pieces.append(f"{condition[m.start('subject'):m.end('subject')]} {relation}")
        last = m.end()
    pieces.append(condition[last:])
    return "".join(pieces)
