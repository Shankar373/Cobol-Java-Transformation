"""Canonical COBOL figurative-constant semantics.

Master README Section 16 lists "figurative constants" as required parser
coverage.  Before this module the parser represented them as a
:class:`~engine.transformation.ir.FieldReference` named ``ZERO`` / ``SPACES``
/ ``ALL '*'`` — i.e. it treated a reserved *word* as an undeclared Java
variable.  The mapper then emitted ``A = ZERO;`` which does not compile,
no diagnostic was produced, and the capability analyzer certified the
program ``SUPPORTED``.  That is exactly the silent semantic loss the
Master README forbids (Sections 14, 60, 61).

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

#: ``ALL "x"`` — a single-character figurative constant repeated across the
#: receiver.  The repeated character is carried on the constant itself.
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


#: ``ALL "x"`` — one COBOL/ASCII character.  The literal may be single- or
#: double-quoted, exactly like any other COBOL alphanumeric literal.  Only a
#: single character is a figurative constant; ``ALL "ab"`` is not.
_ALL_LITERAL = re.compile(
    r"""^ALL\s+(?:"(?P<dq>[^"]{1})"|'(?P<sq>[^']{1})')$""",
    re.IGNORECASE,
)


def _is_reserved_figurative(token: str) -> bool:
    """True when ``token`` spells a reserved figurative constant word.

    Reserved words are always full hyphen-delimited COBOL words, so the
    lookarounds refuse adjacent word characters *and* hyphens.  That keeps a
    data item or paragraph such as ``ZERO-COUNT``, ``SPACES-AVAIL`` or
    ``HIGH-VALUE-FLAG`` from being mistaken for the verb, mirroring the
    boundary rule already used by the capability source patterns.
    """
    return re.fullmatch(
        r"(?<![\w-])(ZEROES|ZEROS|ZERO-ZERO-ZERO|ZERO|SPACES|SPACE"
        r"|QUOTES|QUOTE|LOW-VALUES|LOW-VALUE|HIGH-VALUES|HIGH-VALUE)(?![\w-])",
        token.strip().upper(),
    ) is not None


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
    "is_figurative_constant",
    "parse_figurative_constant",
]