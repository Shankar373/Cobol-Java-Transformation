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
from engine.transformation.cobol_parser import CobolParser
from engine.transformation.diagnostics import DiagnosticCollector
from engine.transformation.java_generator import JavaGenerator
from engine.transformation.semantic_capability import (
    CONSTRUCT_REGISTRY,
    CapabilityLevel,
)


# Structural constructs this producer understands that are not verbs in the
# authoritative semantic capability registry (see
# engine/transformation/semantic_capability.py).  They are kept as an explicit
# producer-scope declaration because the registry classifies semantics, not
# divisions or picture clauses.
_SUPPORTED_STRUCTURE: tuple[str, ...] = (
    "IDENTIFICATION DIVISION",
    "ENVIRONMENT DIVISION",
    "FILE-CONTROL",
    "DATA DIVISION",
    "FILE SECTION",
    "WORKING-STORAGE",
    "PIC X(n)",
    "PIC 9(n)",
)

# Producer-scope limitations that have no standalone registry key: file
# organizations are classified through their file verbs, so the registry does
# not carry an "INDEXED files"/"RELATIVE files" entry.
_UNSUPPORTED_SCOPE: tuple[str, ...] = (
    "INDEXED files",
    "RELATIVE files",
)


def _registry_constructs(level: CapabilityLevel) -> tuple[str, ...]:
    """Return the sorted registry construct names for one capability level.

    The registry is the single source of capability truth (see Master README
    Section 14 and docs/COBOL_UNIVERSALITY_ROADMAP.md P0-1).  Deriving the
    producer's declared lists from it makes a producer claim that contradicts
    the registry impossible by construction.
    """
    return tuple(
        sorted(
            name
            for name, entry in CONSTRUCT_REGISTRY.items()
            if entry.level is level
        )
    )


# Computed once: the registry is static.  Supported and unsupported lists only
# carry constructs whose registry level is exactly SUPPORTED/UNSUPPORTED; a
# PARTIAL construct (e.g. UNSTRING) is deliberately in neither list so the
# producer never reports a bounded construct as fully supported or rejected.
_PRODUCER_SUPPORTED_CONSTRUCTS: tuple[str, ...] = (
    _SUPPORTED_STRUCTURE + _registry_constructs(CapabilityLevel.SUPPORTED)
)
_PRODUCER_UNSUPPORTED_CONSTRUCTS: tuple[str, ...] = (
    _UNSUPPORTED_SCOPE + _registry_constructs(CapabilityLevel.UNSUPPORTED)
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
                supported_constructs=_PRODUCER_SUPPORTED_CONSTRUCTS,
                unsupported_constructs=_PRODUCER_UNSUPPORTED_CONSTRUCTS,
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
