"""Numeric-edited PICTURE clauses: the certified subset.

``parse_numeric_edited`` accepts exactly the pictures whose MOVE-from-number
behaviour is pinned against GnuCOBOL 3.1.2 by the seeded fuzz in
``tests/integration/test_numeric_edited_oracle.py`` (random pictures x values
x sender formats, ~11,000 cases in the development runs, all byte-identical).
Anything else that uses editing symbols is refused with a reason (the
parser reports it as UNSUPPORTED_CONSTRUCT) instead of being guessed.

Certified shape of an expanded picture (``Z(5)`` -> ``ZZZZZ``)::

    [lead] integer-digits [(. | V) 9+] [trail]

- ``lead``: nothing; one fixed ``$`` / ``+`` / ``-``; or a floating string of
  two or more of the same ``$`` / ``+`` / ``-`` (``,`` may sit inside it).
- ``integer-digits``: ``Z`` or ``*`` positions (not both) followed by ``9``
  positions - after a floating string only ``9`` - with the insertion
  characters ``,`` ``B`` ``0`` ``/`` between two digit positions.
- ``trail``: nothing, ``+``, ``-``, ``CR`` or ``DB``; not combined with a
  leading ``+`` / ``-``.

A picture with no editing symbol (``9(5)V99``, ``S9(3)``) is not
numeric-edited and returns ``None``; alphanumeric-edited pictures
(``XXBXX``) also return ``None`` and keep their existing treatment.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Symbols whose presence makes a numeric picture an edited one.
_EDIT_SYMBOLS = set("Z*B0/,.+-$")
#: Letters that mark a picture as alphanumeric / national: not our domain.
_NON_NUMERIC_LETTERS = set("XANEG")
_MAX_EXPANDED = 64

_REPEAT = re.compile(r"(.)\((\d+)\)")
_DIGITS = re.compile(r"^(?:Z+|\*+)?9*$")
_INSERT = ",B0/"


class UnsupportedEditedPicture(ValueError):
    """An editing picture outside the certified subset (message = reason)."""


@dataclass(frozen=True)
class EditedPicture:
    picture: str  # as written, upper case
    expanded: str  # repeat counts expanded
    width: int  # characters of the edited item
    suppress: str  # "Z", "*" or ""
    floating: str  # "$", "+", "-" or "" (leading floating string)
    trailing: str  # "", "+", "-", "CR", "DB"

    @property
    def has_star(self) -> bool:
        return "*" in self.expanded


def expand_picture(picture: str) -> str:
    """``Z(3)9`` -> ``ZZZ9`` (a count above the size cap is left unexpanded)."""

    def repeat(match: re.Match[str]) -> str:
        count = int(match.group(2))
        return match.group(1) * count if 0 < count <= _MAX_EXPANDED else match.group(0)

    return _REPEAT.sub(repeat, picture)


def parse_numeric_edited(picture: str) -> EditedPicture | None:
    """The certified numeric-edited picture, or ``None`` if it is not one.

    Raises :class:`UnsupportedEditedPicture` when the picture uses editing
    symbols but falls outside the certified subset.
    """
    written = picture.strip().rstrip(".").upper()
    expanded = expand_picture(written)
    if not expanded or any(c in _NON_NUMERIC_LETTERS for c in expanded):
        return None
    symbols = set(expanded)
    has_cr_db = expanded.endswith(("CR", "DB"))
    if not has_cr_db and not (symbols & _EDIT_SYMBOLS):
        return None
    if len(expanded) > _MAX_EXPANDED:
        raise UnsupportedEditedPicture("picture is longer than 64 positions")
    if "S" in symbols or "P" in symbols:
        raise UnsupportedEditedPicture("S / P with editing symbols has no certified lowering")

    body, trailing = expanded, ""
    for tail in ("CR", "DB"):
        if body.endswith(tail):
            body, trailing = body[: -len(tail)], tail
            break
    else:
        if body[-1] in "+-" and len(body) > 1:
            body, trailing = body[:-1], body[-1]

    if set(body) - set("9Z*B0/,.V$+-"):
        raise UnsupportedEditedPicture("unrecognised symbol in the picture")

    point = [i for i, c in enumerate(body) if c in ".V"]
    if len(point) > 1:
        raise UnsupportedEditedPicture("more than one decimal point")
    integer, fraction = body, ""
    if point:
        integer, fraction = body[: point[0]], body[point[0] + 1:]
        if not re.fullmatch(r"9+", fraction):
            raise UnsupportedEditedPicture(
                "only 9 positions are certified after the decimal point"
            )

    floating, fixed = "", ""
    if integer and integer[0] in "$+-":
        lead = integer[0]
        run = re.match(rf"^(?:{re.escape(lead)},?)+", integer)
        text = run.group(0) if run else lead
        if text.endswith(","):
            raise UnsupportedEditedPicture("floating string ends with an insertion character")
        symbol_count = text.count(lead)
        if symbol_count >= 2:
            floating = lead
        else:
            fixed = lead
        integer = integer[len(text):]
    if "$" in integer or "+" in integer or "-" in integer:
        raise UnsupportedEditedPicture(
            "a second currency or sign symbol is not certified"
        )
    if (floating or fixed) in ("+", "-") and trailing:
        raise UnsupportedEditedPicture("a leading and a trailing sign are not certified")

    digits = "".join(c for c in integer if c not in _INSERT)
    if not digits:
        raise UnsupportedEditedPicture("an integer digit position is required")
    if not _DIGITS.fullmatch(digits):
        raise UnsupportedEditedPicture(
            "digit positions must be Z (or *) positions followed by 9 positions"
        )
    if floating and set(digits) != {"9"}:
        raise UnsupportedEditedPicture("Z / * cannot follow a floating string")
    if integer[0] in _INSERT or integer[-1] in _INSERT:
        raise UnsupportedEditedPicture("an insertion character must sit between digit positions")
    if re.search(r"[,B0/]{2}", integer):
        raise UnsupportedEditedPicture("adjacent insertion characters are not certified")

    suppress = "Z" if "Z" in digits else "*" if "*" in digits else ""
    width = len(expanded) - expanded.count("V")
    return EditedPicture(
        picture=written,
        expanded=expanded,
        width=width,
        suppress=suppress,
        floating=floating,
        trailing=trailing,
    )
