"""Run-unit control flow shared by the parser checks and the Java lowering.

COBOL executes the procedure division paragraph after paragraph: a
paragraph that does not end the run falls through into the next one.  The
Java lowering reproduces exactly that, and only that, for the provable
subset:

* ``main`` runs the driver (first) paragraph, then calls each following
  paragraph in source order until one whose top-level statements contain
  STOP RUN or GOBACK (the *fall-through chain*);
* a STOP RUN / GOBACK outside the driver is faithful only as the **last
  top-level statement of the chain's final paragraph**, and only when no
  PERFORM ever reaches that paragraph (a PERFORMed STOP RUN would just
  return from the paragraph method).  Everything else stays fail closed.

EXIT PROGRAM in a program that was not CALLed has no effect (oracle:
GnuCOBOL 3.1.2 continues with the next statement), so it never ends the
chain.
"""

from __future__ import annotations

import re

from engine.transformation.ir import (
    GobackStatement,
    Paragraph,
    PerformStatement,
    PerformTimesStatement,
    StopRunStatement,
)

#: Statements that end the run unit when executed by the main program.
RUN_UNIT_TERMINATORS = (StopRunStatement, GobackStatement)

_THRU = re.compile(r"\bTHR(?:OUGH|U)\s+([A-Z0-9][\w-]*)", re.IGNORECASE)


def ends_run_unit(paragraph: Paragraph) -> bool:
    """True when a top-level statement of ``paragraph`` ends the run unit."""
    return any(isinstance(s, RUN_UNIT_TERMINATORS) for s in paragraph.statements)


def fall_through_chain(paragraphs) -> tuple[Paragraph, ...]:
    """Paragraphs executed in order from the driver until one ends the run."""
    chain: list[Paragraph] = []
    for paragraph in paragraphs:
        chain.append(paragraph)
        if ends_run_unit(paragraph):
            break
    return tuple(chain)


def walk_statements(statements):
    """Yield every statement in a body, recursing into all nested bodies."""
    for stmt in statements:
        yield stmt
        for value in getattr(stmt, "__dict__", {}).values():
            if isinstance(value, (tuple, list)):
                nested = [v for v in value if hasattr(v, "__dataclass_fields__")]
                if nested:
                    yield from walk_statements(nested)


def performed_paragraphs(paragraphs) -> frozenset[str]:
    """Upper-case names of every paragraph some PERFORM can execute.

    THRU ranges are expanded in source order; an endpoint the program does
    not define contributes only the named paragraph.  Any ``THRU <name>``
    text left in a statement field also counts, so the set errs on the side
    of reporting a paragraph as performed.
    """
    names = [p.name.upper() for p in paragraphs]
    performed: set[str] = set()
    for paragraph in paragraphs:
        for stmt in walk_statements(paragraph.statements):
            if not isinstance(stmt, (PerformStatement, PerformTimesStatement)):
                continue
            first = (stmt.paragraph_name or "").strip().upper()
            if not first:
                continue
            lasts = {(getattr(stmt, "thru_target", None) or "").strip().upper()}
            for value in vars(stmt).values():
                if isinstance(value, str):
                    lasts.update(m.upper() for m in _THRU.findall(value))
            lasts.discard("")
            performed.add(first)
            for last in lasts:
                if first in names and last in names:
                    lo, hi = names.index(first), names.index(last)
                    performed.update(names[lo:hi + 1])
                performed.add(last)
    return frozenset(performed)
