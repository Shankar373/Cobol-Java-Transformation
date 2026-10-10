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
    exact sign of the source;
  - an explicitly signed literal is rejected on an unsigned PIC
    (GnuCOBOL rejects it too: ``error: data item not signed``), so the
    lane fails closed instead of silently storing a magnitude the oracle
    would not accept.
* ZERO / ZEROS / ZEROES are ``0``.
* A non-numeric VALUE on a numeric item (SPACE, LOW-VALUE, ...) raises
  :class:`NumericValueError` so the lane fails closed instead of emitting
  a bare Java identifier that only fails at compile time.
* :func:`display_format_spec` is the deterministic ``String.format``
  specifier that reproduces the *text* GnuCOBOL writes for a numeric
  ``DISPLAY`` item: the whole digit field, zero-filled, with a leading
  ``+``/``-`` column for signed items.
* :func:`java_integral_suffix` returns ``L`` when an integral literal
  falls outside Java's default ``int`` range, so generated source compiles
  instead of failing with ``error: integer number too large``.

Boundary (documented, not fabricated)
-------------------------------------
* This contract covers the *storage value* of a numeric literal and the
  ``DISPLAY`` *text* of an INTEGER/DECIMAL DISPLAY item.  It does not claim
  the record-area byte encoding (COMP/COMP-3 packed/binary representation,
  sign overpunch) nor exactness of high-precision decimal arithmetic
  realised on IEEE-754 ``double``; those remain PARTIAL/UNSUPPORTED until
  represented on a decimal-exact runtime type.
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


def is_numeric_literal(text: str) -> bool:
    """Return ``True`` when ``text`` is a plain COBOL numeric literal spelling.

    Unlike a plain ``str.isdigit`` test this accepts the optional COBOL
    sign (``+12``, ``-12``) and the fractional forms (``1.2``, ``.5``,
    ``12.``), so callers never mistake a signed/out-of-range literal for a
    field reference.
    """
    return bool(_NUMERIC_LITERAL_RE.match(text))


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
    signed: bool = False,
) -> str:
    """Normalize a numeric VALUE literal against a PIC storage contract.

    Truncates fractional digits to ``decimal_digits`` (COBOL truncation,
    not rounding) and keeps only the least-significant ``integer_digits``
    integer digits on overflow.  Returns canonical Java literal text.

    ``signed`` must be the PIC's sign declaration.  An explicitly signed
    literal on an unsigned PIC raises :class:`NumericValueError` — GnuCOBOL
    rejects the same program with ``error: data item not signed``, so
    accepting it would store a magnitude the oracle never stores.
    """
    stripped = _strip_quotes(text)
    if stripped[:1] in "+-" and _NUMERIC_LITERAL_RE.match(stripped) and not signed:
        raise NumericValueError(
            f"signed numeric literal {text!r} cannot be the VALUE of an "
            f"unsigned PIC (GnuCOBOL: data item not signed)"
        )

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


# Java's default type for an integer literal without a suffix is int.
_JAVA_INT_MAX = 2_147_483_647
_JAVA_INT_MIN = -2_147_483_648


def java_integral_suffix(canonical: str) -> str:
    """Return ``"L"`` when an integral literal falls outside Java's ``int``.

    Java requires an ``L`` suffix for any integer literal outside the
    ``int`` range; without it the compiler reports
    ``error: integer number too large`` even when the target variable is a
    ``long``.  Fractional literals are already ``double`` and never need a
    suffix.

    >>> java_integral_suffix("7")
    ''
    >>> java_integral_suffix("12345678901")
    'L'
    >>> java_integral_suffix("123.45")
    ''
    """
    body = canonical
    sign = ""
    if body[:1] in "+-":
        sign, body = body[0], body[1:]
    if "." in body:
        return ""
    try:
        value = int(body)
    except ValueError:
        return ""
    if sign == "-":
        value = -value
    return "L" if value > _JAVA_INT_MAX or value < _JAVA_INT_MIN else ""


def display_format_spec(
    *,
    integer_digits: int,
    decimal_digits: int,
    signed: bool,
) -> str:
    """Return the Java ``String.format`` specifier for a numeric ``DISPLAY``.

    GnuCOBOL writes the whole digit field of a numeric item: unsigned
    items are zero-filled to their declared integer digits, signed items
    carry a leading ``+``/``-`` column and therefore occupy one column
    more, and fractional items always print ``.`` plus exactly
    ``decimal_digits`` fractions.

    Oracle (GnuCOBOL ``DISPLAY``) examples::

        PIC 9(3)     value 7      -> %03d     -> 007
        PIC S9(4)    value -12    -> %+05d    -> -0012
        PIC S9(4)    value 12     -> %+05d    -> +0012
        PIC 9(4)V99  value 12.5   -> %07.2f   -> 0012.50
        PIC S9(3)V9  value -1.29  -> %+06.1f  -> -001.2

    The specifier is locale-independent for the integer conversions;
    callers must pass ``java.util.Locale.US`` as the first argument of
    ``String.format`` for the ``f`` conversions, otherwise the platform
    locale can substitute its own decimal separator.
    """
    if integer_digits < 0 or decimal_digits < 0:
        raise ValueError("integer_digits and decimal_digits must be >= 0")
    if integer_digits == 0 and decimal_digits == 0:
        raise ValueError("a numeric format spec needs at least one digit position")

    sign_columns = 1 if signed else 0
    if decimal_digits == 0:
        width = integer_digits + sign_columns
        return f"%+0{width}d" if signed else f"%0{width}d"

    width = integer_digits + decimal_digits + 1 + sign_columns
    flag = "+" if signed else ""
    return f"%{flag}0{width}.{decimal_digits}f"


def is_fractional_format_spec(spec: str) -> bool:
    """Return ``True`` when ``spec`` is a floating-point conversion.

    Only those conversions honour the platform locale in
    ``String.format``, so they are the ones that need an explicit
    ``java.util.Locale.US``.
    """
    return spec.rstrip().endswith("f")
