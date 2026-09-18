"""Transformation producer — COBOL to native Java.

The producer is the component that converts COBOL source into Java candidate
source. It is UNTRUSTED by the validation engine. The producer only generates
Java source; it does not validate, compare, or certify.

Architecture:

    COBOL source
        ↓
    CobolParser.parse()
        ↓
    CobolProgram IR
        ↓
    JavaGenerator.generate()
        ↓
    Generated Java source tree
        ↓
    ProducerManifest
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from engine.transformation.cobol_parser import CobolParseError, CobolParser
from engine.transformation.ir import CobolProgram
from engine.transformation.java_generator import GeneratedFile, JavaGenerator


class TransformationError(Exception):
    """Raised when transformation fails."""


@dataclass(frozen=True)
class TransformationResult:
    """Result of a COBOL-to-Java transformation."""
    success: bool
    generated_files: tuple[GeneratedFile, ...] = ()
    program_ir: CobolProgram | None = None
    errors: tuple[str, ...] = ()
    producer_identity: str = "cobol-to-java-transformer"
    producer_version: str = "1.0.0"
    transformation_timestamp: str = ""

    @property
    def java_source_tree(self) -> dict[str, str]:
        """Map of filename → source code."""
        return {f.filename: f.source_code for f in self.generated_files}


class TransformationProducer:
    """Produces Java candidates from COBOL source.

    This is the entry point for transformation. It orchestrates:
    1. COBOL parsing → IR
    2. IR → Java source generation
    3. Producer manifest generation

    The producer is UNTRUSTED. It does NOT:
    - Validate the generated Java
    - Compare against Oracle
    - Derive verdicts
    - Claim equivalence
    """

    def __init__(self) -> None:
        self._parser = CobolParser()
        self._generator = JavaGenerator()

    def transform(
        self,
        cobol_source: str,
        program_id: str = "UNKNOWN",
    ) -> TransformationResult:
        """Transform COBOL source to Java candidate.

        Args:
            cobol_source: The COBOL source code as a string.
            program_id: The COBOL program ID (used for class name).

        Returns:
            TransformationResult with generated files or errors.
        """
        timestamp = datetime.now(timezone.utc).isoformat()

        try:
            # Step 1: Parse COBOL → IR
            program = self._parser.parse(cobol_source)

            # Step 2: Generate Java from IR
            generated_files = self._generator.generate(program)

            return TransformationResult(
                success=True,
                generated_files=tuple(generated_files),
                program_ir=program,
                producer_identity="cobol-to-java-transformer",
                producer_version="1.0.0",
                transformation_timestamp=timestamp,
            )

        except CobolParseError as e:
            return TransformationResult(
                success=False,
                errors=(f"Parse error: {e}",),
                producer_identity="cobol-to-java-transformer",
                producer_version="1.0.0",
                transformation_timestamp=timestamp,
            )
        except (ValueError, KeyError, TypeError, AttributeError) as e:
            return TransformationResult(
                success=False,
                errors=(f"Transformation error: {e}",),
                producer_identity="cobol-to-java-transformer",
                producer_version="1.0.0",
                transformation_timestamp=timestamp,
            )

    def transform_to_directory(
        self,
        cobol_source: str,
        output_dir: str | Path,
        program_id: str = "UNKNOWN",
    ) -> TransformationResult:
        """Transform COBOL and write generated Java to a directory.

        Args:
            cobol_source: The COBOL source code as a string.
            output_dir: Directory to write generated Java files.
            program_id: The COBOL program ID.

        Returns:
            TransformationResult with file paths.
        """
        result = self.transform(cobol_source, program_id)
        if not result.success:
            return result

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        for gen_file in result.generated_files:
            file_path = output_path / gen_file.filename
            file_path.write_text(gen_file.source_code, encoding="utf-8")

        return result

    def compute_source_hash(self, cobol_source: str) -> str:
        """Compute SHA-256 hash of COBOL source."""
        return hashlib.sha256(cobol_source.encode("utf-8")).hexdigest()

    def generate_manifest(
        self,
        result: TransformationResult,
        cobol_source: str,
        source_path: str,
    ) -> dict:
        """Generate producer manifest for the transformation.

        The manifest is metadata about the transformation process.
        It is NOT equivalence evidence.
        """
        if not result.success:
            return {
                "producer_identity": result.producer_identity,
                "producer_version": result.producer_version,
                "success": False,
                "errors": list(result.errors),
            }

        # Compute file hashes
        generated_files_manifest = {}
        for filename, source in result.java_source_tree.items():
            file_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
            generated_files_manifest[filename] = f"sha256:{file_hash}"

        return {
            "producer_identity": result.producer_identity,
            "producer_version": result.producer_version,
            "success": True,
            "source_hash": f"sha256:{self.compute_source_hash(cobol_source)}",
            "source_path": source_path,
            "program_id": result.program_ir.program_id if result.program_ir else "UNKNOWN",
            "generated_files": generated_files_manifest,
            "entrypoint": result.generated_files[0].class_name if result.generated_files else "Unknown",
            "java_version": "17",
            "supported_scope": "Generic COBOL semantic constructs: MOVE, ADD, IF/ELSE, DISPLAY, FILE I/O, UNSTRING, PERFORM, STOP RUN",
            "transformation_timestamp": result.transformation_timestamp,
            "mutation_regeneration_capability": True,
        }
