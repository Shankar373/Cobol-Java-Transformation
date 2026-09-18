"""Workload declaration model for multi-artifact validation.

Defines the contract between workload definitions and the validation engine.
The pipeline consumes WorkloadDefinition to drive artifact capture and comparison.
Artifact type is determined by declaration, NOT by filename extension.

This is the authoritative mechanism for workload generality:
- Payroll-specific knowledge lives in the workload declaration, NOT in engine code
- The same pipeline handles any workload with a valid declaration
- Adding a new workload means creating a WorkloadDefinition, NOT editing pipeline.py
"""

from __future__ import annotations

from dataclasses import dataclass

from engine.contracts.models import (
    FailurePolicy,
    NormalizationPolicy,
    OrderingPolicy,
)


@dataclass(frozen=True)
class WorkloadInput:
    """Declares a single input file for a workload."""

    logical_name: str
    container_path: str  # e.g. "/workspace/input/claims.dat"
    source_path: str  # relative to workload fixture dir

    def __post_init__(self) -> None:
        if not self.logical_name:
            raise ValueError("logical_name cannot be empty")
        if not self.container_path:
            raise ValueError("container_path cannot be empty")
        if not self.source_path:
            raise ValueError("source_path cannot be empty")


@dataclass(frozen=True)
class WorkloadArtifact:
    """Declares a single artifact to capture and compare.

    This is the unit of workload configuration. Each artifact:
    - Has a logical name for human identification
    - Specifies an artifact type (must match a registered comparator)
    - For file-based artifacts, specifies the output path
    - Specifies which comparator to use (by ID)
    - Specifies normalization, ordering, and failure policies
    - For FIXED_RECORD, specifies the expected record length
    """

    logical_name: str
    artifact_type: str  # STDOUT, STDERR, EXIT_STATUS, TEXT_FILE, FIXED_RECORD
    comparator_id: str  # must match a registered comparator ID
    output_path: str | None = None  # for TEXT_FILE / FIXED_RECORD only
    normalization: NormalizationPolicy | None = None
    ordering: OrderingPolicy | None = None
    failure: FailurePolicy | None = None
    record_length: int | None = None  # FIXED_RECORD only; None = byte-level

    def __post_init__(self) -> None:
        valid_types = {"STDOUT", "STDERR", "EXIT_STATUS", "TEXT_FILE", "FIXED_RECORD"}
        if self.artifact_type not in valid_types:
            raise ValueError(
                f"Invalid artifact_type={self.artifact_type!r}. "
                f"Valid: {sorted(valid_types)}"
            )
        if self.artifact_type in ("TEXT_FILE", "FIXED_RECORD") and self.output_path is None:
            raise ValueError(
                f"artifact_type={self.artifact_type!r} requires output_path"
            )
        if self.artifact_type == "FIXED_RECORD" and self.record_length is not None and self.record_length <= 0:
                raise ValueError(
                    f"record_length must be > 0, got {self.record_length}"
                )


@dataclass(frozen=True)
class WorkloadDefinition:
    """Declares a complete workload for validation.

    Contains workload identity, input file declarations, and the ordered
    list of artifacts to capture and compare.
    """

    workload_id: str
    description: str
    artifacts: tuple[WorkloadArtifact, ...]
    inputs: tuple[WorkloadInput, ...] = ()

    def __post_init__(self) -> None:
        if not self.artifacts:
            raise ValueError("At least one artifact must be declared")

    def get_artifact(self, logical_name: str) -> WorkloadArtifact:
        for a in self.artifacts:
            if a.logical_name == logical_name:
                return a
        raise KeyError(f"No artifact with logical_name={logical_name!r}")
