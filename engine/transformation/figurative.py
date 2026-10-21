"""Canonical COBOL figurative-constant semantics.

The project's required parser-coverage list includes "figurative
constants".  Before this module the parser represented them as a
:class:`~engine.transformation.ir.FieldReference` named ``ZERO`` / ``SPACES``
/ ``ALL '*'`` — i.e. it treated a reserved *word* as an undeclared Java
variable.  The mapper then emitted ``A = ZERO;`` which does not compile,
no diagnostic was produced, and the capability analyzer certified the
program ``SUPPORTED``.  That is exactly the silent semantic loss the
project forbids: presenting unproven behaviour as proven.

This module is the single source of truth for figurative constants.  The
parser, the IR, the mapper and the capability registry all read it, so a
constant cannot be understood one way in the parser and another way in the
generator.

Everything here is a deterministic table plus ordinary regular
expression tokenisation — no LLM, no model, no learned behaviour.
"""

from __future__ import annotations

import re


# ---------------------------------------------------------------------------
# Canonical kinds
# ---------------------------------------------------------------------------

#: Numeric figurative constants: every digit position is ``'0'``.
ZERO = "ZERO"

#: Alphanumeric figurative constants and the character they fill with.
#: The character is applied per collating position, so ``MOVE SPACES TO C``
#: fills the whole receiving item with spaces.
SPACES = "SPACES"
QUOTES = "QUOTES"
LOW_VALUE = "LOW-VALUE"
HIGH_VALUE = "HIGH-VALUE"

#: ``ALL "x"`` — a literal repeated across the receiver.  The repeated
#: pattern (one character or many) is carried on the constant itself; the
#: receiving context replicates it to the item's declared width.
ALL = "ALL"


#: Canonical spelling -> semantic kind.  Both singular and plural spellings
#: (and the COBOL-85 ``ZEROS``/``ZEROES`` variants) collapse onto one kind so
#: classification cannot drift between spellings.
CANONICAL_FIGURATIVES: dict[str, str] = {
    "ZERO": ZERO,
    "ZEROS": ZERO,
    "ZERO-ZERO-ZERO": ZERO,
    "ZEROES": ZERO,
    "SPACE": SPACES,
    "SPACES": SPACES,
    "QUOTE": QUOTES,
    "QUOTES": QUOTES,
    "LOW-VALUE": LOW_VALUE,
    "LOW-VALUES": LOW_VALUE,
    "HIGH-VALUE": HIGH_VALUE,
    "HIGH-VALUES": HIGH_VALUE,
}

#: The reserved figurative spellings, derived from the canonical map so the
#: two can never drift.  Exact whole-token membership is what
#: :func:`_is_reserved_figurative` needs.
_RESERVED_FIGURATIVES = frozenset(CANONICAL_FIGURATIVES)


#: Semantic kind -> the character it fills each position with.  ``ZERO`` is
#: absent because it is numeric, not a character fill; it maps to the integer
#: 0 instead (see :func:`figurative_fill_char`).
#:
#: LOW-VALUE/HIGH-VALUE use the native ASCII collating sequence (NUL and
#: 0xFF), which is what GnuCOBOL — the project's independent oracle — uses by
#: default.  A dialect with a different collating sequence would need an
#: explicit mapping, which is recorded as a limitation rather than guessed.
_FILL_CHARACTERS: dict[str, str] = {
    SPACES: " ",
    QUOTES: '"',
    LOW_VALUE: "\x00",
    HIGH_VALUE: "\xff",
}


#: ``ALL "x"`` / ``ALL "xy"`` — a literal repeated across the receiver.  The
#: repeated pattern is carried on the constant itself; a single character is
#: the common case, and a multi-character pattern is a repetition whose final
#: copy is truncated at the receiving item's width (COBOL 13.18.40.9).
_ALL_LITERAL = re.compile(
    r"""^ALL\s+(?:"(?P<dq>[^"]+)"|'(?P<sq>[^']+)')$""",
    re.IGNORECASE,
)

#: ``ALL <figurative word>`` — COBOL treats the combination as the plain
#: figurative constant (``ALL ZEROS`` is ``ZEROS``, ``ALL SPACE`` is
#: ``SPACES``).  Without this the spelling fell through to the field-
#: reference branch and its raw text leaked into generated Java.
_ALL_FIGURATIVE_WORD = re.compile(
    r"""^ALL\s+(?P<word>ZERO-ZERO-ZERO|ZEROES|ZEROS|ZERO|QUOTES|QUOTE"""
    r"""|LOW-VALUES|LOW-VALUE|HIGH-VALUES|HIGH-VALUE|SPACES|SPACE)$""",
    re.IGNORECASE,
)


