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
    StopRunStatement,
)

#: Statements that end the run unit when executed by the main program.
RUN_UNIT_TERMINATORS = (StopRunStatement, GobackStatement)

#: Static method that runs a program as the entry of a run unit (driver
#: paragraph, then its fall-through chain) for hosts that do not call
#: ``main`` (the Spring Boot runner).  ``$`` cannot occur in a COBOL
#: paragraph name, so it never collides with a paragraph method.
RUN_UNIT_ENTRY_METHOD = "RUN_UNIT$ENTRY"

#: Static method returning the run unit's process exit status
#: (``RETURN-CODE & 0xFF``), generated only for a program that uses the
#: RETURN-CODE register.  Every host (``main``, the Spring Boot runner)
#: exits with it after the run-unit entry returns; a program without it
#: exits 0, as before.
RUN_UNIT_EXIT_STATUS_METHOD = "RUN_UNIT$EXIT_STATUS"

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
            if not isinstance(stmt, PerformStatement):
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


def goto_plan_reasons(paragraphs, has_linkage: bool = False) -> list[str]:
    """Why ``GO TO`` cannot be lowered for this program (empty list: certified, or no GO TO at all).

    The certified subset (proven against GnuCOBOL in ``tests/integration/test_goto_oracle.py``): ``GO TO name`` with a
    defined paragraph, in a program without a LINKAGE section or EXIT PROGRAM; the paragraphs that contain a GO TO are
    run by a scheduler, either as the run unit or as a plain ``PERFORM first THRU last`` range, and every GO TO inside
    such a range lands inside it (a jump out of a PERFORM range does not return to the PERFORM, which Java cannot
    reproduce with calls). A paragraph that contains a GO TO may not be PERFORMed by a simple, TIMES, UNTIL or VARYING
    PERFORM, because the range would be a single paragraph or looped.
    """
    from engine.transformation.ir import ExitProgramStatement, GoToStatement

    names = [p.name.upper() for p in paragraphs]
    gotos: dict[int, list[GoToStatement]] = {}
    for index, paragraph in enumerate(paragraphs):
        found = [s for s in walk_statements(paragraph.statements) if isinstance(s, GoToStatement)]
        if found:
            gotos[index] = found
    if not gotos:
        return []
    reasons: list[str] = []
    if has_linkage:
        reasons.append("LINKAGE")
    for paragraph in paragraphs:
        if any(isinstance(s, ExitProgramStatement) for s in walk_statements(paragraph.statements)):
            reasons.append("EXIT_PROGRAM")
            break
    for index, found in gotos.items():
        for stmt in found:
            target = (stmt.target or "").strip().upper()
            if not target:
                reasons.append("FORM")
            elif target not in names:
                reasons.append("TARGET")
    for paragraph in paragraphs:
        for stmt in walk_statements(paragraph.statements):
            if not isinstance(stmt, PerformStatement):
                continue
            first = (stmt.paragraph_name or "").strip().upper()
            if not first or first not in names:
                continue
            last = (stmt.thru_target or "").strip().upper() or first
            if last not in names:
                continue
            lo, hi = names.index(first), names.index(last)
            inside = [i for i in gotos if lo <= i <= hi]
            if not inside:
                continue
            plain = stmt.until_condition is None and not stmt.body and bool(stmt.thru_target)
            if not plain:
                reasons.append("PERFORM_FORM")
                continue
            for i in inside:
                for goto in gotos[i]:
                    target = (goto.target or "").strip().upper()
                    if target in names and not lo <= names.index(target) <= hi:
                        reasons.append("RANGE")
    return list(dict.fromkeys(reasons))


def has_goto(paragraphs) -> bool:
    from engine.transformation.ir import GoToStatement

    return any(isinstance(s, GoToStatement) for p in paragraphs for s in walk_statements(p.statements))
