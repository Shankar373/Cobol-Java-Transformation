"""OpenSourceCOBOL4J adapter — external/alternative producer.

This adapter wraps OpenSourceCOBOL4J as an external transformation producer.
It is NOT part of the core transformation implementation.

CRITICAL: Generated Java requires libcobj.jar (COBOL-specific runtime).
Therefore: standalone_native_java = PARTIAL

Architecture:

    COBOL source
        ↓
    OpenSourceCOBOL4J (external tool)
        ↓
    Generated Java (requires libcobj.jar)
        ↓
    TransformationResult (with runtime requirements)
"""

from __future__ import annotations

import hashlib
import subprocess
import tempfile
from pathlib import Path

from engine.transformation.contracts import (
    GeneratedFile,
    ProducerCapability,
    TransformationProducer,
    TransformationResult,
    TransformationStatus,
)
from engine.transformation.diagnostics import Diagnostic, DiagnosticCode


class OpenSourceCOBOL4JProducerAdapter(TransformationProducer):
    """Adapter for OpenSourceCOBOL4J as an external producer.

    This adapter exposes OpenSourceCOBOL4J through the standard producer
    interface. Generated Java requires libcobj.jar at runtime.

    CRITICAL: This producer does NOT satisfy the standalone native Java
    requirement. It is classified as an alternative/benchmark producer.
    """

    PRODUCER_IDENTITY = "opensourcecobol4j-adapter"
    PRODUCER_VERSION = "2.1.0"
    DOCKER_IMAGE = "opensourcecobol/opensourcecobol4j:2.1.0"

    def __init__(self, use_docker: bool = True) -> None:
        self._use_docker = use_docker

    def transform(
        self,
        cobol_source: str,
        program_id: str = "UNKNOWN",
    ) -> TransformationResult:
        """Transform COBOL source using OpenSourceCOBOL4J.

        NOTE: This requires Docker and the OpenSourceCOBOL4J image.
        Generated Java requires libcobj.jar at runtime.
        """
        if not self._use_docker:
            return TransformationResult(
                status=TransformationStatus.FAILED,
                producer_identity=self.PRODUCER_IDENTITY,
                producer_version=self.PRODUCER_VERSION,
                diagnostics=(
                    Diagnostic.error(
                        DiagnosticCode.GENERATION_ERROR,
                        "OpenSourceCOBOL4J adapter requires Docker",
                    ),
                ),
            )

        try:
            # Write COBOL source to temp file
            with tempfile.TemporaryDirectory() as tmpdir:
                cobol_path = Path(tmpdir) / f"{program_id}.cob"
                cobol_path.write_text(cobol_source, encoding="utf-8")

                # Run cobj via Docker
                result = subprocess.run(
                    [
                        "docker", "run", "--rm",
                        "-v", f"{tmpdir}:/cobol",
                        self.DOCKER_IMAGE,
                        "cobj", f"/cobol/{program_id}.cob",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )

                if result.returncode != 0:
                    return TransformationResult(
                        status=TransformationStatus.FAILED,
                        producer_identity=self.PRODUCER_IDENTITY,
                        producer_version=self.PRODUCER_VERSION,
                        diagnostics=(
                            Diagnostic.error(
                                DiagnosticCode.GENERATION_ERROR,
                                f"OpenSourceCOBOL4J compilation failed: {result.stderr}",
                            ),
                        ),
                    )

                # Read generated Java
                java_path = Path(tmpdir) / f"{program_id}.java"
                if not java_path.exists():
                    return TransformationResult(
                        status=TransformationStatus.FAILED,
                        producer_identity=self.PRODUCER_IDENTITY,
                        producer_version=self.PRODUCER_VERSION,
                        diagnostics=(
                            Diagnostic.error(
                                DiagnosticCode.GENERATION_ERROR,
                                "OpenSourceCOBOL4J did not generate Java file",
                            ),
                        ),
                    )

                java_source = java_path.read_text(encoding="utf-8")

                return TransformationResult(
                    status=TransformationStatus.SUCCESS,
                    generated_files=(
                        GeneratedFile(
                            filename=f"{program_id}.java",
                            source_code=java_source,
                            language="java",
                        ),
                    ),
                    entrypoint=program_id,
                    producer_identity=self.PRODUCER_IDENTITY,
                    producer_version=self.PRODUCER_VERSION,
                    supported_constructs=(
                        "IDENTIFICATION DIVISION",
                        "ENVIRONMENT DIVISION",
                        "FILE-CONTROL",
                        "DATA DIVISION",
                        "FILE SECTION",
                        "WORKING-STORAGE",
                        "PIC X(n)",
                        "PIC 9(n)",
                        "OCCURS",
                        "OPEN",
                        "READ",
                        "WRITE",
                        "MOVE",
                        "ADD",
                        "IF/ELSE",
                        "PERFORM",
                        "DISPLAY",
                        "GO TO",
                        "STOP RUN",
                        "STRING",
                        "UNSTRING",
                        "SORT",
                        "CALL",
                        "INDEXED files",
                        "RELATIVE files",
                    ),
                    unsupported_constructs=(),
                    metadata={
                        "source_hash": self._compute_hash(cobol_source),
                        "standalone_java": False,
                        "cobol_runtime_required": True,
                        "runtime_dependency": "libcobj.jar",
                        "runtime_license": "LGPL-3.0",
                        "compiler_license": "GPL-3.0",
                        "docker_image": self.DOCKER_IMAGE,
                    },
                )

        except subprocess.TimeoutExpired:
            return TransformationResult(
                status=TransformationStatus.FAILED,
                producer_identity=self.PRODUCER_IDENTITY,
                producer_version=self.PRODUCER_VERSION,
                diagnostics=(
                    Diagnostic.error(
                        DiagnosticCode.GENERATION_ERROR,
                        "OpenSourceCOBOL4J compilation timed out",
                    ),
                ),
            )
        except Exception as e:
            return TransformationResult(
                status=TransformationStatus.FAILED,
                producer_identity=self.PRODUCER_IDENTITY,
                producer_version=self.PRODUCER_VERSION,
                diagnostics=(
                    Diagnostic.error(
                        DiagnosticCode.GENERATION_ERROR,
                        f"OpenSourceCOBOL4J adapter error: {e}",
                    ),
                ),
            )

    def get_capabilities(self) -> tuple[ProducerCapability, ...]:
        return (
            ProducerCapability.SEQUENTIAL_FILES,
            ProducerCapability.INDEXED_FILES,
            ProducerCapability.RELATIVE_FILES,
            ProducerCapability.SORT_STATEMENTS,
            ProducerCapability.CALL_STATEMENTS,
        )

    def get_identity(self) -> tuple[str, str]:
        return (self.PRODUCER_IDENTITY, self.PRODUCER_VERSION)

    def get_runtime_requirements(self) -> tuple[str, ...]:
        return ("libcobj.jar",)  # COBOL-specific runtime required

    def _compute_hash(self, source: str) -> str:
        return hashlib.sha256(source.encode("utf-8")).hexdigest()
