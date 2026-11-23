"""Explicit, closed policies for source properties the engine does not model (Layer 5 entry policies, deterministic).

Three questions had no stated answer; each now has one, and an input outside the answer is *named*, never guessed:

* **Compiler options** (``CBL``/``PROCESS`` cards and ``$SET``): :func:`classify_option` puts every option in one of
  ``LISTING`` (changes only listings/diagnostics), ``DIALECT`` (selects a language level the dialect profile already
  records) or ``SEMANTIC`` (changes the meaning of generated code: arithmetic, truncation, data representation, the
  CICS/SQL/DB2 precompilers, character sets, run-time checking) - and ``UNCLASSIFIED`` for anything else.
  ``SEMANTIC`` and ``UNCLASSIFIED`` are *unmodelled*: facts derived under them are incomplete.  No option is
  silently ignored, and a missing option is never read as "default".
* **JCL flavour**: :func:`jcl_flavour` accepts z/OS JCL (a ``//name JOB|EXEC|DD`` statement with the name in column 3)
  and names every other JCL-like text (``VSE``, ``UNKNOWN``) as unsupported, so a VSE job is never read as z/OS.
* **Line terminators and tabs**: :func:`line_terminator_policy` - LF and CRLF are read, a lone CR is refused by the
  parser; a TAB makes a column inexact (``SPAN_COLUMN_TAB``) but never moves a line number.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Options that only change listings or diagnostics (honoured by ignoring them is safe).
LISTING_OPTIONS = frozenset({
    "LIST", "NOLIST", "MAP", "NOMAP", "XREF", "NOXREF", "SOURCE", "NOSOURCE", "OFFSET", "NOOFFSET", "NUMBER",
    "NONUMBER", "SEQUENCE", "NOSEQUENCE", "SEQ", "NOSEQ", "FLAG", "TERMINAL", "NOTERMINAL", "VBREF", "NOVBREF",
    "SPACE", "TEST", "NOTEST", "OPTIMIZE", "NOOPTIMIZE", "OPT", "NOOPT", "OPTIONS", "NOOPTIONS", "LINECOUNT",
    "PRINT", "NOPRINT", "SSRANGE_LISTING",
})
#: Options that select a language level (their value is in the dialect profile's ``dialect``/``oracle_std``).
DIALECT_OPTIONS = frozenset({"STD", "DEFAULT", "COBOL85", "COBOL2002", "COBOL2014", "MF", "IBM", "ACU", "XOPEN",
                             "FREE", "FIXED", "FORMAT"})
#: Options that change what generated code means; the engine models none of them.
SEMANTIC_OPTIONS = frozenset({
    "TRUNC", "NUMPROC", "ARITH", "BINARY", "DYNAM", "NODYNAM", "CICS", "SQL", "DB2", "DBCS", "NODBCS", "NSYMBOL",
    "CURRENCY", "CODEPAGE", "CHAR", "FLOAT", "SSRANGE", "NOSSRANGE", "RENT", "NORENT", "THREAD", "NOTHREAD",
    "ZWB", "NOZWB", "AWO", "NOAWO", "APOST", "QUOTE", "EXPORTALL", "LIB", "NOLIB", "RMODE", "AMODE", "PGMNAME",
    "INTDATE", "NSYMBOL", "DATEPROC", "YEARWINDOW", "MDECK", "NOMDECK", "WORD", "COMPILE", "NOCOMPILE", "ADV",
    "NOADV", "CMPR2", "NOCMPR2", "PARMCHECK", "DIAGTRUNC", "SERVICE", "SQLCCSID", "NOSQLCCSID", "STGOPT",
})

OPTION_CLASSES = ("LISTING", "DIALECT", "SEMANTIC", "UNCLASSIFIED")
_KEYWORD = re.compile(r"^[A-Z][A-Z0-9-]*")


@dataclass(frozen=True)
class OptionVerdict:
    option: str          # as written, upper-case
    keyword: str         # the leading keyword (``TRUNC(BIN)`` -> ``TRUNC``)
    klass: str           # OPTION_CLASSES

    @property
    def unmodelled(self) -> bool:
        return self.klass in ("SEMANTIC", "UNCLASSIFIED")


def classify_option(option: str) -> OptionVerdict:
    text = option.strip().upper()
    found = _KEYWORD.match(text.lstrip("$"))
    keyword = found.group(0) if found else text
    if keyword in SEMANTIC_OPTIONS:
        klass = "SEMANTIC"
    elif keyword in DIALECT_OPTIONS or text.startswith("$SET") and "SOURCEFORMAT" in text:
        klass = "DIALECT"
    elif keyword in LISTING_OPTIONS:
        klass = "LISTING"
    else:
        klass = "UNCLASSIFIED"
    return OptionVerdict(text, keyword, klass)


def classify_options(options: tuple[str, ...] | list[str]) -> tuple[OptionVerdict, ...]:
    """One verdict per option, input order kept (the profile already fixes it: first occurrence)."""
    return tuple(classify_option(option) for option in options)


def unmodelled_options(options: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    """The options a consumer must treat as "facts derived under this file are incomplete"."""
    return tuple(v.option for v in classify_options(options) if v.unmodelled)


# --- JCL flavour ------------------------------------------------------------------------------------------------

JCL_FLAVOURS = ("ZOS", "VSE", "UNKNOWN")
_ZOS = re.compile(r"^//[A-Z0-9@#$]{1,8}\s+(?:JOB|EXEC|DD|PROC|SET|IF|OUTPUT|JCLLIB)\b", re.IGNORECASE | re.MULTILINE)
_ZOS_UNNAMED = re.compile(r"^//\s+(?:DD|EXEC)\b", re.IGNORECASE | re.MULTILINE)   # continuation DD / EXEC without a name
_VSE = re.compile(r"^// +(?:JOB|EXEC|DLBL|ASSGN|LIBDEF|TLBL|UPSI|OPTION|LBLTYP)\b|^/[&*]", re.IGNORECASE | re.MULTILINE)


def jcl_flavour(text: str) -> str:
    """``ZOS`` for z/OS JCL, ``VSE`` for DOS/VSE job control, ``UNKNOWN`` otherwise (never guessed as z/OS).

    A text with both z/OS statements and VSE markers is ``UNKNOWN``: it is not one reader's input.
    """
    zos = bool(_ZOS.search(text))
    vse = bool(_VSE.search(text))
    if zos and vse:
        return "UNKNOWN"
    if zos:
        return "ZOS"
    if vse:
        return "VSE"
    return "ZOS" if _ZOS_UNNAMED.search(text) and text.lstrip().startswith("//") else "UNKNOWN"


# --- Line terminators and tabs -----------------------------------------------------------------------------------

_LONE_CR = re.compile(r"\r(?!\n)")


def line_terminator_policy(text: str) -> str:
    """``LF``, ``CRLF``, ``MIXED_LF_CRLF`` (all read, the physical line count is the number of LFs) or
    ``LONE_CR`` (refused by the parser: ``LINE_TERMINATOR_LONE_CR_UNSUPPORTED``)."""
    if _LONE_CR.search(text):
        return "LONE_CR"
    crlf = text.count("\r\n")
    lf = text.count("\n") - crlf
    if crlf and lf:
        return "MIXED_LF_CRLF"
    return "CRLF" if crlf else "LF"
