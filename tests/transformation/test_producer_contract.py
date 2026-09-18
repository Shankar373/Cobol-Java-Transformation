"""Producer contract tests.

Verifies that all producers implement the TransformationProducer interface
correctly and that the producer abstraction maintains separation from
the validation engine.
"""

from __future__ import annotations

import pytest

from engine.transformation.contracts import (
    GeneratedFile,
    ProducerCapability,
    TransformationProducer,
    TransformationResult,
    TransformationStatus,
)
from engine.transformation.producers.internal_native import InternalNativeJavaProducer


class TestProducerContract:
    """Verify TransformationProducer interface compliance."""

    def test_internal_producer_implements_interface(self):
        """InternalNativeJavaProducer implements TransformationProducer."""
        producer = InternalNativeJavaProducer()
        assert isinstance(producer, TransformationProducer)

    def test_internal_producer_has_identity(self):
        """Producer provides identity."""
        producer = InternalNativeJavaProducer()
        name, version = producer.get_identity()
        assert name
        assert version

    def test_internal_producer_has_capabilities(self):
        """Producer declares capabilities."""
        producer = InternalNativeJavaProducer()
        caps = producer.get_capabilities()
        assert len(caps) > 0
        assert ProducerCapability.NATIVE_JAVA in caps

    def test_internal_producer_no_runtime_requirements(self):
        """Internal producer has no COBOL runtime requirements."""
        producer = InternalNativeJavaProducer()
        reqs = producer.get_runtime_requirements()
        assert reqs == ()

    def test_transform_returns_result(self):
        """transform() returns TransformationResult."""
        producer = InternalNativeJavaProducer()
        from pathlib import Path
        cobol_source = Path("fixtures/workload-claims/cobol/CLAIMS.cob").read_text()
        result = producer.transform(cobol_source, program_id="CLAIMS")
        assert isinstance(result, TransformationResult)

    def test_transform_success_has_files(self):
        """Successful transformation produces generated files."""
        producer = InternalNativeJavaProducer()
        from pathlib import Path
        cobol_source = Path("fixtures/workload-claims/cobol/CLAIMS.cob").read_text()
        result = producer.transform(cobol_source, program_id="CLAIMS")
        assert result.status.value in ("SUCCESS", "PARTIAL")
        assert len(result.generated_files) > 0

    def test_transform_success_has_entrypoint(self):
        """Successful transformation has entrypoint class."""
        producer = InternalNativeJavaProducer()
        from pathlib import Path
        cobol_source = Path("fixtures/workload-claims/cobol/CLAIMS.cob").read_text()
        result = producer.transform(cobol_source, program_id="CLAIMS")
        assert result.entrypoint

    def test_transform_producer_identity_set(self):
        """Result contains producer identity."""
        producer = InternalNativeJavaProducer()
        from pathlib import Path
        cobol_source = Path("fixtures/workload-claims/cobol/CLAIMS.cob").read_text()
        result = producer.transform(cobol_source, program_id="CLAIMS")
        assert result.producer_identity == "internal-native-java-producer"

    def test_transform_no_certification_in_result(self):
        """Result does NOT contain authoritative certification."""
        producer = InternalNativeJavaProducer()
        from pathlib import Path
        cobol_source = Path("fixtures/workload-claims/cobol/CLAIMS.cob").read_text()
        result = producer.transform(cobol_source, program_id="CLAIMS")
        # The result should NOT claim VERIFIED, PASS, or CERTIFIED
        assert not hasattr(result, 'verdict')
        assert not hasattr(result, 'is_equivalent')
        assert not hasattr(result, 'certified')

    def test_transform_tolerant_on_invalid_source(self):
        """Parser is tolerant: invalid COBOL returns FAILED, not exception.

        The parser does not raise on invalid input. Instead, it returns
        a FAILED result with a PARSE_ERROR diagnostic. This is safe:
        no exception leaks, and the caller receives explicit failure status.
        """
        producer = InternalNativeJavaProducer()
        result = producer.transform("INVALID COBOL SOURCE", program_id="BAD")
        # Parser is tolerant — returns FAILED with diagnostic (no exception)
        assert result.status.value == "FAILED"
        assert len(result.diagnostics) > 0
        assert result.diagnostics[0]["level"] == "ERROR"
        assert "PARSE_ERROR" in result.diagnostics[0]["code"]

    def test_java_source_tree_property(self):
        """java_source_tree returns filename→source mapping."""
        producer = InternalNativeJavaProducer()
        from pathlib import Path
        cobol_source = Path("fixtures/workload-claims/cobol/CLAIMS.cob").read_text()
        result = producer.transform(cobol_source, program_id="CLAIMS")
        tree = result.java_source_tree
        assert isinstance(tree, dict)
        assert len(tree) > 0

    def test_supported_constructs_populated(self):
        """Result lists supported constructs."""
        producer = InternalNativeJavaProducer()
        from pathlib import Path
        cobol_source = Path("fixtures/workload-claims/cobol/CLAIMS.cob").read_text()
        result = producer.transform(cobol_source, program_id="CLAIMS")
        assert len(result.supported_constructs) > 0

    def test_unsupported_constructs_populated(self):
        """Result lists unsupported constructs."""
        producer = InternalNativeJavaProducer()
        from pathlib import Path
        cobol_source = Path("fixtures/workload-claims/cobol/CLAIMS.cob").read_text()
        result = producer.transform(cobol_source, program_id="CLAIMS")
        assert len(result.unsupported_constructs) > 0

    def test_metadata_has_standalone_flag(self):
        """Result metadata indicates standalone Java."""
        producer = InternalNativeJavaProducer()
        from pathlib import Path
        cobol_source = Path("fixtures/workload-claims/cobol/CLAIMS.cob").read_text()
        result = producer.transform(cobol_source, program_id="CLAIMS")
        assert result.metadata.get("standalone_java") is True
        assert result.metadata.get("cobol_runtime_required") is False


