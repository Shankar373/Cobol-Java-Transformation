"""JCL-specific transformation diagnostics.

The JCL modernization lane keeps its own diagnostic vocabulary so that the
shared transformation diagnostics (``engine.transformation.diagnostics``)
remain untouched. Every diagnostic is deterministic and carries enough
structure for tooling: level, code, and a location pointing at the offending
job/step construct.

Diagnostic policy:

- Supported construct: no diagnostic (or an INFO diagnostic when a nuance is
  preserved verbatim).
- Construct recognized but only partially representable: WARNING with an
  explicit statement of what is preserved and what is not.
- Construct outside the supported subset: ERROR diagnostic. The construct is
  never silently dropped.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class JclDiagnosticLevel(Enum):
    """Severity level for JCL diagnostics."""

    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class JclDiagnosticCode(Enum):
    """Structured JCL diagnostic codes."""

    PROFILE_NOTED = "JCL_PROFILE_NOTED"
    PARTIAL_COND_SEMANTICS = "JCL_PARTIAL_COND_SEMANTICS"
    UNRESOLVED_SYMBOL = "JCL_UNRESOLVED_SYMBOL"
    SYMBOL_SET_PRESERVED = "JCL_SYMBOL_SET_PRESERVED"
    DUMMY_RESOURCE = "JCL_DUMMY_RESOURCE"
    JOB_UNNAMED = "JCL_JOB_UNNAMED"
    STEP_NO_EXEC = "JCL_STEP_NO_EXEC"
    UNSUPPORTED_PROCEDURE = "JCL_UNSUPPORTED_PROCEDURE"
    UNSUPPORTED_CONTROL_BLOCK = "JCL_UNSUPPORTED_CONTROL_BLOCK"
    UNSUPPORTED_STATEMENT = "JCL_UNSUPPORTED_STATEMENT"
    UNSUPPORTED_CONTINUATION = "JCL_UNSUPPORTED_CONTINUATION"


@dataclass(frozen=True)
class JclDiagnostic:
    """A structured JCL diagnostic.

    Args:
        level: severity of the diagnostic.
        code: structured diagnostic code.
        message: human-readable description.
        job: originating JOB name (empty when not attributable).
        step: originating STEP name (empty when not attributable).
        location: free-form location hint (e.g. line number).
    """

    level: JclDiagnosticLevel
    code: JclDiagnosticCode
    message: str
    job: str = ""
    step: str = ""
    location: str = ""

    @classmethod
    def info(
        cls, code: JclDiagnosticCode, message: str, **kwargs: str
    ) -> JclDiagnostic:
        return cls(level=JclDiagnosticLevel.INFO, code=code, message=message, **kwargs)

    @classmethod
    def warning(
        cls, code: JclDiagnosticCode, message: str, **kwargs: str
    ) -> JclDiagnostic:
        return cls(
            level=JclDiagnosticLevel.WARNING, code=code, message=message, **kwargs
        )

    @classmethod
    def error(
        cls, code: JclDiagnosticCode, message: str, **kwargs: str
    ) -> JclDiagnostic:
        return cls(level=JclDiagnosticLevel.ERROR, code=code, message=message, **kwargs)


class JclDiagnosticCollector:
    """Collects JCL diagnostics during semantic build and mapping."""

    def __init__(self) -> None:
        self._diagnostics: list[JclDiagnostic] = []

    def add(self, diagnostic: JclDiagnostic) -> None:
        self._diagnostics.append(diagnostic)

    def info(self, code: JclDiagnosticCode, message: str, **kwargs: str) -> None:
        self.add(JclDiagnostic.info(code, message, **kwargs))

    def warning(self, code: JclDiagnosticCode, message: str, **kwargs: str) -> None:
        self.add(JclDiagnostic.warning(code, message, **kwargs))

    def error(self, code: JclDiagnosticCode, message: str, **kwargs: str) -> None:
        self.add(JclDiagnostic.error(code, message, **kwargs))

    @property
    def has_errors(self) -> bool:
        return any(d.level == JclDiagnosticLevel.ERROR for d in self._diagnostics)

    @property
    def has_warnings(self) -> bool:
        return any(d.level == JclDiagnosticLevel.WARNING for d in self._diagnostics)

    @property
    def errors(self) -> list[JclDiagnostic]:
        return [d for d in self._diagnostics if d.level == JclDiagnosticLevel.ERROR]

    @property
    def warnings(self) -> list[JclDiagnostic]:
        return [d for d in self._diagnostics if d.level == JclDiagnosticLevel.WARNING]

    @property
    def all(self) -> tuple[JclDiagnostic, ...]:
        return tuple(self._diagnostics)

    def clear(self) -> None:
        self._diagnostics.clear()

    def with_job(self, job: str) -> list[JclDiagnostic]:
        """Return diagnostics attributable to a specific job."""
        return [d for d in self._diagnostics if d.job == job]
