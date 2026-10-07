"""Deterministic COBOL numeric VALUE / literal semantics.

This module is the single authority for turning a COBOL *numeric literal*
into the deterministic Java literal text the generator may emit.  It is a
pure, deterministic, side-effect-free contract so the transformation lane
can be tested against GnuCOBOL (oracle) and the Java candidate separately.

Contract
--------
* ``normalize_numeric_literal`` normalizes a numeric literal with no PIC
  context (expression literals such as ``MOVE 007 TO X``).  COBOL numeric
  literals are decimal: leading zeroes carry no octal meaning, so ``007``
  is ``7`` and ``009`` is ``9``.
* ``normalize_value_for_pic`` additionally applies a PIC's *storage
  contract*:
  - fractional digits are truncated (COBOL truncates, it does not round)
    to the PIC's declared decimal places;
  - integer overflow keeps the least-significant declared integer digits
    (GnuCOBOL behaviour: ``PIC 9(3) VALUE 1234`` stores ``234``);
  - the result is never an octal-looking Java literal and carries the
    exact sign of the source.
* ZERO / ZEROS / ZEROES are ``0``.
* A non-numeric VALUE on a numeric item (SPACE, LOW-VALUE, ...) raises
  :class:`NumericValueError` so the lane fails closed instead of emitting
  a bare Java identifier that only fails at compile time.

Boundary (documented, not fabricated)
-------------------------------------
* This contract covers the *storage value* of a numeric literal.  It does
  not claim byte-equal DISPLAY formatting (sign placement, overpunch) nor
  exactness of high-precision decimal arithmetic realised on IEEE-754
  ``double``; those remain PARTIAL/UNSUPPORTED until represented on a
  decimal-exact runtime type.
"""

from __future__ import annotations

import re

# numeric literal: optional sign, digits with optional fractional part.
_NUMERIC_LITERAL_RE = re.compile(r"^[+-]?(?:(?:\d+(?:\.\d*)?)|(?:\.\d+))$")

_ZERO_FIGURATIVE = frozenset({"ZERO", "ZEROS", "ZEROES"})

# Figurative constants that are invalid as the VALUE of a numeric item.
_INVALID_NUMERIC_FIGURATIVE = frozenset({
    "SPACE", "SPACES",
    "LOW-VALUE", "LOW-VALUES",
    "HIGH-VALUE", "HIGH-VALUES",
    "NULL", "NULLS",
    "QUOTE", "QUOTES",
})


class NumericValueError(ValueError):
    """Raised when a numeric literal cannot be represented deterministically.

    Treating this as a hard error keeps the lane fail-closed: an invalid
    numeric VALUE becomes a diagnosed error instead of a Java program that
    only fails (or, worse, miscompiles) later.
    """


def _strip_quotes(text: str) -> str:
    return text.strip().strip("\"'").strip()


def normalize_numeric_literal(text: str) -> str:
    """Normalize a COBOL numeric literal to safe Java literal text.

    ``007`` → ``7`` (no octal), ``009`` → ``9``, ``+12.50`` → ``12.5``.
    Raises :class:`NumericValueError` for non-numeric text.
    """
    stripped = _strip_quotes(text)
    upper = stripped.upper()
    if upper in _ZERO_FIGURATIVE:
        return "0"
    if upper in _INVALID_NUMERIC_FIGURATIVE or not _NUMERIC_LITERAL_RE.match(stripped):
        raise NumericValueError(
            f"cannot normalize non-numeric numeric literal {text!r}"
        )

    sign = ""
    body = stripped
    if body[0] in "+-":
        if body[0] == "-":
            sign = "-"
        body = body[1:]

    if "." in body:
        int_part, frac_part = body.split(".", 1)
    else:
        int_part, frac_part = body, ""

    int_part = int_part.lstrip("0") or "0"
    if not frac_part:
        return f"{sign}{int_part}"
    frac_normalized = frac_part.rstrip("0") or "0"
    return f"{sign}{int_part}.{frac_normalized}"


def normalize_value_for_pic(
    text: str,
    *,
    integer_digits: int,
    decimal_digits: int,
) -> str:
    """Normalize a numeric VALUE literal against a PIC storage contract.

    Truncates fractional digits to ``decimal_digits`` (COBOL truncation,
    not rounding) and keeps only the least-significant ``integer_digits``
    integer digits on overflow.  Returns canonical Java literal text.
    """
    normalized = normalize_numeric_literal(text)

    sign = ""
    body = normalized
    if body.startswith("-"):
        sign = "-"
        body = body[1:]

    int_part, sep, frac_part = body.partition(".")
    if not sep:
        frac_part = ""

    # COBOL truncates fractional digits beyond the picture scale.
    if len(frac_part) > decimal_digits:
        frac_part = frac_part[:decimal_digits]

    # Overflow truncates the most-significant integer digits.
    if len(int_part) > integer_digits:
        int_part = int_part[-integer_digits:]

    if decimal_digits == 0:
        return f"{sign}{int_part}"

    frac_part = frac_part.ljust(decimal_digits, "0")
    return f"{sign}{int_part}.{frac_part}"