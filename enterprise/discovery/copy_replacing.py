"""The one ``COPY ... REPLACING`` grammar (layer 4, acceptance criterion 8).

Discovery records what an estate contains; the engine materialises what a
program copies in.  The two faces used to parse the clause independently and
disagreed: discovery recorded literal and sign-prefixed operands the engine
refuses, under a different code name.  This module is the only place the
clause grammar lives:

* :func:`parse_clause` — the canonical parser over a statement's text.  The
  engine's materialisation, the capability analyzer and the FD-copybook lane
  all reach it through ``copybook_model._parse_replacing_clause``;
* :func:`parse_tokens` — the discovery face: a token stream is rendered back
  to clause text by :func:`clause_text` and read by :func:`parse_clause`
  itself, so the two faces cannot drift.  ``tests/discovery/
  test_replacing_parity.py`` proves the agreement over a fixture matrix.

Supported operand forms: pseudo-text ``==...==`` pairs (possibly multi-line)
and COBOL-word operands, multiple pairs.  Refused by name under
``COPYBOOK_REPLACING_UNSUPPORTED``: the ``LEADING``/``TRAILING``/``PARTIAL``
phrases, ``+``/``-`` prefixed operands and quoted literals — a pattern that
lives inside quotes can never be matched safely by the unquoted-text
substitution, so it is never applied.  A clause that does not parse fails
under ``COPYBOOK_REPLACING_MALFORMED``.  Discovery's scanner reports exactly
these two codes, so a literal-operand ``COPY`` is refused the same way from
discovery and from generation.  The parser stops at the first refusal: pairs
completed before it are kept, a partial application never proceeds.

Deterministic and dependency-free; no LLM, no I/O.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .cobol_text import Token

#: Refusal code for a recognised operand form neither face applies.
UNSUPPORTED = "COPYBOOK_REPLACING_UNSUPPORTED"
#: Refusal code for a clause that does not parse.
MALFORMED = "COPYBOOK_REPLACING_MALFORMED"

#: ``COPY ... REPLACING`` forms this grammar understands: the plain ``BY`` pairing.
SUPPORTED_REPLACING_FORMS = ("BY",)
#: IBM/enterprise phrase forms recognised only to fail closed by name.
PHRASE_REPLACING_FORMS = ("LEADING", "TRAILING", "PARTIAL")
#: Every operand form refused by name (phrases, quoted literals, signed operands).
UNSUPPORTED_REPLACING_FORMS = PHRASE_REPLACING_FORMS + ("LITERAL", "SIGN-PREFIXED")
#: Named conditions behind a ``MALFORMED`` refusal: diagnostic detail for the
#: discovery face, never a verdict on their own — the code is the verdict.
MALFORMED_REPLACING_FORMS = (
    "UNPAIRED-PSEUDO-TEXT",
    "UNTERMINATED-PSEUDO-TEXT",
    "EMPTY-PSEUDO-TEXT",
    "UNEXPECTED-TOKEN",
    "MISSING-BY",
    "NO-PAIRS",
)

_REPLACING_KEYWORD = re.compile(r"\bREPLACING\b", re.IGNORECASE)
_BY_KEYWORD = re.compile(r"\bBY\b", re.IGNORECASE)
_COBOL_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")


@dataclass(frozen=True)
class ReplacingClause:
    """One clause's verdict: the pairs read before a refusal, and the refusal.

    ``pairs`` holds every pair completed before ``error`` — the caller decides
    what a refusal means for it (generation fails closed, discovery records
    and names the problem); ``error`` is ``None`` only for a clause that
    parsed completely.  ``form`` names the form/condition behind ``error`` for
    diagnostics; the code in ``error`` is the verdict.
    """

    pairs: tuple[tuple[str, str], ...]
    error: tuple[str, str] | None = None
    form: str | None = None


def has_replacing(source: str) -> bool:
    """True when ``source`` mentions ``REPLACING`` (cheap pre-check, no parse)."""
    return _REPLACING_KEYWORD.search(source) is not None


def parse_clause(stmt: str) -> ReplacingClause:
    """Parse the REPLACING clause of one COPY statement — the one grammar.

    Returns an empty, error-free clause when the statement has no
    ``REPLACING``.  Supported: pseudo-text ``==...==`` operands (possibly
    multi-line) and COBOL-word operands, multiple pairs.  Refused by name
    under :data:`UNSUPPORTED`: ``LEADING``/``TRAILING``/``PARTIAL`` phrases,
    ``+``/``-`` prefixed operands and quoted literals.  Everything else that
    does not parse fails under :data:`MALFORMED`, with the message naming
    ``REPLACING``.  Fails closed on the first refusal; pairs completed before
    it are kept.
    """
    match = _REPLACING_KEYWORD.search(stmt)
    if not match:
        return ReplacingClause(())
    body = stmt.rstrip()
    if body.endswith("."):
        body = body[:-1]
    length = len(body)
    pos = match.end()
    pairs: list[tuple[str, str]] = []

    def _skip_ws(i: int) -> int:
        while i < length and body[i] in " \t\r\n":
            i += 1
        return i

    def _read_operand(i: int) -> tuple[str | None, int, tuple[str, str, str] | None]:
        """``(operand, next_index, failure)``; failure is ``(code, message, form)``."""
        if i >= length:
            return None, i, (
                MALFORMED,
                "REPLACING clause ended where an operand was expected",
                "UNPAIRED-PSEUDO-TEXT",
            )
        ch = body[i]
        if ch in "+-":
            return None, i, (
                UNSUPPORTED,
                f"REPLACING prefixed operand {ch!r} is not applied",
                "SIGN-PREFIXED",
            )
        if ch in "'\"":
            return None, i, (
                UNSUPPORTED,
                "REPLACING literal (quoted) operand is not applied",
                "LITERAL",
            )
        if body.startswith("==", i):
            end = body.find("==", i + 2)
            if end < 0:
                return None, i, (
                    MALFORMED,
                    "REPLACING pseudo-text operand is not terminated by ==",
                    "UNTERMINATED-PSEUDO-TEXT",
                )
            operand = body[i + 2 : end].strip()
            if not operand:
                return None, i, (
                    MALFORMED,
                    "REPLACING pseudo-text operand is empty",
                    "EMPTY-PSEUDO-TEXT",
                )
            return operand, end + 2, None
        word_match = _COBOL_WORD.match(body, i)
        if not word_match:
            return None, i, (
                MALFORMED,
                f"REPLACING clause has an unexpected token {body[i:i + 12]!r}",
                "UNEXPECTED-TOKEN",
            )
        word = word_match.group(0)
        if word.upper() in PHRASE_REPLACING_FORMS:
            return None, i, (
                UNSUPPORTED,
                f"REPLACING {word.upper()} phrase is not applied",
                word.upper(),
            )
        return word, word_match.end(), None

    while True:
        pos = _skip_ws(pos)
        if pos >= length:
            break
        left, pos, failure = _read_operand(pos)
        if failure:
            return ReplacingClause(tuple(pairs), failure[:2], failure[2])
        pos = _skip_ws(pos)
        by_match = _BY_KEYWORD.match(body, pos)
        if not by_match:
            return ReplacingClause(
                tuple(pairs),
                (MALFORMED, "REPLACING clause is missing the BY keyword between operands"),
                "MISSING-BY",
            )
        pos = _skip_ws(by_match.end())
        right, pos, failure = _read_operand(pos)
        if failure:
            return ReplacingClause(tuple(pairs), failure[:2], failure[2])
        # ``_read_operand`` reports a refusal instead of an operand, so both are
        # present here; the assert keeps that pairing visible to the type checker.
        assert left is not None and right is not None, "operand without a refusal"
        pairs.append((left, right))
    if not pairs:
        return ReplacingClause(
            (),
            (MALFORMED, "REPLACING clause contains no operand pairs"),
            "NO-PAIRS",
        )
    return ReplacingClause(tuple(pairs))


def clause_text(tokens: list[Token], start: int, end: int) -> str:
    """The statement's text as written, rebuilt from ``tokens[start:end]``.

    The tokenizer strips pseudo-text's ``==`` delimiters and a literal's
    quotes; both are put back here so the rebuilt text reads like the source
    clause to :func:`parse_clause`.  One space separates every token: the
    grammar skips whitespace uniformly, and no operand may contain one
    (pseudo-text keeps its inner blanks, delimited by ``==``).
    """
    parts: list[str] = []
    for token in tokens[start:end]:
        if token.kind == "pseudo":
            parts.append(f"=={token.text}==")
        elif token.kind == "literal":
            text = token.text
            parts.append(text if text[:1] in ("'", '"') else f"'{text}'")
        else:
            parts.append(token.text)
    return " ".join(parts)


def parse_tokens(tokens: list[Token], start: int, end: int) -> ReplacingClause:
    """The discovery face: the very same grammar over a token stream."""
    return parse_clause(clause_text(tokens, start, end))