def _is_reserved_figurative(token: str) -> bool:
    """True when ``token`` spells a reserved figurative constant word.

    Membership is exact: the stripped, upper-cased token must be one of the
    canonical spellings (:data:`_RESERVED_FIGURATIVES`), so a data item or
    paragraph such as ``ZERO-COUNT``, ``SPACES-AVAIL`` or ``HIGH-VALUE-FLAG``
    is never mistaken for the verb, mirroring the boundary rule already used
    by the capability source patterns.
    """
    return token.strip().upper() in _RESERVED_FIGURATIVES


def parse_figurative_constant(text: str) -> tuple[str, str | None] | None:
    """Return ``(kind, fill_character)`` for a figurative constant operand.

    ``fill_character`` is ``None`` for ``ZERO`` (numeric) and for ``ALL``
    itself is returned as the repeated character.

    Returns ``None`` when ``text`` is not a figurative constant, which lets
    callers fall through to ordinary expression parsing.  Quoted literals are
    rejected first so a field named ``ZERO`` inside a literal (``VALUE
    "ZERO"``) is never treated as the reserved word.
    """
    if text is None:
        return None
    stripped = text.strip()
    if not stripped:
        return None

    # A quoted literal is never a reserved word, even if it spells one.
    if (
        (stripped.startswith('"') and stripped.endswith('"') and len(stripped) >= 2)
        or (stripped.startswith("'") and stripped.endswith("'") and len(stripped) >= 2)
    ):
        return None

    upper = stripped.upper()
    if upper in CANONICAL_FIGURATIVES:
        return CANONICAL_FIGURATIVES[upper], None

    match = _ALL_LITERAL.match(stripped)
    if match:
        return ALL, (match.group("dq") or match.group("sq"))

    # ``ALL <figurative word>`` collapses onto the word's canonical kind:
    # COBOL treats the combination as the plain figurative constant.
    word_match = _ALL_FIGURATIVE_WORD.match(stripped)
    if word_match:
        return CANONICAL_FIGURATIVES[word_match.group("word").upper()], None

    return None


def is_figurative_constant(text: str) -> bool:
    """True when ``text`` is a reserved figurative constant word."""
    return _is_reserved_figurative(text or "")


def figurative_fill_char(kind: str) -> str | None:
    """Return the character a figurative constant fills each position with.

    Returns ``None`` for ``ZERO`` (numeric value 0) and for any unknown kind,
    so a caller can never invent a fill character.
    """
    return _FILL_CHARACTERS.get(kind)


def figurative_is_numeric(kind: str) -> bool:
    """True when the figurative constant carries a numeric value."""
    return kind == ZERO


def figurative_to_width(kind: str, fill: str | None, width: int) -> str | None:
    """Character string a figurative constant supplies for an alphanumeric
    receiving item of ``width`` characters.

    COBOL treats a figurative constant as a character string the *size of
    the receiving item* (13.18.24.3): the constant's character fills every
    position — ``MOVE ZEROS TO PIC X(5)`` stores ``00000``, not ``0`` plus
    spaces — and ``ALL <literal>`` repeats its pattern across the width,
    truncating whatever does not fit in the final copy
    (``MOVE ALL "ABC" TO PIC X(10)`` stores ``ABCABCABC``).  Both rules are
    pinned against the GnuCOBOL 3.1.2 oracle (the project's independent
    reference implementation).

    Returns ``None`` when the constant supplies no character string (an
    unknown kind, or ``ALL`` with no pattern), so a caller can never invent
    a fill.
    """
    if width is None or width <= 0:
        return None
    if kind == ALL:
        pattern = fill or ""
        if not pattern:
            return None
        return (pattern * (width // len(pattern) + 1))[:width]
    if kind == ZERO:
        # The character form of numeric zero for an alphanumeric receiver.
        return "0" * width
    char = figurative_fill_char(kind)
    if char is None:
        return None
    return char * width


__all__ = [
    "ALL",
    "CANONICAL_FIGURATIVES",
    "HIGH_VALUE",
    "LOW_VALUE",
    "QUOTES",
    "SPACES",
    "ZERO",
    "figurative_fill_char",
    "figurative_is_numeric",
    "figurative_to_width",
    "is_figurative_constant",
    "parse_figurative_constant",
]
