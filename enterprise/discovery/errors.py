"""Typed failure taxonomy and diagnostics.

Two distinct ideas are modelled, and conflating them would break the
"fail closed / no silent acceptance" invariants (I1, I2):

``IngestionError``
    The input is unsafe, malformed or unsupported.  Nothing is extracted,
    nothing is emitted, and the run ends with a non-zero exit code.
``Diagnostic``
    The run continues, but something was refused, degraded or could not be
    determined.  Every diagnostic has a stable ``code``, a severity, and a
    location when one exists.  Diagnostics are emitted into the manifest, so a
    refusal is never invisible.

Stable codes are part of the output contract: tests assert on codes rather
than on message text, so wording can be improved without breaking tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

__all__ = [
    "Severity",
    "IngestionError",
    "UnsafePathError",
    "LimitExceededError",
    "UnsupportedInputError",
    "Diagnostic",
    "DiagnosticSink",
]


class Severity:
    """Diagnostic severities (closed set)."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"

    ALL = (ERROR, WARNING, INFO)


class IngestionError(Exception):
    """Base class for fail-closed ingestion failures.

    ``code`` is a stable identifier suitable for assertions and for the CLI
    exit summary; ``location`` is an optional ``(path, line, column)``.
    """

    code = "INGESTION_FAILED"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        path: str | None = None,
        line: int | None = None,
        column: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        self.path = path
        self.line = line
        self.column = column

    def as_dict(self) -> dict[str, object]:
        out: dict[str, object] = {"code": self.code, "message": self.message}
        if self.path is not None:
            out["file"] = self.path
        if self.line is not None:
            out["line"] = self.line
        if self.column is not None:
            out["column"] = self.column
        return out

    def __str__(self) -> str:  # pragma: no cover - formatting only
        loc = ""
        if self.path:
            loc = f" [{self.path}"
            if self.line is not None:
                loc += f":{self.line}"
                if self.column is not None:
                    loc += f":{self.column}"
            loc += "]"
        return f"{self.code}: {self.message}{loc}"


class UnsafePathError(IngestionError):
    """An entry name would escape the staging root or collide on the filesystem."""

    code = "UNSAFE_PATH"


class LimitExceededError(IngestionError):
    """A declared or observed bound was exceeded; extraction aborts."""

    code = "LIMIT_EXCEEDED"


class UnsupportedInputError(IngestionError):
    """The input type or an embedded construct is outside P1 scope."""

    code = "UNSUPPORTED_INPUT"


@dataclass(frozen=True, order=True)
class Diagnostic:
    """One recorded refusal/degradation, ordered deterministically."""

    sort_key: tuple[str, int, int, str] = field(default=("zzz", 0, 0, ""))
    code: str = ""
    severity: str = Severity.WARNING
    message: str = ""
    path: str | None = None
    line: int | None = None
    column: int | None = None

    @classmethod
    def make(
        cls,
        code: str,
        message: str,
        *,
        severity: str = Severity.WARNING,
        path: str | None = None,
        line: int | None = None,
        column: int | None = None,
    ) -> "Diagnostic":
        if severity not in Severity.ALL:
            raise ValueError(f"unknown severity {severity!r}")
        # Sort by location first so a report reads top-to-bottom, then by code.
        key = (path or "", line or 0, column or 0, code)
        return cls(
            sort_key=key,
            code=code,
            severity=severity,
            message=message,
            path=path,
            line=line,
            column=column,
        )

    def as_dict(self) -> dict[str, object]:
        out: dict[str, object] = {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
        }
        if self.path is not None:
            out["file"] = self.path
        if self.line is not None:
            out["line"] = self.line
        if self.column is not None:
            out["column"] = self.column
        return out

    def render(self) -> str:
        loc = ""
        if self.path:
            loc = f" [{self.path}"
            if self.line is not None:
                loc += f":{self.line}"
                if self.column is not None:
                    loc += f":{self.column}"
            loc += "]"
        return f"{self.severity.upper()} {self.code}{loc}: {self.message}"


class DiagnosticSink:
    """Collects diagnostics, de-duplicates, caps the count, sorts for output.

    The cap matters: without it a hostile input could emit unbounded
    diagnostics and grow the manifest without limit.
    """

    def __init__(self, max_diagnostics: int = 500) -> None:
        self._max = max_diagnostics
        self._items: dict[tuple[object, ...], Diagnostic] = {}
        self._dropped = 0

    def add(self, diagnostic: Diagnostic) -> None:
        key = (
            diagnostic.code,
            diagnostic.path,
            diagnostic.line,
            diagnostic.column,
            diagnostic.message,
        )
        if key in self._items:
            return
        if len(self._items) >= self._max:
            self._dropped += 1
            return
        self._items[key] = diagnostic

    def warn(self, code: str, message: str, **loc: object) -> None:
        self.add(Diagnostic.make(code, message, severity=Severity.WARNING, **loc))  # type: ignore[arg-type]

    def error(self, code: str, message: str, **loc: object) -> None:
        self.add(Diagnostic.make(code, message, severity=Severity.ERROR, **loc))  # type: ignore[arg-type]

    def info(self, code: str, message: str, **loc: object) -> None:
        self.add(Diagnostic.make(code, message, severity=Severity.INFO, **loc))  # type: ignore[arg-type]

    @property
    def dropped(self) -> int:
        """Diagnostics refused by the cap — surfaced, never hidden."""

        return self._dropped

    def __len__(self) -> int:
        return len(self._items)

    def extend(self, items: Iterable[Diagnostic]) -> None:
        for item in items:
            self.add(item)

    def to_list(self) -> list[dict[str, object]]:
        ordered = sorted(
            self._items.values(),
            key=lambda d: (d.sort_key[0], d.sort_key[1], d.sort_key[2], d.sort_key[3]),
        )
        out = [d.as_dict() for d in ordered]
        if self._dropped:
            out.append(
                Diagnostic.make(
                    "DIAGNOSTICS_TRUNCATED",
                    f"{self._dropped} diagnostic(s) suppressed by the "
                    f"max_diagnostics={self._max} cap",
                    severity=Severity.WARNING,
                ).as_dict()
            )
        return out
