"""Expand ``COPY`` statements that sit inside the FILE SECTION (G-26).

Copybooks are normally *not* expanded into the program text: the program is parsed as written and
copybook records are merged into WORKING-STORAGE afterwards.  That is wrong for an FD, whose record
belongs to the file: the FD ended up with no record, so WRITE/REWRITE of it were refused and no
layout could be derived.  Discovery therefore expands only the COPY statements located in the FILE
SECTION, textually and in place, before parsing; the parser then sees exactly what it would see for
an inline FD, so ownership, layout and Java generation need no special case.

Fail-closed, reusing the nested-copybook expansion: a member that is missing, ambiguous, unreadable,
cyclic or has an invalid ``REPLACING`` clause yields an ERROR diagnostic and the statement is
skipped - no record is ever invented.  Comments and string literals are masked before COPY
statements are located, so a ``COPY`` word in either is not a statement.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from engine.transformation.copybook_model import (
    CopybookDiagnostic,
    _apply_replacing,
    _expand_copybook_text,
    _find_copy_statements,
    _mask_comments,
    _parse_replacing_clause,
)
from engine.transformation.copybook_resolver import (
    AmbiguousCopybookError,
    CopybookResolutionError,
    resolve_copybook,
)

_SEQ = r"(?:\d{6})?"  # fixed-format sequence number area (columns 1-6)
_FILE_SECTION = re.compile(r"(?im)^" + _SEQ + r"[ \t]*FILE[ \t]+SECTION[ \t]*\.")
_SECTION_END = re.compile(
    r"(?im)^" + _SEQ + r"[ \t]*(?:(?:WORKING-STORAGE|LINKAGE|LOCAL-STORAGE|SCREEN|COMMUNICATION|REPORT)[ \t]+SECTION[ \t]*\."
    r"|PROCEDURE[ \t]+DIVISION\b)"
)
_CHAIN = ("FILE SECTION",)


@dataclass(frozen=True)
class FdCopyExpansion:
    source: str  # the program text with FILE SECTION COPY statements expanded
    diagnostics: tuple[CopybookDiagnostic, ...] = ()
    consumed: tuple[str, ...] = ()  # copybook names expanded into FDs (not to be merged into WORKING-STORAGE)

    @property
    def errors(self) -> tuple[CopybookDiagnostic, ...]:
        return tuple(d for d in self.diagnostics if d.level == "ERROR")


def expand_fd_copybooks(source: str, search_dirs: tuple[Path, ...]) -> FdCopyExpansion:
    """Expand the COPY statements of the FILE SECTION; the rest of ``source`` is returned untouched."""
    masked = _mask_comments(source)
    section = _FILE_SECTION.search(masked)
    if section is None:
        return FdCopyExpansion(source)
    start = section.end()
    stop = _SECTION_END.search(masked, start)
    end = stop.start() if stop else len(source)
    region = source[start:end]
    spans = _find_copy_statements(region)
    if not spans:
        return FdCopyExpansion(source)

    diagnostics: list[CopybookDiagnostic] = []
    consumed: list[str] = []
    masked_region = _mask_comments(region)
    pieces: list[str] = []
    cursor = 0
    for span_start, span_end, target in spans:
        before = region[cursor:span_start].rstrip(" \t")  # the expansion carries its own indentation
        pieces.append(before + ("\n" if before and not before.endswith("\n") else ""))
        cursor = span_end
        pairs, clause_error = _parse_replacing_clause(masked_region[span_start:span_end])
        if clause_error is not None:
            code, message = clause_error
            diagnostics.append(CopybookDiagnostic(level="ERROR", code=code, message=f"{message} (in FILE SECTION)"))
            continue
        try:
            resolved = resolve_copybook(target, search_dirs, program_id="FILE SECTION")
        except AmbiguousCopybookError as exc:
            diagnostics.append(CopybookDiagnostic(
                level="ERROR", code="COPYBOOK_AMBIGUOUS",
                message=f"Ambiguous COPY target {target!r} in FILE SECTION: "
                        + ", ".join(str(c) for c in exc.candidates)))
            continue
        except CopybookResolutionError:
            diagnostics.append(CopybookDiagnostic(
                level="ERROR", code="COPYBOOK_UNRESOLVED", message=f"Missing COPY target: {target} (in FILE SECTION)"))
            continue
        text = _apply_replacing(_expand_copybook_text(resolved.path, search_dirs, _CHAIN, diagnostics), tuple(pairs))
        pieces.append(text if text.endswith("\n") else text + "\n")
        consumed.append(target.upper())
    pieces.append(region[cursor:])
    return FdCopyExpansion(source[:start] + "".join(pieces) + source[end:], tuple(diagnostics), tuple(consumed))
