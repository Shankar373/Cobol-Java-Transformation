"""JCL modernization lane.

Upgrades JCL from discovery-only parsing into a defined semantic model and a
Java/Spring Batch modernization profile.

Architecture:

    JCL source (JclApplication IR + raw text)
        ↓
    JclSemanticBuilder (engine.jcl.builder)
        ↓
    JclSemanticModel (engine.jcl.model)
        ↓
    JclSpringBatchMapper (engine.transformation.jcl_to_spring_batch)
        ↓
    JclSpringBatchApplication (engine.transformation.jcl_spring_batch_ir)

This lane makes no JES/z/OS runtime equivalence claims. Unsupported constructs
are reported as explicit JCL diagnostics, never silently dropped.
"""

from engine.jcl.diagnostics import (
    JclDiagnostic,
    JclDiagnosticCode,
    JclDiagnosticCollector,
    JclDiagnosticLevel,
)
from engine.jcl.model import (
    JclControl,
    JclControlKind,
    JclDatasetFlow,
    JclDatasetUse,
    JclDisposition,
    JclExec,
    JclExecMode,
    JclResource,
    JclResourceKind,
    JclSemanticJob,
    JclSemanticModel,
    JclSemanticStep,
    JclStepDependency,
)

__all__ = [
    "JclControl",
    "JclControlKind",
    "JclDatasetFlow",
    "JclDatasetUse",
    "JclDiagnostic",
    "JclDiagnosticCode",
    "JclDiagnosticCollector",
    "JclDiagnosticLevel",
    "JclDisposition",
    "JclExec",
    "JclExecMode",
    "JclResource",
    "JclResourceKind",
    "JclSemanticJob",
    "JclSemanticModel",
    "JclSemanticStep",
    "JclStepDependency",
]
