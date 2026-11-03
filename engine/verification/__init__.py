"""Deterministic runtime and business-equivalence verification.

This package extends the canonical verification pipeline; it does not
introduce a parallel one.

- ``runtime_catalog`` declares what each execution runtime can *actually*
  prove, what it requires, and downgrades any claim whose prerequisites were
  not observed. Capabilities are never upgraded by discovery.
- ``business_invariants`` evaluates declarative preconditions,
  postconditions and error-behaviour invariants against one execution's
  observation. Reports are canonical, content-addressed and compared by the
  registered ``BUSINESS_INVARIANT_COMPARATOR``.

No LLM, network call, container launch or filesystem mutation happens in
either module. Discovery observes; it never infers availability.
"""

from engine.verification.business_invariants import (
    BusinessInvariant,
    BusinessInvariantReport,
    EvaluationReport,
    InvariantKind,
    InvariantObservation,
    InvariantOutcome,
    InvariantPhase,
    InvariantSource,
    build_report,
    evaluate_invariants,
    invariant_definition_digest,
)
from engine.verification.runtime_catalog import (
    PrerequisiteKind,
    PrerequisiteObservation,
    PrerequisiteStatus,
    RuntimeAdapterCapability,
    RuntimeCapabilityState,
    RuntimeCatalog,
    RuntimeDiscoveryReport,
    RuntimePrerequisite,
    RuntimeStatus,
    default_runtime_catalog,
    observe_local_prerequisites,
)

__all__ = [
    "BusinessInvariant",
    "BusinessInvariantReport",
    "EvaluationReport",
    "InvariantKind",
    "InvariantObservation",
    "InvariantOutcome",
    "InvariantPhase",
    "InvariantSource",
    "PrerequisiteKind",
    "PrerequisiteObservation",
    "PrerequisiteStatus",
    "RuntimeAdapterCapability",
    "RuntimeCapabilityState",
    "RuntimeCatalog",
    "RuntimeDiscoveryReport",
    "RuntimePrerequisite",
    "RuntimeStatus",
    "build_report",
    "default_runtime_catalog",
    "evaluate_invariants",
    "invariant_definition_digest",
    "observe_local_prerequisites",
]
