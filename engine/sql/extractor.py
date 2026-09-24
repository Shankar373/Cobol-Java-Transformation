"""EXEC SQL blocked extraction from COBOL source (lane-owned).

The COBOL parser is off-limits to this lane, so this module provides the
minimal, deterministic bridge it is allowed to own: locate ``EXEC SQL ...
END-EXEC`` regions and hand their text to the existing ``SqlParser``.

It deliberately does NOT parse COBOL structure — it only extracts embedded
SQL regions and strips the fixed-format Area A/B column prefix that COBOL
sources carry.
"""

from __future__ import annotations

import re

from engine.sql.analyzer import Db2SemanticAnalyzer
from engine.sql.model import Db2SqlModel
from engine.transformation.ir import EmbeddedSqlBlock
from engine.transformation.sql_parser import SqlParser

_EXEC_SQL_RE = re.compile(
    r"\bEXEC\s+SQL\b(.*?)\bEND-EXEC\b",
    re.IGNORECASE | re.DOTALL,
)

# Fixed-format COBOL columns 1-6 hold an optional sequence number.
_CC_NUMBER_RE = re.compile(r"^\d{6}\s?")

_SQL_PARSER = SqlParser()


def _clean_cobol_line(line: str) -> str:
    """Strip the fixed-format column prefix from one COBOL source line."""
    cleaned = _CC_NUMBER_RE.sub("", line, count=1)
    return cleaned.strip()


def extract_embedded_sql_blocks(cobol_text: str) -> list[str]:
    """Return the SQL text of every ``EXEC SQL ... END-EXEC`` region.

    Each returned string has the fixed-format Area-A/B column prefix and
    COBOL full-line comments (``*``/``*>``) removed.  Extraction is
    deterministic; a comment mentioning ``EXEC SQL`` cannot open a region.
    """
    source_lines = []
    for line in cobol_text.splitlines():
        cleaned_line = _clean_cobol_line(line)
        if cleaned_line and not cleaned_line.startswith("*"):
            source_lines.append(cleaned_line)
    blocks: list[str] = []
    for match in _EXEC_SQL_RE.finditer("\n".join(source_lines)):
        raw = match.group(1)
        cleaned = "\n".join(
            _clean_cobol_line(line) for line in raw.splitlines() if line.strip()
        )
        if cleaned.strip():
            blocks.append(cleaned)
    return blocks


def parse_sql_blocks(sql_texts: list[str]) -> tuple[EmbeddedSqlBlock, ...]:
    """Parse extracted SQL texts into embedded SQL blocks."""
    blocks: list[EmbeddedSqlBlock] = []
    for text in sql_texts:
        blocks.append(_SQL_PARSER.parse_embedded_sql(text))
    return tuple(blocks)


def analyze_cobol_sql(
    cobol_text: str,
    program_id: str,
    sqlcode_field: str = "SQLCODE",
    sqlstate_field: str = "SQLSTATE",
) -> Db2SqlModel:
    """End-to-end lane analysis: EXEC SQL regions → DB2 semantic model."""
    sql_texts = extract_embedded_sql_blocks(cobol_text)
    blocks = parse_sql_blocks(sql_texts)
    return Db2SemanticAnalyzer().analyze_program(
        program_id,
        blocks,
        sqlcode_field=sqlcode_field,
        sqlstate_field=sqlstate_field,
    )