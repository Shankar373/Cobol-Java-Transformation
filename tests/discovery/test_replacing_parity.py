"""REPLACING parity: one grammar, two faces (layer 4, acceptance criterion 8).

Discovery records what an estate contains; generation materialises what a
program copies in.  Criterion 8 requires identical supported/refused forms on
both sides, and a literal-operand COPY produces the same named refusal code
from discovery and from generation.

The structural reason the two faces cannot drift: discovery's token face
(``copy_replacing.parse_tokens``) renders the statement back to clause text
and runs the very parser generation runs
(``copybook_model._parse_replacing_clause``).  This fixture matrix proves the
agreement over every supported and refused form — verdict, pairs and the
problem code the scanner reports — rather than trusting the wiring by
documentation.
"""

from __future__ import annotations

import pytest

from enterprise.discovery import copy_replacing
from enterprise.discovery.cobol_text import logical_lines, tokenize
from enterprise.discovery.scan_cobol import scan_cobol
from engine.transformation.copybook_model import _parse_replacing_clause
from tests.discovery.helpers import _fixed

#: ``(statement, pairs)`` — forms both faces apply.
SUPPORTED = [
    ("COPY T REPLACING ==A== BY ==B==.", [("A", "B")]),
    ("COPY T REPLACING WS-OLD BY WS-NEW.", [("WS-OLD", "WS-NEW")]),
    ("COPY T REPLACING ==A== BY ==B== C BY D.", [("A", "B"), ("C", "D")]),
    ("COPY T REPLACING ==A B== BY ==C D==.", [("A B", "C D")]),
]

#: ``(statement, refusal code)`` — forms both faces refuse, by name.
REFUSED = [
    # recognised operand forms neither face applies
    ("COPY T REPLACING LEADING ==A== BY ==B==.", "COPYBOOK_REPLACING_UNSUPPORTED"),
    ("COPY T REPLACING TRAILING ==A== BY ==B==.", "COPYBOOK_REPLACING_UNSUPPORTED"),
    ("COPY T REPLACING PARTIAL ==A== BY ==B==.", "COPYBOOK_REPLACING_UNSUPPORTED"),
    ("COPY T REPLACING 'X' BY 'Y'.", "COPYBOOK_REPLACING_UNSUPPORTED"),
    ("COPY T REPLACING +5 BY 6.", "COPYBOOK_REPLACING_UNSUPPORTED"),
    # clauses that do not parse
    ("COPY T REPLACING ==A== BY.", "COPYBOOK_REPLACING_MALFORMED"),
    ("COPY T REPLACING ==A== ==B==.", "COPYBOOK_REPLACING_MALFORMED"),
    ("COPY T REPLACING.", "COPYBOOK_REPLACING_MALFORMED"),
    ("COPY T REPLACING ==A BY ==B==.", "COPYBOOK_REPLACING_MALFORMED"),
    # a refusal after a completed pair keeps that pair on both faces
    ("COPY T REPLACING ==A== BY ==B== LEADING ==C== BY ==D==.", "COPYBOOK_REPLACING_UNSUPPORTED"),
]


def _generation_face(stmt: str) -> tuple[list[tuple[str, str]], tuple[str, str] | None]:
    """What generation reads: the engine's materialisation face."""
    return _parse_replacing_clause(stmt)


def _discovery_face(stmt: str) -> tuple[list[tuple[str, str]], tuple[str, str] | None]:
    """What discovery reads: tokens rendered back to text by the shared grammar."""
    lines = logical_lines(stmt)[1]
    tokens = tokenize(lines)
    clause = copy_replacing.parse_tokens(tokens, 0, len(tokens))
    return list(clause.pairs), clause.error


def _scan_codes(stmt: str) -> list[str]:
    """The problem codes the discovery scanner reports for the statement."""
    scan = scan_cobol("p.cbl", _fixed("PROGRAM-ID. P.", f"    {stmt}"))
    return [p.code for p in scan.problems]


@pytest.mark.parametrize("stmt,pairs", SUPPORTED)
def test_supported_forms_agree_on_both_faces(stmt: str, pairs: list[tuple[str, str]]) -> None:
    assert _generation_face(stmt) == (pairs, None)
    assert _discovery_face(stmt) == (pairs, None)
    assert _scan_codes(stmt) == []


@pytest.mark.parametrize("stmt,code", REFUSED)
def test_refused_forms_agree_on_both_faces(stmt: str, code: str) -> None:
    gen_pairs, gen_error = _generation_face(stmt)
    dis_pairs, dis_error = _discovery_face(stmt)
    # same verdict, same pairs read before the refusal
    assert gen_error is not None and gen_error == dis_error
    assert gen_error[0] == code
    assert dis_pairs == gen_pairs
    # criterion 8: the scanner reports the same named refusal code generation does
    assert _scan_codes(stmt) == [code]


def test_pairs_completed_before_a_refusal_are_kept_identically() -> None:
    """A partial clause never proceeds on either face: the pair is kept, the refusal stands."""
    stmt = "COPY T REPLACING ==A== BY ==B== LEADING ==C== BY ==D==."
    gen_pairs, gen_error = _generation_face(stmt)
    dis_pairs, dis_error = _discovery_face(stmt)
    assert gen_pairs == dis_pairs == [("A", "B")]
    assert gen_error is not None and gen_error == dis_error
    assert gen_error[0] == "COPYBOOK_REPLACING_UNSUPPORTED"
