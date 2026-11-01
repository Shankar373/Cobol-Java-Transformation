"""COBOL reference-format detection shared by the oracle and the parser.

The oracle compiles a source as free format only when it looks free format
(``DockerOracleAdapter.detect_source_format`` delegates here), and the
parser must read the same text the compiler reads.  In fixed format the
compiler ignores the program-identification area — every column after 72 —
so the parser drops it too; otherwise it would translate characters the
compiled COBOL program never contains (e.g. a data name cut at column 72,
or sequence numbers in columns 73-80).
"""

from __future__ import annotations

#: Last column of the fixed-format program text area (Area B ends here).
FIXED_FORMAT_TEXT_END = 72


def _line_is_comment(line: str) -> bool:
    """True for fixed- or free-format comment lines."""
    if line.startswith("*") or line.startswith("/"):
        return True
    if len(line) > 6 and line[6] in "*/":
        return True
    return line.lstrip().startswith("*>")


def detect_source_format(text: str) -> str:
    """Classify COBOL source text as ``"free"`` or ``"fixed"``.

    An explicit ``>>SOURCE FORMAT`` directive takes precedence. In its
    absence fixed format is assumed unless a code line places a
    non-digit, non-space character in the sequence area (columns 1-6):
    that is impossible in fixed format and is characteristic of free
    format, where code may begin at column 1.
    """
    for raw in text.splitlines():
        upper = raw.strip().upper()
        if upper.startswith(">>SOURCE") and "FORMAT" in upper:
            if "FREE" in upper:
                return "free"
            if "FIXED" in upper:
                return "fixed"
    for raw in text.splitlines():
        line = raw.rstrip("\r\n")
        if not line.strip() or _line_is_comment(line):
            continue
        if any(ch not in "0123456789 " for ch in line[:6]):
            return "free"
    return "fixed"


def compiler_visible_text(text: str) -> str:
    """The source text a fixed-format compile reads: columns 1-72 only.

    Free-format text is returned unchanged.  Line structure is preserved so
    diagnostics keep their line numbers.
    """
    if detect_source_format(text) != "fixed":
        return text
    return "\n".join(
        line.rstrip("\r")[:FIXED_FORMAT_TEXT_END] for line in text.split("\n")
    )
