"""Candidate subsystem for the validation engine."""

from engine.candidate.adapter import (
    CandidateAdapter,
    CandidateExecutionResult,
    CandidateManifest,
    CompilationResult,
    PlainJavaCandidateAdapter,
)

__all__ = [
    "CandidateAdapter",
    "CandidateExecutionResult",
    "CandidateManifest",
    "CompilationResult",
    "PlainJavaCandidateAdapter",
]
