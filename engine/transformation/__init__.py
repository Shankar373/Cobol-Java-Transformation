"""Transformation platform — COBOL to native Java.

This module provides the modular transformation platform architecture:

    contracts.py          - Producer interface and result types
    source_model.py       - COBOL AST/semantic model
    cobol_parser.py       - COBOL source → IR
    ir.py                 - Intermediate representation
    java_generator.py     - IR → Java source
    diagnostics.py        - Diagnostic messages
    manifest.py           - Producer manifest
    producers/            - Producer implementations
        internal_native.py    - Primary standalone native Java
        opensource4j.py       - OpenSourceCOBOL4J adapter

Architecture:

    COBOL source
        ↓
    TransformationProducer (interface)
        ↓
    TransformationResult
        ↓
    Validation Engine (independent)
"""

from engine.transformation.contracts import (
    GeneratedFile,
    ProducerCapability,
    TransformationProducer,
    TransformationResult,
    TransformationStatus,
)
from engine.transformation.diagnostics import Diagnostic, DiagnosticCode, DiagnosticLevel
from engine.transformation.manifest import ProducerManifest

__all__ = [
    # Contracts
    "TransformationProducer",
    "TransformationResult",
    "TransformationStatus",
    "GeneratedFile",
    "ProducerCapability",
    # Diagnostics
    "Diagnostic",
    "DiagnosticCode",
    "DiagnosticLevel",
    # Manifest
    "ProducerManifest",
]
