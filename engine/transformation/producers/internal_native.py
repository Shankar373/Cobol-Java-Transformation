"""Internal Native Java Producer — primary transformation technology.

This is the project's own COBOL→native-Java transformation producer.
It generates standalone Java that requires only standard JDK/JVM.

Architecture:

    COBOL source
        ↓
    CobolParser.parse()
        ↓
    CobolProgram IR
        ↓
    JavaGenerator.generate()
        ↓
    Generated Java source (standalone, no COBOL runtime)
"""

from __future__ import annotations

from engine.transformation.contracts import (
    GeneratedFile,
    ProducerCapability,
    TransformationProducer,
    TransformationResult,
    TransformationStatus,
)
from engine.transformation.cobol_parser import CobolParseError, CobolParser
from engine.transformation.diagnostics import DiagnosticCollector
from engine.transformation.java_generator import JavaGenerator

# Capability metadata for this producer. These lists must stay disjoint and
# must agree with the actual lowering in cobol_to_java_mapping.py and with
# the generated Java (each entry below was checked against emitted code):
#   supported   — lowered to Java with full observable semantics
#   partial     — lowered, but semantics are incomplete or degraded
#   unsupported — no working semantic Java lowering (skipped, comment-only,
#                 rejected by the parser, or emits non-compiling Java)
# This is a static declaration about the producer's language coverage; it is
# NOT a certification of any particular transformation.
_SUPPORTED_CONSTRUCTS = (
    "IDENTIFICATION DIVISION",
    "ENVIRONMENT DIVISION",
    "FILE-CONTROL",
    "DATA DIVISION",
    "FILE SECTION",
    "WORKING-STORAGE",
    "PIC X(n)",
    "PIC 9(n)",
    "OPEN",
    "READ",
    "WRITE",
    "MOVE",
    "ADD",
    "SUBTRACT",
    "MULTIPLY",
    "DIVIDE ... BY ... GIVING",
    "COMPUTE",
    "IF/ELSE",
    "PERFORM",
    "DISPLAY",
    "STOP RUN",
    "CALL (static literal target)",
)

# Partially lowered constructs. EVALUATE is declared partial, not supported:
# the subject form with arm bodies on their own lines lowers correctly, but
# `EVALUATE TRUE` and arm bodies written on the WHEN line are flattened into
# an invalid condition, so not every EVALUATE form is safe to transform.
_PARTIAL_CONSTRUCTS = (
    "OCCURS",
    "STRING",
    "UNSTRING",
    "EVALUATE",
)

_UNSUPPORTED_CONSTRUCTS = (
    "SORT",
    "ACCEPT",
    "CLOSE",
    "INDEXED files",
    "RELATIVE files",
    "GO TO",
    "dynamic CALL",
    "DIVIDE ... INTO",
)


class InternalNativeJavaProducer(TransformationProducer):
    """Primary transformation producer — generates standalone native Java.

    This producer generates Java that:
    - Uses only standard Java libraries (java.io, java.util)
    - Has no COBOL runtime dependency
    - Reads actual workload input files
    - Produces the same output artifacts as the COBOL program

    Scope: Generic COBOL semantic subset. Not a universal COBOL translator.
    """

    PRODUCER_IDENTITY = "internal-native-java-producer"
    PRODUCER_VERSION = "1.0.0"

    def __init__(self) -> None:
        self._generator = JavaGenerator()

    def transform(
        self,
        cobol_source: str,
        program_id: str = "UNKNOWN",
    ) -> TransformationResult:
        """Transform COBOL source to standalone native Java."""
        diagnostics = DiagnosticCollector()
        try:
            # Step 1: Parse COBOL → IR (with diagnostics)
            parser = CobolParser(diagnostics=diagnostics)
            program = parser.parse(cobol_source)

            # Step 2: Generate Java from IR
            generated_files = self._generator.generate(program)

            # Step 3: Determine status based on diagnostics
            if diagnostics.has_errors:
                status = TransformationStatus.FAILED
            elif diagnostics.has_warnings:
                status = TransformationStatus.PARTIAL
            else:
                status = TransformationStatus.SUCCESS

            # Step 4: Build result
            return TransformationResult(
                status=status,
                generated_files=tuple(
                    GeneratedFile(
                        filename=f.filename,
                        source_code=f.source_code,
                        language="java",
                    )
                    for f in generated_files
                ),
                entrypoint=generated_files[0].class_name if generated_files else "",
                producer_identity=self.PRODUCER_IDENTITY,
                producer_version=self.PRODUCER_VERSION,
                supported_constructs=_SUPPORTED_CONSTRUCTS,
                unsupported_constructs=_UNSUPPORTED_CONSTRUCTS,
                partial_constructs=_PARTIAL_CONSTRUCTS,
                diagnostics=tuple(
                    {
                        "level": d.level.value,
                        "code": d.code.value,
                        "message": d.message,
                        "location": d.location,
                    }
                    for d in diagnostics.all
                ),
                metadata={
                    "source_hash": self._compute_hash(cobol_source),
                    "standalone_java": True,
                    "cobol_runtime_required": False,
                },
            )

        except CobolParseError as exc:
            return TransformationResult(
                status=TransformationStatus.FAILED,
                producer_identity=self.PRODUCER_IDENTITY,
                producer_version=self.PRODUCER_VERSION,
                diagnostics=tuple({
                    "level": diagnostic.level.value,
                    "code": diagnostic.code.value,
                    "message": diagnostic.message,
                    "location": diagnostic.location,
                } for diagnostic in exc.diagnostics),
            )
        except Exception as e:
            return TransformationResult(
                status=TransformationStatus.FAILED,
                producer_identity=self.PRODUCER_IDENTITY,
                producer_version=self.PRODUCER_VERSION,
                diagnostics=(
                    {
                        "level": "ERROR",
                        "code": "TRANSFORMATION_ERROR",
                        "message": str(e),
                    },
                ),
            )

    def get_capabilities(self) -> tuple[ProducerCapability, ...]:
        return (
            ProducerCapability.NATIVE_JAVA,
            ProducerCapability.SEQUENTIAL_FILES,
            ProducerCapability.SOURCE_DRIVEN,
        )

    def get_identity(self) -> tuple[str, str]:
        return (self.PRODUCER_IDENTITY, self.PRODUCER_VERSION)

    def get_runtime_requirements(self) -> tuple[str, ...]:
        return ()  # Standalone — no COBOL runtime

    def _compute_hash(self, source: str) -> str:
        import hashlib
        return hashlib.sha256(source.encode("utf-8")).hexdigest()
