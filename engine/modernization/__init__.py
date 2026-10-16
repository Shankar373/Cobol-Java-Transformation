"""Universal Modernization Layer.

Provides the architectural layer that accepts an unfamiliar legacy COBOL
application and orchestrates the complete modernization flow:

    Unfamiliar Repository
    → Discovery
    → Semantic Graph
    → Capability Analysis
    → Transformation Plan
    → Per-Program Transformation
    → Application Assembly
    → Docker Build/Run
    → GnuCOBOL Oracle Execution
    → Comparison
    → Evidence
    → Verdict

This package does NOT transform COBOL itself. It orchestrates existing
transformers, validates capabilities, and assembles results.
"""

from engine.modernization.modernization_planner import (
    ModernizationPlanner,
    ModernizationPlan,
    ProgramPlan,
    CallRelationship,
    CopybookPlan,
    FileDependencyPlan,
    EntryProgram,
    ModernizationStatus,
    BlockingReason,
    TransformationStrategy,
    ValidationStrategy,
)

__all__ = [
    "ModernizationPlanner",
    "ModernizationPlan",
    "ProgramPlan",
    "CallRelationship",
    "CopybookPlan",
    "FileDependencyPlan",
    "EntryProgram",
    "ModernizationStatus",
    "BlockingReason",
    "TransformationStrategy",
    "ValidationStrategy",
]