# ---------------------------------------------------------------------------
# Negative transformation tests (A-F)
# ---------------------------------------------------------------------------

class TestTransformationNegative:
    """Prove invalid/unsupported COBOL produces explicit failure status."""

    def test_empty_source_returns_failed(self):
        """TEST A: empty source -> FAILED."""
        producer = InternalNativeJavaProducer()
        result = producer.transform("", program_id="EMPTY")
        assert result.status == TransformationStatus.FAILED
        assert len(result.diagnostics) > 0
        assert result.diagnostics[0]["level"] == "ERROR"

    def test_random_text_returns_failed(self):
        """TEST B: random non-COBOL text -> FAILED."""
        producer = InternalNativeJavaProducer()
        result = producer.transform(
            "The quick brown fox jumps over the lazy dog",
            program_id="RANDOM",
        )
        assert result.status == TransformationStatus.FAILED
        assert len(result.diagnostics) > 0
        assert result.diagnostics[0]["code"] == "PARSE_ERROR"

    def test_missing_identification_division_returns_failed(self):
        """TEST C: missing IDENTIFICATION DIVISION -> FAILED."""
        producer = InternalNativeJavaProducer()
        result = producer.transform("DISPLAY HELLO.\nSTOP RUN.", program_id="NOID")
        assert result.status == TransformationStatus.FAILED
        assert len(result.diagnostics) > 0

    def test_valid_with_unsupported_compute_returns_partial(self):
        """TEST D: valid structure + unsupported COMPUTE -> PARTIAL."""
        producer = InternalNativeJavaProducer()
        source = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST-COMPUTE.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-X PIC 9(4) VALUE 100.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-LOGIC.\n"
            "           COMPUTE WS-X = WS-X * 2\n"
            "           DISPLAY WS-X\n"
            "           STOP RUN.\n"
        )
        result = producer.transform(source, program_id="TEST-COMPUTE")
        assert result.status == TransformationStatus.SUCCESS
        codes = [d["code"] for d in result.diagnostics]
        # COMPUTE is now fully supported, no UNSUPPORTED_CONSTRUCT
        assert "UNSUPPORTED_CONSTRUCT" not in codes

    def test_claims_cobol_returns_partial(self):
        """TEST E: valid Claims COBOL + unsupported constructs -> PARTIAL."""
        from pathlib import Path
        producer = InternalNativeJavaProducer()
        cobol = Path("fixtures/workload-claims/cobol/CLAIMS.cob").read_text()
        result = producer.transform(cobol, program_id="CLAIMS")
        assert result.status == TransformationStatus.PARTIAL
        assert len(result.diagnostics) > 0
        codes = [d["code"] for d in result.diagnostics]
        assert "UNSUPPORTED_CONSTRUCT" in codes

    def test_valid_minimal_cobol_returns_success(self):
        """TEST F: valid fully supported minimal COBOL -> SUCCESS."""
        producer = InternalNativeJavaProducer()
        source = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. MINIMAL.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-COUNT PIC 9(4) VALUE 0.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-LOGIC.\n"
            "           MOVE 42 TO WS-COUNT\n"
            "           DISPLAY WS-COUNT\n"
            "           STOP RUN.\n"
        )
        result = producer.transform(source, program_id="MINIMAL")
        assert result.status == TransformationStatus.SUCCESS
        assert len(result.diagnostics) == 0
