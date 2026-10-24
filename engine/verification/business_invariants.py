"""Declarative business invariants with deterministic evaluation.

The platform already proves *technical* equivalence of observed artifacts.
Business equivalence additionally requires that declared business rules hold
for each execution, independently, before the two sides may be called
equivalent. This module supplies that missing layer:

- Invariants are declarations, not code supplied by a workload.
- Evaluation is a pure function of one execution observation.
- All comparisons are exact: lines are exact, fixed fields are exact byte
  slices, totals use :class:`decimal.Decimal` arithmetic (never floats), JSON
  numbers are parsed as ``Decimal``.
- The resulting report is canonical JSON and content-addressed, so it can be
  sealed into the existing evidence graph and compared by the existing
  comparator/verdict machinery.

A report is ``PASS`` only when at least one invariant is declared and every
declared invariant passed. There is no vacuous pass.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any

SCHEMA_VERSION = "1.0"

#: Field tokens accepted in a dotted JSON path, with optional list indexes,
#: e.g. ``account.lines[0].amount``.
_JSON_TOKEN = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)((?:\[\d+\])*)$")
_JSON_INDEX = re.compile(r"\[(\d+)\]")
_SIGNED_INTEGER = re.compile(r"^[+-]?\d+$")


class InvariantPhase(str, Enum):
    """When an invariant must hold."""

    PRECONDITION = "PRECONDITION"
    POSTCONDITION = "POSTCONDITION"
    ERROR_BEHAVIOR = "ERROR_BEHAVIOR"


class InvariantKind(str, Enum):
    """The closed set of supported invariant kinds."""

    EXIT_CODE = "EXIT_CODE"
    EXACT_LINES = "EXACT_LINES"
    LINE_COUNT = "LINE_COUNT"
    RECORD_COUNT = "RECORD_COUNT"
    FIXED_FIELD_EQUALS = "FIXED_FIELD_EQUALS"
    FIXED_FIELD_TOTAL = "FIXED_FIELD_TOTAL"
    JSON_FIELD_EQUALS = "JSON_FIELD_EQUALS"


class InvariantSource(str, Enum):
    """Where an invariant reads its observed value from."""

    STDOUT = "STDOUT"
    STDERR = "STDERR"
    EXIT_STATUS = "EXIT_STATUS"
    FILE = "FILE"
    INPUT = "INPUT"


_TEXT_SOURCES = frozenset({
    InvariantSource.STDOUT,
    InvariantSource.STDERR,
    InvariantSource.FILE,
    InvariantSource.INPUT,
})
_FILE_SOURCES = frozenset({InvariantSource.FILE, InvariantSource.INPUT})


# ---------------------------------------------------------------------------
# Canonical value handling
# ---------------------------------------------------------------------------

def _is_json_number(value: object) -> bool:
    return isinstance(value, (int, Decimal)) and not isinstance(value, bool)


def _validate_json_value(value: object, *, path: str = "expected") -> None:
    """Reject values that cannot be compared deterministically.

    Floats are rejected: IEEE-754 rounding would make a business expectation
    platform-dependent. Callers must express decimals as strings and the
    evaluator converts them through :class:`Decimal`.
    """
    if isinstance(value, float):
        raise ValueError(
            f"{path} must not be a float; express decimals as strings for "
            f"exact Decimal comparison"
        )
    if isinstance(value, (str, bool, int, Decimal)) or value is None:
        if isinstance(value, Decimal) and not value.is_finite():
            raise ValueError(f"{path} must be a finite Decimal")
        return
    if isinstance(value, bytes):
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _validate_json_value(item, path=f"{path}[{index}]")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} keys must be strings, got {key!r}")
            _validate_json_value(item, path=f"{path}.{key}")
        return
    raise ValueError(f"{path} has unsupported type {type(value).__name__}")


def canonical_value(value: object) -> Any:
    """Return a deterministic JSON-compatible representation of a value."""
    if isinstance(value, bytes):
        return {"$bytes_hex": value.hex()}
    if isinstance(value, Decimal):
        return {"$decimal": format(value, "f")}
    if isinstance(value, tuple):
        return [canonical_value(item) for item in value]
    if isinstance(value, list):
        return [canonical_value(item) for item in value]
    if isinstance(value, Mapping):
        return {
            str(key): canonical_value(value[key]) for key in sorted(value)
        }
    if isinstance(value, (str, bool, int)) or value is None:
        return value
    raise ValueError(f"unsupported canonical value type {type(value).__name__}")


def _canonical_json(value: object) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


# ---------------------------------------------------------------------------
# Declarations
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BusinessInvariant:
    """A single declarative business rule.

    The same declaration is evaluated against the oracle observation and the
    candidate observation. The rule is satisfied only when evaluation passes
    on both sides; a rule that fails identically on both sides is still a
    failure, never equivalence.
    """

    invariant_id: str
    kind: InvariantKind
    source: InvariantSource = InvariantSource.STDOUT
    expected: object = None
    phase: InvariantPhase = InvariantPhase.POSTCONDITION
    source_name: str | None = None
    record_length: int | None = None
    offset: int | None = None
    length: int | None = None
    record_index: int | None = None
    decimal_places: int = 0
    json_path: str | None = None
    description: str = ""

    def __post_init__(self) -> None:
        if not self.invariant_id or not self.invariant_id.strip():
            raise ValueError("invariant_id cannot be empty")
        if not isinstance(self.kind, InvariantKind):
            raise ValueError(f"kind must be InvariantKind, got {self.kind!r}")
        if not isinstance(self.source, InvariantSource):
            raise ValueError(f"source must be InvariantSource, got {self.source!r}")
        if not isinstance(self.phase, InvariantPhase):
            raise ValueError(f"phase must be InvariantPhase, got {self.phase!r}")

        if self.kind is InvariantKind.EXIT_CODE:
            self._require_source({InvariantSource.EXIT_STATUS})
            if not isinstance(self.expected, int) or isinstance(self.expected, bool):
                raise ValueError(
                    "EXIT_CODE expected must be an int, got "
                    f"{type(self.expected).__name__}"
                )
            self._reject_irrelevant_fields()
            return

        if self.kind is InvariantKind.EXACT_LINES:
            self._require_source(_TEXT_SOURCES)
            self._require_source_name_for_file_source()
            if not isinstance(self.expected, Sequence) or isinstance(
                self.expected, (str, bytes)
            ):
                raise ValueError(
                    "EXACT_LINES expected must be a sequence of strings"
                )
            lines = tuple(self.expected)
            if any(not isinstance(line, str) for line in lines):
                raise ValueError("EXACT_LINES expected entries must be strings")
            object.__setattr__(self, "expected", lines)
            self._reject_irrelevant_fields(source_name=True)
            return

        if self.kind is InvariantKind.LINE_COUNT:
            self._require_source(_TEXT_SOURCES)
            self._require_source_name_for_file_source()
            if (
                not isinstance(self.expected, int)
                or isinstance(self.expected, bool)
                or self.expected < 0
            ):
                raise ValueError("LINE_COUNT expected must be an int >= 0")
            self._reject_irrelevant_fields(source_name=True)
            return

        if self.kind is InvariantKind.RECORD_COUNT:
            self._require_file_source()
            self._require_record_length()
            if (
                not isinstance(self.expected, int)
                or isinstance(self.expected, bool)
                or self.expected < 0
            ):
                raise ValueError("RECORD_COUNT expected must be an int >= 0")
            self._reject_irrelevant_fields(
                source_name=True, record_length=True,
            )
            return

        if self.kind is InvariantKind.FIXED_FIELD_EQUALS:
            self._require_file_source()
            self._require_record_length()
            self._require_field_window()
            if isinstance(self.expected, str):
                object.__setattr__(self, "expected", self.expected.encode("utf-8"))
            if not isinstance(self.expected, bytes):
                raise ValueError(
                    "FIXED_FIELD_EQUALS expected must be bytes or a string"
                )
            self._reject_irrelevant_fields(
                source_name=True, record_length=True, offset=True, length=True,
                record_index=True,
            )
            return

        if self.kind is InvariantKind.FIXED_FIELD_TOTAL:
            self._require_file_source()
            self._require_record_length()
            self._require_field_window()
            if not isinstance(self.expected, (str, int, Decimal)) or isinstance(
                self.expected, bool
            ):
                raise ValueError(
                    "FIXED_FIELD_TOTAL expected must be an exact decimal "
                    "string, int or Decimal"
                )
            if isinstance(self.expected, Decimal) and not self.expected.is_finite():
                raise ValueError("FIXED_FIELD_TOTAL expected must be finite")
            if (
                not isinstance(self.decimal_places, int)
                or isinstance(self.decimal_places, bool)
                or self.decimal_places < 0
            ):
                raise ValueError("decimal_places must be an int >= 0")
            # Validate now so a malformed expectation fails closed at
            # declaration time instead of during evaluation.
            self._expected_decimal()
            self._reject_irrelevant_fields(
                source_name=True, record_length=True, offset=True, length=True,
                record_index=True, decimal_places=True,
            )
            return

        if self.kind is InvariantKind.JSON_FIELD_EQUALS:
            self._require_source(
                {InvariantSource.FILE, InvariantSource.STDOUT, InvariantSource.STDERR}
            )
            self._require_source_name_for_file_source()
            if self.json_path is None or not self.json_path.strip():
                raise ValueError("JSON_FIELD_EQUALS requires json_path")
            object.__setattr__(self, "json_path", self.json_path)
            self._json_tokens()  # validate syntax
            _validate_json_value(self.expected, path="JSON_FIELD_EQUALS.expected")
            self._reject_irrelevant_fields(source_name=True, json_path=True)
            return

        raise ValueError(f"Unsupported invariant kind {self.kind!r}")

    # -- validation helpers -------------------------------------------------

    def _require_source(self, allowed: set[InvariantSource]) -> None:
        if self.source not in allowed:
            raise ValueError(
                f"{self.kind.value} source must be one of "
                f"{sorted(item.value for item in allowed)}, got {self.source.value}"
            )

    def _require_source_name_for_file_source(self) -> None:
        if self.source in _FILE_SOURCES and (
            not self.source_name or not self.source_name.strip()
        ):
            raise ValueError(
                f"{self.kind.value} source {self.source.value} requires source_name"
            )

    def _require_file_source(self) -> None:
        self._require_source(_FILE_SOURCES)
        self._require_source_name_for_file_source()

    def _require_record_length(self) -> None:
        if (
            not isinstance(self.record_length, int)
            or isinstance(self.record_length, bool)
            or self.record_length <= 0
        ):
            raise ValueError(f"{self.kind.value} requires record_length > 0")

    def _require_field_window(self) -> None:
        if (
            not isinstance(self.offset, int)
            or isinstance(self.offset, bool)
            or self.offset < 0
        ):
            raise ValueError(f"{self.kind.value} requires offset >= 0")
        if (
            not isinstance(self.length, int)
            or isinstance(self.length, bool)
            or self.length <= 0
        ):
            raise ValueError(f"{self.kind.value} requires length > 0")
        assert self.record_length is not None
        if self.offset + self.length > self.record_length:
            raise ValueError(
                f"{self.kind.value} window [{self.offset},{self.offset + self.length}) "
                f"exceeds record_length {self.record_length}"
            )
        if self.record_index is not None and (
            not isinstance(self.record_index, int)
            or isinstance(self.record_index, bool)
            or self.record_index < 0
        ):
            raise ValueError("record_index must be an int >= 0 or None")

    def _reject_irrelevant_fields(self, **allowed: bool) -> None:
        """Reject parameters that the kind would silently ignore.

        ``allowed`` marks the fields meaningful for this kind; every other
        field must still hold its default value.
        """
        checks = {
            "source_name": self.source_name is not None,
            "record_length": self.record_length is not None,
            "offset": self.offset is not None,
            "length": self.length is not None,
            "record_index": self.record_index is not None,
            "json_path": self.json_path is not None,
            "decimal_places": self.decimal_places != 0,
        }
        for name, present in checks.items():
            if present and not allowed.get(name, False):
                raise ValueError(
                    f"{self.kind.value} does not accept {name}={getattr(self, name)!r}"
                )

    def _json_tokens(self) -> tuple[str | int, ...]:
        assert self.json_path is not None
        tokens: list[str | int] = []
        for component in self.json_path.split("."):
            match = _JSON_TOKEN.match(component)
            if match is None:
                raise ValueError(
                    f"invalid json_path component {component!r}; expected "
                    f"name or name[index]"
                )
            tokens.append(match.group(1))
            for index in _JSON_INDEX.findall(match.group(2)):
                tokens.append(int(index))
        return tuple(tokens)

    def _expected_decimal(self) -> Decimal:
        try:
            value = Decimal(str(self.expected))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(
                f"FIXED_FIELD_TOTAL expected {self.expected!r} is not a valid "
                f"decimal: {exc}"
            ) from exc
        if not value.is_finite():
            raise ValueError("FIXED_FIELD_TOTAL expected must be finite")
        return value

    # -- canonical form -----------------------------------------------------

    def to_canonical_dict(self) -> dict[str, Any]:
        """Canonical declaration used for hashing and report self-checking."""
        return {
            "invariant_id": self.invariant_id,
            "kind": self.kind.value,
            "source": self.source.value,
            "phase": self.phase.value,
            "source_name": self.source_name,
            "expected": canonical_value(self.expected),
            "record_length": self.record_length,
            "offset": self.offset,
            "length": self.length,
            "record_index": self.record_index,
            "decimal_places": self.decimal_places,
            "json_path": self.json_path,
            "description": self.description,
        }


def invariant_definition_digest(
    invariants: Sequence[BusinessInvariant],
) -> str:
    """SHA-256 over the canonical declarations, sorted by invariant id.

    Declaration order is not semantic, so reordering invariants must not
    change either the digest or the canonical report.
    """
    payload = [
        invariant.to_canonical_dict()
        for invariant in sorted(invariants, key=lambda item: item.invariant_id)
    ]
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Observation and results
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class InvariantObservation:
    """One execution's observable state.

    ``files`` is keyed by the declared output path, exactly as the execution
    adapters report generated files. ``inputs`` is keyed by the staged input
    file name.
    """

    exit_code: int | None
    stdout: bytes = b""
    stderr: bytes = b""
    files: Mapping[str, bytes] = field(default_factory=dict)
    inputs: Mapping[str, bytes] = field(default_factory=dict)


@dataclass(frozen=True)
class InvariantOutcome:
    """Evaluation result for one invariant."""

    invariant_id: str
    phase: InvariantPhase
    kind: InvariantKind
    passed: bool
    expected: object
    observed: object
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "invariant_id": self.invariant_id,
            "phase": self.phase.value,
            "kind": self.kind.value,
            "passed": self.passed,
            "expected": canonical_value(self.expected),
            "observed": canonical_value(self.observed),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class BusinessInvariantReport:
    """Canonical, content-addressed report for one execution side."""

    definition_digest: str
    definitions: tuple[dict[str, Any], ...]
    outcomes: tuple[InvariantOutcome, ...]
    schema_version: str = SCHEMA_VERSION

    @property
    def overall(self) -> str:
        return (
            "PASS"
            if self.outcomes and all(outcome.passed for outcome in self.outcomes)
            else "FAIL"
        )

    @property
    def failed_count(self) -> int:
        return sum(1 for outcome in self.outcomes if not outcome.passed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "definition_digest": self.definition_digest,
            "definitions": [dict(item) for item in self.definitions],
            "overall": self.overall,
            "evaluated_count": len(self.outcomes),
            "failed_count": self.failed_count,
            "outcomes": [outcome.to_dict() for outcome in self.outcomes],
        }

    def to_bytes(self) -> bytes:
        """Canonical bytes captured as the BUSINESS_INVARIANT artifact."""
        return _canonical_json(self.to_dict()).encode("utf-8")


#: Historical name kept as an alias for callers that used the design name.
EvaluationReport = BusinessInvariantReport


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def _decode_text(content: bytes) -> str | None:
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _read_source(
    invariant: BusinessInvariant, observation: InvariantObservation
) -> tuple[bytes | None, str]:
    if invariant.source is InvariantSource.STDOUT:
        return observation.stdout, "STDOUT"
    if invariant.source is InvariantSource.STDERR:
        return observation.stderr, "STDERR"
    assert invariant.source_name is not None
    if invariant.source is InvariantSource.FILE:
        content = observation.files.get(invariant.source_name)
        return content, f"FILE:{invariant.source_name}"
    if invariant.source is InvariantSource.INPUT:
        content = observation.inputs.get(invariant.source_name)
        return content, f"INPUT:{invariant.source_name}"
    return None, invariant.source.value


def _outcome(
    invariant: BusinessInvariant,
    *,
    passed: bool,
    observed: object,
    reason: str,
) -> InvariantOutcome:
    return InvariantOutcome(
        invariant_id=invariant.invariant_id,
        phase=invariant.phase,
        kind=invariant.kind,
        passed=passed,
        expected=invariant.expected,
        observed=observed,
        reason=reason,
    )


def _evaluate_one(
    invariant: BusinessInvariant, observation: InvariantObservation
) -> InvariantOutcome:
    if invariant.kind is InvariantKind.EXIT_CODE:
        actual = observation.exit_code
        if actual is None:
            return _outcome(
                invariant, passed=False, observed="MISSING",
                reason="execution reported no exit code",
            )
        return _outcome(
            invariant,
            passed=actual == invariant.expected,
            observed=actual,
            reason=(
                "exit code matched"
                if actual == invariant.expected
                else f"exit code {actual} != expected {invariant.expected}"
            ),
        )

    content, label = _read_source(invariant, observation)
    if content is None:
        return _outcome(
            invariant,
            passed=False,
            observed="MISSING",
            reason=f"declared source {label} is missing",
        )

    if invariant.kind in (InvariantKind.EXACT_LINES, InvariantKind.LINE_COUNT):
        text = _decode_text(content)
        if text is None:
            return _outcome(
                invariant,
                passed=False,
                observed={"$bytes_hex": content.hex()},
                reason=f"{label} is not valid UTF-8; exact line comparison refused",
            )
        lines = tuple(text.splitlines())
        if invariant.kind is InvariantKind.EXACT_LINES:
            expected_lines = tuple(invariant.expected)  # type: ignore[arg-type]
            return _outcome(
                invariant,
                passed=lines == expected_lines,
                observed=list(lines),
                reason=(
                    f"{label} lines matched exactly"
                    if lines == expected_lines
                    else f"{label} lines differ from the declared exact sequence"
                ),
            )
        expected_count = int(invariant.expected)  # type: ignore[arg-type]
        return _outcome(
            invariant,
            passed=len(lines) == expected_count,
            observed=len(lines),
            reason=(
                f"{label} line count matched"
                if len(lines) == expected_count
                else f"{label} has {len(lines)} line(s), expected {expected_count}"
            ),
        )

    if invariant.kind is InvariantKind.RECORD_COUNT:
        assert invariant.record_length is not None
        if len(content) % invariant.record_length != 0:
            return _outcome(
                invariant,
                passed=False,
                observed=len(content),
                reason=(
                    f"{label} length {len(content)} is not divisible by "
                    f"record_length {invariant.record_length}"
                ),
            )
        count = len(content) // invariant.record_length
        expected_count = int(invariant.expected)  # type: ignore[arg-type]
        return _outcome(
            invariant,
            passed=count == expected_count,
            observed=count,
            reason=(
                f"{label} record count matched"
                if count == expected_count
                else f"{label} has {count} record(s), expected {expected_count}"
            ),
        )

    if invariant.kind is InvariantKind.FIXED_FIELD_EQUALS:
        assert invariant.record_length is not None
        assert invariant.offset is not None
        assert invariant.length is not None
        if len(content) % invariant.record_length != 0:
            return _outcome(
                invariant,
                passed=False,
                observed=len(content),
                reason=(
                    f"{label} length {len(content)} is not divisible by "
                    f"record_length {invariant.record_length}"
                ),
            )
        records = _records(content, invariant.record_length)
        if not records:
            return _outcome(
                invariant, passed=False, observed=0,
                reason=f"{label} contains no complete records",
            )
        expected_bytes = invariant.expected  # bytes
        observed_fields: list[Any] = []
        mismatched: list[int] = []
        indexes = (
            [invariant.record_index]
            if invariant.record_index is not None
            else list(range(len(records)))
        )
        for index in indexes:
            if index >= len(records):
                return _outcome(
                    invariant,
                    passed=False,
                    observed=len(records),
                    reason=(
                        f"record_index {index} is out of range for {len(records)} "
                        f"record(s) in {label}"
                    ),
                )
            field_bytes = records[index][
                invariant.offset: invariant.offset + invariant.length
            ]
            observed_fields.append({"$bytes_hex": field_bytes.hex()})
            if field_bytes != expected_bytes:
                mismatched.append(index)
        return _outcome(
            invariant,
            passed=not mismatched,
            observed=(
                observed_fields[0]
                if invariant.record_index is not None
                else {"records_checked": len(indexes), "mismatched": mismatched}
            ),
            reason=(
                f"{label} fixed field matched exactly"
                if not mismatched
                else f"{label} fixed field differs at record(s) {mismatched}"
            ),
        )

    if invariant.kind is InvariantKind.FIXED_FIELD_TOTAL:
        assert invariant.record_length is not None
        assert invariant.offset is not None
        assert invariant.length is not None
        if len(content) % invariant.record_length != 0:
            return _outcome(
                invariant,
                passed=False,
                observed=len(content),
                reason=(
                    f"{label} length {len(content)} is not divisible by "
                    f"record_length {invariant.record_length}"
                ),
            )
        records = _records(content, invariant.record_length)
        if not records:
            return _outcome(
                invariant, passed=False, observed=0,
                reason=f"{label} contains no complete records",
            )
        indexes = (
            [invariant.record_index]
            if invariant.record_index is not None
            else list(range(len(records)))
        )
        total = Decimal(0)
        for index in indexes:
            if index >= len(records):
                return _outcome(
                    invariant,
                    passed=False,
                    observed=len(records),
                    reason=(
                        f"record_index {index} is out of range for {len(records)} "
                        f"record(s) in {label}"
                    ),
                )
            field_bytes = records[index][
                invariant.offset: invariant.offset + invariant.length
            ]
            token = _numeric_token(field_bytes)
            if token is None:
                return _outcome(
                    invariant,
                    passed=False,
                    observed={"$bytes_hex": field_bytes.hex()},
                    reason=(
                        f"{label} record {index} field is not an exact signed "
                        f"integer"
                    ),
                )
            total += Decimal(token)
        if invariant.decimal_places:
            total = total / (Decimal(10) ** invariant.decimal_places)
        expected_total = invariant._expected_decimal()
        return _outcome(
            invariant,
            passed=total == expected_total,
            observed={"$decimal": format(total, "f")},
            reason=(
                f"{label} fixed-field total matched"
                if total == expected_total
                else (
                    f"{label} fixed-field total {format(total, 'f')} != expected "
                    f"{format(expected_total, 'f')}"
                )
            ),
        )

    if invariant.kind is InvariantKind.JSON_FIELD_EQUALS:
        text = _decode_text(content)
        if text is None:
            return _outcome(
                invariant,
                passed=False,
                observed={"$bytes_hex": content.hex()},
                reason=f"{label} is not valid UTF-8 JSON",
            )
        try:
            document = json.loads(text, parse_float=Decimal)
        except json.JSONDecodeError as exc:
            return _outcome(
                invariant,
                passed=False,
                observed="MALFORMED_JSON",
                reason=f"{label} is not valid JSON: {exc.msg} at {exc.pos}",
            )
        try:
            actual = _resolve_json_path(document, invariant._json_tokens())
        except (KeyError, IndexError, TypeError) as exc:
            return _outcome(
                invariant,
                passed=False,
                observed="MISSING_PATH",
                reason=f"json_path {invariant.json_path!r} not found in {label}: {exc}",
            )
        return _outcome(
            invariant,
            passed=_json_equal(actual, invariant.expected),
            observed=actual,
            reason=(
                f"{label} JSON field matched"
                if _json_equal(actual, invariant.expected)
                else f"{label} JSON field differs at {invariant.json_path}"
            ),
        )

    raise ValueError(f"Unsupported invariant kind {invariant.kind!r}")


def _records(content: bytes, record_length: int) -> list[bytes]:
    count = len(content) // record_length
    return [
        content[index * record_length:(index + 1) * record_length]
        for index in range(count)
    ]


def _numeric_token(field: bytes) -> str | None:
    try:
        token = field.decode("ascii").strip()
    except UnicodeDecodeError:
        return None
    return token if _SIGNED_INTEGER.match(token) else None


def _resolve_json_path(document: object, tokens: Sequence[str | int]) -> object:
    current = document
    for token in tokens:
        if isinstance(token, int):
            if not isinstance(current, list):
                raise TypeError(f"cannot index non-list with [{token}]")
            current = current[token]
        else:
            if not isinstance(current, Mapping):
                raise TypeError(f"cannot read {token!r} from non-object")
            current = current[token]
    return current


def _json_equal(actual: object, expected: object) -> bool:
    """Exact equality with Decimal-aware numeric comparison.

    ``Decimal('1.0') == 1`` is true, but no binary float is ever introduced,
    so an expectation of ``"1.10"`` cannot pass because of rounding.
    """
    if isinstance(actual, Decimal):
        if isinstance(expected, Decimal):
            return actual == expected
        if isinstance(expected, bool):
            return False
        if isinstance(expected, int):
            return actual == Decimal(expected)
        if isinstance(expected, str):
            try:
                return actual == Decimal(expected)
            except InvalidOperation:
                return False
        return False
    if isinstance(actual, int) and not isinstance(actual, bool):
        if isinstance(expected, Decimal):
            return Decimal(actual) == expected
        if isinstance(expected, str):
            try:
                return Decimal(actual) == Decimal(expected)
            except InvalidOperation:
                return False
    return actual == expected


def evaluate_invariants(
    invariants: Sequence[BusinessInvariant],
    observation: InvariantObservation,
) -> tuple[InvariantOutcome, ...]:
    """Evaluate every invariant against one observation, sorted by id."""
    ids = [invariant.invariant_id for invariant in invariants]
    duplicates = sorted({item for item in ids if ids.count(item) > 1})
    if duplicates:
        raise ValueError(f"Duplicate invariant_id(s): {duplicates}")
    return tuple(
        _evaluate_one(invariant, observation)
        for invariant in sorted(invariants, key=lambda item: item.invariant_id)
    )


def build_report(
    invariants: Sequence[BusinessInvariant],
    observation: InvariantObservation,
) -> BusinessInvariantReport:
    """Evaluate and package a canonical report for one execution side."""
    if not invariants:
        raise ValueError(
            "Cannot build a business-invariant report with no invariants: "
            "an empty report never certifies equivalence"
        )
    definitions = tuple(
        invariant.to_canonical_dict()
        for invariant in sorted(invariants, key=lambda item: item.invariant_id)
    )
    digest = hashlib.sha256(_canonical_json(list(definitions)).encode("utf-8")).hexdigest()
    outcomes = evaluate_invariants(invariants, observation)
    return BusinessInvariantReport(
        definition_digest=digest,
        definitions=definitions,
        outcomes=outcomes,
    )


# ---------------------------------------------------------------------------
# Report admission (used by the comparator)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AdmittedReport:
    """A report that passed structural and self-consistency checks."""

    definition_digest: str
    definitions: tuple[dict[str, Any], ...]
    overall: str
    outcomes: tuple[dict[str, Any], ...]


def admit_report(content: bytes) -> AdmittedReport:
    """Parse and fully re-verify a report before it can influence a verdict.

    Raises ``ValueError`` for any malformed or self-inconsistent report. The
    comparator turns that into ``INCONCLUSIVE`` (never ``MATCH``).
    """
    try:
        document = json.loads(
            content.decode("utf-8"), parse_float=Decimal
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"business-invariant report is not valid JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise ValueError("business-invariant report must be a JSON object")
    if document.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            f"unsupported business-invariant report schema_version "
            f"{document.get('schema_version')!r}"
        )
    definitions = document.get("definitions")
    outcomes = document.get("outcomes")
    digest = document.get("definition_digest")
    overall = document.get("overall")
    if not isinstance(definitions, list) or not definitions:
        raise ValueError("business-invariant report declares no definitions")
    if not isinstance(outcomes, list) or not outcomes:
        raise ValueError("business-invariant report declares no outcomes")
    if not isinstance(digest, str) or len(digest) != 64:
        raise ValueError("business-invariant report has an invalid definition_digest")
    if overall not in ("PASS", "FAIL"):
        raise ValueError(f"invalid overall status {overall!r}")

    canonical_definitions = [_canonical_definition(item) for item in definitions]
    recomputed = hashlib.sha256(
        _canonical_json(canonical_definitions).encode("utf-8")
    ).hexdigest()
    if recomputed != digest:
        raise ValueError(
            "business-invariant report definition_digest does not match its "
            "definitions"
        )

    canonical_outcomes = [_canonical_outcome(item) for item in outcomes]
    definition_ids = [str(item["invariant_id"]) for item in canonical_definitions]
    outcome_ids = [str(item["invariant_id"]) for item in canonical_outcomes]
    if sorted(definition_ids) != sorted(outcome_ids):
        raise ValueError(
            "business-invariant report outcomes do not match declared "
            "invariants exactly"
        )
    for outcome in canonical_outcomes:
        phase = outcome["phase"]
        if phase not in {item.value for item in InvariantPhase}:
            raise ValueError(f"invalid outcome phase {phase!r}")
        if outcome["kind"] not in {item.value for item in InvariantKind}:
            raise ValueError(f"invalid outcome kind {outcome['kind']!r}")
        if not isinstance(outcome["passed"], bool):
            raise ValueError("outcome passed must be a boolean")

    computed_overall = (
        "PASS" if all(item["passed"] for item in canonical_outcomes) else "FAIL"
    )
    if computed_overall != overall:
        raise ValueError(
            f"business-invariant report overall={overall!r} contradicts its "
            f"outcomes ({computed_overall})"
        )

    return AdmittedReport(
        definition_digest=digest,
        definitions=tuple(canonical_definitions),
        overall=overall,
        outcomes=tuple(canonical_outcomes),
    )


def _canonical_definition(item: object) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError("definition entries must be JSON objects")
    required = {
        "invariant_id", "kind", "source", "phase", "source_name", "expected",
        "record_length", "offset", "length", "record_index", "decimal_places",
        "json_path", "description",
    }
    if set(item) != required:
        raise ValueError(
            f"definition fields mismatch: missing={sorted(required - set(item))} "
            f"extra={sorted(set(item) - required)}"
        )
    if item["kind"] not in {entry.value for entry in InvariantKind}:
        raise ValueError(f"invalid definition kind {item['kind']!r}")
    if item["source"] not in {entry.value for entry in InvariantSource}:
        raise ValueError(f"invalid definition source {item['source']!r}")
    if item["phase"] not in {entry.value for entry in InvariantPhase}:
        raise ValueError(f"invalid definition phase {item['phase']!r}")
    return dict(item)


def _canonical_outcome(item: object) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError("outcome entries must be JSON objects")
    required = {
        "invariant_id", "phase", "kind", "passed", "expected", "observed",
        "reason",
    }
    if set(item) != required:
        raise ValueError(
            f"outcome fields mismatch: missing={sorted(required - set(item))} "
            f"extra={sorted(set(item) - required)}"
        )
    if not isinstance(item["reason"], str):
        raise ValueError("outcome reason must be a string")
    return dict(item)
