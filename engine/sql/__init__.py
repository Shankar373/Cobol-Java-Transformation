"""DB2 / embedded SQL modernization lane.

This package owns the DB2 SQL semantic layer for the COBOL → Java
transformation platform.  It is isolated by design:

- references the frozen SQL IR in ``engine.transformation.ir`` (read-only)
- never imports or modifies COBOL/CICS/Spring/generator modules
- produces a Java repository/service representation that downstream
  generators may consume through the documented integration hook

Compatibility claims are disciplined: syntax/semantic compatibility is
classified explicitly and is never conflated with DB2 runtime verification.
"""

from engine.sql.dialect import (
    Db2CompatibilityLevel,
    Db2FeatureCompatibility,
    compatibility_report,
)
from engine.sql.model import (
    Db2BindingDirection,
    Db2SqlModel,
    Db2StmtSemantic,
    Db2TableUsage,
    HostVariableOccurrence,
    SqlHostVariableSemantic,
)
from engine.sql.status import (
    SQLCODE_DUPLICATE_KEY,
    SQLCODE_NO_DATA,
    SQLCODE_SUCCESS,
    SQLCODE_TOO_MANY_ROWS,
    SQLSTATE_DUPLICATE_KEY,
    SQLSTATE_NO_DATA,
    SQLSTATE_SUCCESS,
    SQLSTATE_TOO_MANY_ROWS,
    Db2SqlStatus,
)

__all__ = [
    "SQLCODE_DUPLICATE_KEY",
    "SQLCODE_NO_DATA",
    "SQLCODE_SUCCESS",
    "SQLCODE_TOO_MANY_ROWS",
    "SQLSTATE_DUPLICATE_KEY",
    "SQLSTATE_NO_DATA",
    "SQLSTATE_SUCCESS",
    "SQLSTATE_TOO_MANY_ROWS",
    "Db2BindingDirection",
    "Db2CompatibilityLevel",
    "Db2FeatureCompatibility",
    "Db2SqlModel",
    "Db2SqlStatus",
    "Db2StmtSemantic",
    "Db2TableUsage",
    "HostVariableOccurrence",
    "SqlHostVariableSemantic",
    "compatibility_report",
]