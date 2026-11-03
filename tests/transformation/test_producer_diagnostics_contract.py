"""BL-042: every producer emits real `contracts.Diagnostic` instances.

`TransformationResult.diagnostics` is declared as
`tuple[Diagnostic, ...]` where `Diagnostic` is the contracts dataclass
with **string** level/code.  The internal-native producer emitted plain
dicts (attribute access crashes `has_errors`/`has_warnings`) and the
OpenSourceCOBOL4J adapter emitted engine diagnostics with **enum**
levels/codes (attribute access works, but `has_errors`/`has_warnings`
compare `d.level == "ERROR"` against a `DiagnosticLevel` enum and
silently mis-report `False` for real ERROR diagnostics).

These tests prove both violations first (red), then pin the fix: every
diagnostic leaving a producer is a `contracts.Diagnostic`; attribute
access and `has_errors`/`has_warnings` equivalence hold identically for
all producers.
"""

from engine.transformation.contracts import Diagnostic, TransformationStatus
from engine.transformation.producers.internal_native import (
    InternalNativeJavaProducer,
)
from engine.transformation.producers.opensource4j import (
    OpenSourceCOBOL4JProducerAdapter,
)

INVALID = "INVALID COBOL SOURCE"

MINIMAL_VALID = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. CONTRACT-TEST.\n"
    "       DATA DIVISION.\n"
    "       WORKING-STORAGE SECTION.\n"
    "       01 WS-X PIC 9(4) VALUE 1.\n"
    "       PROCEDURE DIVISION.\n"
    "       MAIN-LOGIC.\n"
    "           DISPLAY WS-X\n"
    "           STOP RUN.\n"
)


def _assert_contract_shape(result) -> None:
    kinds = [type(d).__name__ for d in result.diagnostics]
    assert all(isinstance(d, Diagnostic) for d in result.diagnostics), kinds
    for d in result.diagnostics:
        assert isinstance(d.level, str)
        assert isinstance(d.code, str)
        assert isinstance(d.message, str)


def test_internal_native_invalid_source_emits_contract_diagnostics():
    """Attribute access must work on every producer diagnostic."""
    result = InternalNativeJavaProducer().transform(INVALID, program_id="BAD")

    assert result.status == TransformationStatus.FAILED
    _assert_contract_shape(result)
    assert result.diagnostics[0].level == "ERROR"
    assert "PARSE_ERROR" in result.diagnostics[0].code


def test_internal_native_invalid_source_reports_has_errors_truthfully():
    """has_errors must be True when an ERROR diagnostic is present."""
    result = InternalNativeJavaProducer().transform(INVALID, program_id="BAD")

    assert result.has_errors is True
    assert result.has_errors == any(d.level == "ERROR" for d in result.diagnostics)
    assert result.has_warnings == any(
        d.level == "WARNING" for d in result.diagnostics
    )


def test_internal_native_valid_source_diagnostics_are_contract_objects():
    """A clean transform still exposes the declared diagnostics contract."""
    result = InternalNativeJavaProducer().transform(
        MINIMAL_VALID, program_id="CONTRACT-TEST"
    )

    assert result.status == TransformationStatus.SUCCESS
    _assert_contract_shape(result)
    assert result.has_errors is False


def test_internal_native_exception_path_emits_contract_diagnostic(monkeypatch):
    """The internal error path must not smuggle a dict past the contract."""
    producer = InternalNativeJavaProducer()

    def boom(*args, **kwargs):
        raise ValueError("synthetic generator failure")

    monkeypatch.setattr(type(producer._generator), "generate", boom)

    result = producer.transform(MINIMAL_VALID, program_id="CONTRACT-TEST")

    assert result.status == TransformationStatus.FAILED
    _assert_contract_shape(result)
    assert result.diagnostics[0].level == "ERROR"
    assert result.diagnostics[0].code == "TRANSFORMATION_ERROR"
    assert result.has_errors is True


def test_opensource4j_without_docker_reports_error_truthfully():
    """The adapter's no-Docker failure must set has_errors (enum bug today)."""
    result = OpenSourceCOBOL4JProducerAdapter(use_docker=False).transform(
        MINIMAL_VALID, program_id="CONTRACT-TEST"
    )

    assert result.status == TransformationStatus.FAILED
    _assert_contract_shape(result)
    assert result.diagnostics[0].level == "ERROR"
    assert result.has_errors is True


def test_has_errors_has_warnings_equivalence_across_producers():
    """One rule for both producers: flags mirror the diagnostic levels."""
    native_bad = InternalNativeJavaProducer().transform(INVALID, program_id="BAD")
    adapter_bad = OpenSourceCOBOL4JProducerAdapter(use_docker=False).transform(
        INVALID, program_id="BAD"
    )

    for result in (native_bad, adapter_bad):
        _assert_contract_shape(result)
        assert result.has_errors == any(d.level == "ERROR" for d in result.diagnostics)
        assert result.has_warnings == any(
            d.level == "WARNING" for d in result.diagnostics
        )
        assert result.has_errors is True
