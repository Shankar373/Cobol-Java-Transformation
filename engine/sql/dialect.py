"""DB2 compatibility classification.

The lane rule is strict: syntax/semantic compatibility and actual DB2
runtime compatibility are different claims that must never be conflated.

    DB2_SYNTAX            recognized as valid DB2 SQL syntax
    DB2_SEMANTIC          semantic model derived from source positions
    PORTABLE_EXECUTABLE   deterministically executable on the controlled
                          test database (SQLite) after translation
    DB2_RUNTIME_VERIFIED  verified against a real DB2 subsystem

``DB2_RUNTIME_VERIFIED`` is only ever attached explicitly (with evidence of
running against DB2); nothing in this lane can manufacture it.  A green
test on the controlled database warrants at most PORTABLE_EXECUTABLE.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from engine.sql.model import Db2SqlModel


class Db2CompatibilityLevel(Enum):
    """Strictly ordered claim levels.  Higher = stronger claim."""

    DB2_SYNTAX = "DB2_SYNTAX"
    DB2_SEMANTIC = "DB2_SEMANTIC"
    PORTABLE_EXECUTABLE = "PORTABLE_EXECUTABLE"
    DB2_RUNTIME_VERIFIED = "DB2_RUNTIME_VERIFIED"

    @property
    def rank(self) -> int:
        order = ("DB2_SYNTAX", "DB2_SEMANTIC", "PORTABLE_EXECUTABLE", "DB2_RUNTIME_VERIFIED")
        return order.index(self.value)

    def at_least(self, other: Db2CompatibilityLevel) -> bool:
        return self.rank >= other.rank


@dataclass(frozen=True)
class Db2FeatureCompatibility:
    """Compatibility claim for one SQL feature of a program.

    ``claim`` is the strongest level *supported by this lane*, not a verified
    statement about DB2 runtime behavior.  ``runtime_verified`` must remain
    False unless a real DB2 run produced the evidence.
    """

    feature: str                  # statement type or SQL construct
    claim: Db2CompatibilityLevel
    note: str = ""

    @property
    def runtime_verified(self) -> bool:
        return self.claim == Db2CompatibilityLevel.DB2_RUNTIME_VERIFIED


_DB2_SPECIFIC_CONSTRUCTS = (
    (re.compile(r"FETCH\s+FIRST\s+\d+\s+ROWS?\s+ONLY", re.IGNORECASE),
     "FETCH FIRST n ROWS ONLY"),
    (re.compile(r"NVL\s*\(", re.IGNORECASE), "NVL() built-in function"),
    (re.compile(r"CURRENT\s+(?:DATE|TIME|TIMESTAMP)\b", re.IGNORECASE),
     "CURRENT DATE/TIME/TIMESTAMP"),
    (re.compile(r"GENERATED\s+ALWAYS\s+AS\s+IDENTITY", re.IGNORECASE),
     "GENERATED ALWAYS AS IDENTITY"),
)


@dataclass(frozen=True)
class _StatementClassification:
    syntax_known: bool = True            # parseable by this lane's parser
    semantically_modeled: bool = True    # Db2SemanticAnalyzer handles it
    portable: bool = False               # translatable to the test database
    note: str = ""


_PORTABLE_STATEMENTS = {
    "SELECT": True,
    "INSERT": True,
    "UPDATE": True,
    "DELETE": True,
    "DECLARE_CURSOR": True,
    "OPEN_CURSOR": True,
    "FETCH_CURSOR": True,
    "CLOSE_CURSOR": True,
    "COMMIT": True,
    "ROLLBACK": True,
}

_NON_PORTABLE_STATEMENTS = {
    "CALL": "stored procedure invocation is outside the execution subset",
    "PREPARE": "dynamic SQL preparation is outside the execution subset",
    "EXECUTE": "dynamic SQL execution is outside the execution subset",
}


def classify_statement(
    stmt_semantic,
) -> _StatementClassification:
    """Classify one analyzed statement into the compatibility levels."""
    stype = stmt_semantic.statement_type
    if stype in _PORTABLE_STATEMENTS:
        level_note = ""
        if stmt_semantic.is_cursor_operation:
            level_note = "cursor lifecycle supported by the controlled harness"
        return _StatementClassification(
            syntax_known=True,
            semantically_modeled=True,
            portable=True,
            note=level_note,
        )
    if stype in _NON_PORTABLE_STATEMENTS:
        return _StatementClassification(
            syntax_known=True,
            semantically_modeled=True,
            portable=False,
            note=_NON_PORTABLE_STATEMENTS[stype],
        )
    return _StatementClassification(
        syntax_known=False,
        semantically_modeled=False,
        portable=False,
        note=f"statement type {stype!r} is outside the lane's supported subset",
    )


def _claim_for(
    stmt_semantic,
    classification: _StatementClassification,
) -> Db2CompatibilityLevel:
    if not classification.syntax_known:
        return Db2CompatibilityLevel.DB2_SYNTAX
    if classification.portable:
        return Db2CompatibilityLevel.PORTABLE_EXECUTABLE
    if classification.semantically_modeled:
        return Db2CompatibilityLevel.DB2_SEMANTIC
    return Db2CompatibilityLevel.DB2_SYNTAX


def compatibility_report(model: Db2SqlModel) -> list[Db2FeatureCompatibility]:
    """Deterministic per-feature compatibility report for a DB2 SQL model.

    Every item is a *support claim of this lane* at the stated level;
    ``runtime_verified`` is False for all of them (see module docstring).
    """
    report: list[Db2FeatureCompatibility] = []
    for stmt in model.statements:
        classification = classify_statement(stmt)
        claim = _claim_for(stmt, classification)
        note = classification.note
        report.append(
            Db2FeatureCompatibility(
                feature=stmt.statement_type,
                claim=claim,
                note=note,
            )
        )
        for regex, label in _DB2_SPECIFIC_CONSTRUCTS:
            if regex.search(stmt.raw_sql):
                report.append(
                    Db2FeatureCompatibility(
                        feature=label,
                        claim=Db2CompatibilityLevel.DB2_SYNTAX,
                        note=(
                            "DB2-specific syntax; the controlled harness "
                            "translates it deterministically for execution"
                        ),
                    )
                )
    return report


def runtime_verified_features(report: list[Db2FeatureCompatibility]) -> list[str]:
    """Features claimed DB2_RUNTIME_VERIFIED (expected empty on this lane)."""
    return [f.feature for f in report if f.runtime_verified]