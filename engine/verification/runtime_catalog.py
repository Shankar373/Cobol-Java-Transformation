"""Declarative runtime-capability catalog with fail-closed discovery.

What the platform can prove at runtime differs sharply by workload family:
GnuCOBOL and Java batch execution are proven; DB2, MQ, CICS, IMS and JCL
behavioural runtimes are not. A single ``SUPPORTED`` boolean cannot express
that honestly, so every capability declares:

- one of six states (``IMPLEMENTED``, ``PARTIAL``, ``BLOCKED``,
  ``UNAVAILABLE``, ``UNSUPPORTED``, ``UNKNOWN``);
- the prerequisites it actually needs;
- the artifact types it can produce;
- the limitations that remain even when it runs;
- optional evidence references.

Discovery is a pure function over *observed* prerequisite statuses. Missing
or unobserved prerequisites can only downgrade a claim, never upgrade it.
There is no Docker/network/LLM call here; authoritative observers (the
container audit, CI) supply observations explicitly.
"""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0"


class RuntimeCapabilityState(str, Enum):
    """Exactly the states a runtime claim may carry."""

    IMPLEMENTED = "IMPLEMENTED"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"
    UNAVAILABLE = "UNAVAILABLE"
    UNSUPPORTED = "UNSUPPORTED"
    UNKNOWN = "UNKNOWN"


#: States that assert some runnable proof and therefore require every
#: required prerequisite to be positively observed.
_CLAIMABLE_STATES = frozenset({
    RuntimeCapabilityState.IMPLEMENTED,
    RuntimeCapabilityState.PARTIAL,
})


class PrerequisiteKind(str, Enum):
    """How a prerequisite can be observed."""

    EXECUTABLE = "EXECUTABLE"
    ENVIRONMENT = "ENVIRONMENT"
    FILE = "FILE"
    CONTAINER_IMAGE = "CONTAINER_IMAGE"
    RUNTIME = "RUNTIME"
    ENTITLEMENT = "ENTITLEMENT"


class PrerequisiteStatus(str, Enum):
    SATISFIED = "SATISFIED"
    MISSING = "MISSING"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class RuntimePrerequisite:
    """A single prerequisite for a runtime capability."""

    name: str
    kind: PrerequisiteKind
    description: str
    required: bool = True
    #: Value an EXECUTABLE/ENVIRONMENT/FILE probe should look for. Defaults
    #: to ``name``. Container images, runtimes and entitlements are never
    #: probed locally; they require an authoritative observation.
    probe: str | None = None

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("prerequisite name cannot be empty")
        if not isinstance(self.kind, PrerequisiteKind):
            raise ValueError(f"kind must be PrerequisiteKind, got {self.kind!r}")
        if self.probe is not None and not self.probe.strip():
            raise ValueError("probe cannot be blank when provided")

    @property
    def probe_target(self) -> str:
        return self.probe or self.name


@dataclass(frozen=True)
class RuntimeAdapterCapability:
    """One runtime's declared capability."""

    runtime_id: str
    display_name: str
    families: tuple[str, ...]
    state: RuntimeCapabilityState
    prerequisites: tuple[RuntimePrerequisite, ...] = ()
    produced_artifact_types: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.runtime_id or not self.runtime_id.strip():
            raise ValueError("runtime_id cannot be empty")
        if not self.display_name:
            raise ValueError("display_name cannot be empty")
        if not self.families:
            raise ValueError("at least one runtime family must be declared")
        if not isinstance(self.state, RuntimeCapabilityState):
            raise ValueError(
                f"state must be RuntimeCapabilityState, got {self.state!r}"
            )
        names = [item.name for item in self.prerequisites]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(
                f"duplicate prerequisite(s) for {self.runtime_id}: {duplicates}"
            )
        for item in self.prerequisites:
            if not isinstance(item, RuntimePrerequisite):
                raise ValueError(
                    f"prerequisites must be RuntimePrerequisite, got "
                    f"{type(item).__name__}"
                )


@dataclass(frozen=True)
class PrerequisiteObservation:
    """An authoritative observation of one prerequisite."""

    prerequisite: str
    status: PrerequisiteStatus
    detail: str = ""

    def __post_init__(self) -> None:
        if not self.prerequisite or not self.prerequisite.strip():
            raise ValueError("observed prerequisite name cannot be empty")
        if not isinstance(self.status, PrerequisiteStatus):
            raise ValueError(
                f"status must be PrerequisiteStatus, got {self.status!r}"
            )


@dataclass(frozen=True)
class RuntimeStatus:
    """Effective (post-discovery) status of one capability."""

    runtime_id: str
    display_name: str
    families: tuple[str, ...]
    declared_state: RuntimeCapabilityState
    effective_state: RuntimeCapabilityState
    satisfied_prerequisites: tuple[str, ...]
    missing_prerequisites: tuple[str, ...]
    unknown_prerequisites: tuple[str, ...]
    produced_artifact_types: tuple[str, ...]
    limitations: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    downgrade_reason: str | None

    @property
    def certifies_runtime(self) -> bool:
        """True only for an unimpeded IMPLEMENTED claim."""
        return (
            self.effective_state is RuntimeCapabilityState.IMPLEMENTED
            and not self.missing_prerequisites
            and not self.unknown_prerequisites
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "runtime_id": self.runtime_id,
            "display_name": self.display_name,
            "families": list(self.families),
            "declared_state": self.declared_state.value,
            "effective_state": self.effective_state.value,
            "certifies_runtime": self.certifies_runtime,
            "satisfied_prerequisites": list(self.satisfied_prerequisites),
            "missing_prerequisites": list(self.missing_prerequisites),
            "unknown_prerequisites": list(self.unknown_prerequisites),
            "produced_artifact_types": list(self.produced_artifact_types),
            "limitations": list(self.limitations),
            "evidence_refs": list(self.evidence_refs),
            "downgrade_reason": self.downgrade_reason,
        }


@dataclass(frozen=True)
class RuntimeDiscoveryReport:
    """Deterministic, canonical discovery result for a catalog."""

    statuses: tuple[RuntimeStatus, ...]
    stray_observations: tuple[str, ...] = ()
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "capabilities": [status.to_dict() for status in self.statuses],
            "stray_observations": list(self.stray_observations),
        }

    def to_bytes(self) -> bytes:
        return json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")

    def get(self, runtime_id: str) -> RuntimeStatus:
        for status in self.statuses:
            if status.runtime_id == runtime_id:
                return status
        raise KeyError(f"unknown runtime_id {runtime_id!r}")

    def by_state(self, state: RuntimeCapabilityState) -> tuple[RuntimeStatus, ...]:
        return tuple(
            status for status in self.statuses
            if status.effective_state is state
        )


class RuntimeCatalog:
    """An immutable set of declared runtime capabilities."""

    def __init__(self, capabilities: Iterable[RuntimeAdapterCapability]) -> None:
        self._capabilities = tuple(
            sorted(capabilities, key=lambda item: item.runtime_id)
        )
        ids = [item.runtime_id for item in self._capabilities]
        duplicates = sorted({item for item in ids if ids.count(item) > 1})
        if duplicates:
            raise ValueError(f"Duplicate runtime_id(s): {duplicates}")
        if not self._capabilities:
            raise ValueError("RuntimeCatalog requires at least one capability")

    @property
    def capabilities(self) -> tuple[RuntimeAdapterCapability, ...]:
        return self._capabilities

    def get(self, runtime_id: str) -> RuntimeAdapterCapability:
        for capability in self._capabilities:
            if capability.runtime_id == runtime_id:
                return capability
        raise KeyError(f"unknown runtime_id {runtime_id!r}")

    def discover(
        self,
        observations: Iterable[PrerequisiteObservation],
    ) -> RuntimeDiscoveryReport:
        """Compute effective states without ever upgrading a declaration.

        Observation semantics are fail-closed:

        - a prerequisite with no observation is ``UNKNOWN``;
        - conflicting observations for one prerequisite are ``UNKNOWN``;
        - a missing required prerequisite downgrades a claimable state to
          ``UNAVAILABLE``;
        - an unknown required prerequisite downgrades it to ``UNKNOWN``;
        - non-claimable declared states are retained as declared;
        - observations naming prerequisites no capability declares are
          reported as ``stray_observations`` and cannot affect any state.
        """
        observed: dict[str, set[PrerequisiteStatus]] = {}
        for observation in observations:
            observed.setdefault(observation.prerequisite, set()).add(
                observation.status
            )

        declared_names = {
            prerequisite.name
            for capability in self._capabilities
            for prerequisite in capability.prerequisites
        }
        stray = tuple(sorted(set(observed) - declared_names))

        statuses: list[RuntimeStatus] = []
        for capability in self._capabilities:
            satisfied: list[str] = []
            missing: list[str] = []
            unknown: list[str] = []
            for prerequisite in capability.prerequisites:
                statuses_seen = observed.get(prerequisite.name, set())
                if len(statuses_seen) > 1:
                    status = PrerequisiteStatus.UNKNOWN
                elif statuses_seen:
                    status = next(iter(statuses_seen))
                else:
                    status = PrerequisiteStatus.UNKNOWN
                if status is PrerequisiteStatus.SATISFIED:
                    satisfied.append(prerequisite.name)
                elif status is PrerequisiteStatus.MISSING:
                    missing.append(prerequisite.name)
                else:
                    unknown.append(prerequisite.name)

            effective = capability.state
            downgrade_reason: str | None = None
            if capability.state in _CLAIMABLE_STATES:
                if missing:
                    effective = RuntimeCapabilityState.UNAVAILABLE
                    downgrade_reason = (
                        "required prerequisite(s) missing: " + ", ".join(missing)
                    )
                elif unknown:
                    effective = RuntimeCapabilityState.UNKNOWN
                    downgrade_reason = (
                        "required prerequisite(s) not positively observed: "
                        + ", ".join(unknown)
                    )
            else:
                downgrade_reason = (
                    f"declared state is {capability.state.value}; discovery "
                    f"never upgrades it"
                )

            statuses.append(RuntimeStatus(
                runtime_id=capability.runtime_id,
                display_name=capability.display_name,
                families=capability.families,
                declared_state=capability.state,
                effective_state=effective,
                satisfied_prerequisites=tuple(satisfied),
                missing_prerequisites=tuple(missing),
                unknown_prerequisites=tuple(unknown),
                produced_artifact_types=capability.produced_artifact_types,
                limitations=capability.limitations,
                evidence_refs=capability.evidence_refs,
                downgrade_reason=downgrade_reason,
            ))

        return RuntimeDiscoveryReport(
            statuses=tuple(statuses),
            stray_observations=stray,
        )


# ---------------------------------------------------------------------------
# Local observation helpers
# ---------------------------------------------------------------------------

def _observe_local(
    prerequisite: RuntimePrerequisite,
    environ: Mapping[str, str],
) -> PrerequisiteObservation:
    target = prerequisite.probe_target
    if prerequisite.kind is PrerequisiteKind.EXECUTABLE:
        found = shutil.which(target)
        return PrerequisiteObservation(
            prerequisite=prerequisite.name,
            status=(
                PrerequisiteStatus.SATISFIED if found
                else PrerequisiteStatus.MISSING
            ),
            detail=f"resolved executable: {found}" if found else "not on PATH",
        )
    if prerequisite.kind is PrerequisiteKind.ENVIRONMENT:
        value = environ.get(target)
        return PrerequisiteObservation(
            prerequisite=prerequisite.name,
            status=(
                PrerequisiteStatus.SATISFIED if value else PrerequisiteStatus.MISSING
            ),
            detail="environment variable is set" if value else "environment variable unset",
        )
    if prerequisite.kind is PrerequisiteKind.FILE:
        path = Path(target)
        exists = path.is_file()
        return PrerequisiteObservation(
            prerequisite=prerequisite.name,
            status=(
                PrerequisiteStatus.SATISFIED if exists
                else PrerequisiteStatus.MISSING
            ),
            detail=f"file exists: {path}" if exists else f"file absent: {path}",
        )
    # Container image presence, proprietary entitlement and a full z/OS or
    # messaging runtime cannot be established by looking at the local host.
    # Guessing either way would corrupt the capability claim.
    return PrerequisiteObservation(
        prerequisite=prerequisite.name,
        status=PrerequisiteStatus.UNKNOWN,
        detail=(
            f"{prerequisite.kind.value} requires an authoritative observer; "
            f"local discovery cannot decide it"
        ),
    )


def observe_local_prerequisites(
    prerequisites: Iterable[RuntimePrerequisite],
    *,
    environ: Mapping[str, str] | None = None,
) -> tuple[PrerequisiteObservation, ...]:
    """Observe only what is locally decidable (executable/env/file).

    ``environ`` is accepted for deterministic tests; when omitted the real
    process environment is used.
    """
    environment = os.environ if environ is None else environ
    return tuple(_observe_local(item, environment) for item in prerequisites)


# ---------------------------------------------------------------------------
# Default catalog: the current, evidence-backed truth
# ---------------------------------------------------------------------------

def default_runtime_catalog() -> RuntimeCatalog:
    """Return the canonical catalog of runtime capabilities.

    Every claim here must be backed by repository evidence. States for
    DB2/MQ/CICS/IMS/JCL intentionally stay ``BLOCKED``; no prerequisite
    observation can raise them.
    """
    docker = RuntimePrerequisite(
        name="docker",
        kind=PrerequisiteKind.EXECUTABLE,
        description="Docker CLI available to the execution host",
    )

    return RuntimeCatalog((
        RuntimeAdapterCapability(
            runtime_id="gnucobol-batch",
            display_name="GnuCOBOL 3.1.2 batch oracle",
            families=("COBOL",),
            state=RuntimeCapabilityState.IMPLEMENTED,
            prerequisites=(
                docker,
                RuntimePrerequisite(
                    name="image:gnucobol-ocesql:latest",
                    kind=PrerequisiteKind.CONTAINER_IMAGE,
                    description="Digest-pinned GnuCOBOL oracle image",
                ),
            ),
            produced_artifact_types=(
                "STDOUT", "STDERR", "EXIT_STATUS", "TEXT_FILE", "FIXED_RECORD",
            ),
            limitations=(
                "No DB2, MQ, CICS, IMS or JCL runtime execution.",
                "Artifact coverage is limited to the five registered types "
                "plus derived BUSINESS_INVARIANT reports.",
            ),
            evidence_refs=(
                "test-artifacts/runtime-image-audit-2026-10-22/",
            ),
        ),
        RuntimeAdapterCapability(
            runtime_id="gnucobol-indexed-relative-io",
            display_name="GnuCOBOL indexed/relative file I/O",
            families=("COBOL", "FILE"),
            state=RuntimeCapabilityState.IMPLEMENTED,
            prerequisites=(
                docker,
                RuntimePrerequisite(
                    name="image:gnucobol-ocesql:latest",
                    kind=PrerequisiteKind.CONTAINER_IMAGE,
                    description="Digest-pinned GnuCOBOL oracle image",
                ),
            ),
            produced_artifact_types=("FIXED_RECORD",),
            limitations=(
                "Runtime execution is proven for hand-written candidates; "
                "transformation-side FILE-CONTROL indexed/relative "
                "classification remains a separate gap.",
            ),
            evidence_refs=(
                "tests/integration/test_indexed_semantics.py",
                "tests/integration/test_relative_semantics.py",
            ),
        ),
        RuntimeAdapterCapability(
            runtime_id="java-docker-candidate",
            display_name="Docker Java 21 candidate",
            families=("JAVA",),
            state=RuntimeCapabilityState.IMPLEMENTED,
            prerequisites=(
                docker,
                RuntimePrerequisite(
                    name="image:eclipse-temurin:21-jdk",
                    kind=PrerequisiteKind.CONTAINER_IMAGE,
                    description="Digest-pinned Java candidate image",
                ),
            ),
            produced_artifact_types=(
                "STDOUT", "STDERR", "EXIT_STATUS", "TEXT_FILE", "FIXED_RECORD",
            ),
            limitations=(
                "Generated Spring Boot build/start is tested; JCL "
                "behavioural equivalence is not.",
            ),
            evidence_refs=(
                "test-artifacts/runtime-image-audit-2026-10-22/",
            ),
        ),
        RuntimeAdapterCapability(
            runtime_id="db2-esql",
            display_name="DB2 embedded SQL execution",
            families=("DB2", "SQL"),
            state=RuntimeCapabilityState.BLOCKED,
            prerequisites=(
                RuntimePrerequisite(
                    name="ocesql",
                    kind=PrerequisiteKind.EXECUTABLE,
                    description="Open-COBOL-ESQL preprocessor",
                ),
                RuntimePrerequisite(
                    name="db2-client-library",
                    kind=PrerequisiteKind.RUNTIME,
                    description="DB2 client/driver stack",
                ),
                RuntimePrerequisite(
                    name="image:db2",
                    kind=PrerequisiteKind.CONTAINER_IMAGE,
                    description="Licensed DB2 server image",
                ),
            ),
            limitations=(
                "No ESQL preprocessor, DB2 client stack, database-state "
                "comparator or DB-state evidence lane.",
            ),
        ),
        RuntimeAdapterCapability(
            runtime_id="ibm-mq",
            display_name="IBM MQ messaging",
            families=("MQ",),
            state=RuntimeCapabilityState.BLOCKED,
            prerequisites=(
                RuntimePrerequisite(
                    name="image:ibm-mq",
                    kind=PrerequisiteKind.CONTAINER_IMAGE,
                    description="IBM MQ developer image",
                ),
                RuntimePrerequisite(
                    name="mq-execution-lane",
                    kind=PrerequisiteKind.RUNTIME,
                    description="Queue setup, send/receive lane and message comparator",
                ),
            ),
            limitations=(
                "A free developer image exists, but no MQ execution test, "
                "lane or message-state evidence comparator exists.",
            ),
        ),
        RuntimeAdapterCapability(
            runtime_id="cics-transaction",
            display_name="CICS transaction server",
            families=("CICS",),
            state=RuntimeCapabilityState.BLOCKED,
            prerequisites=(
                RuntimePrerequisite(
                    name="ibm-cics-entitlement",
                    kind=PrerequisiteKind.ENTITLEMENT,
                    description="Proprietary CICS entitlement and runtime",
                ),
            ),
            limitations=(
                "IBM registry access returned UNAUTHORIZED; execution "
                "requires licensed software.",
            ),
        ),
        RuntimeAdapterCapability(
            runtime_id="ims-transaction",
            display_name="IMS transaction processing",
            families=("IMS",),
            state=RuntimeCapabilityState.BLOCKED,
            prerequisites=(
                RuntimePrerequisite(
                    name="ibm-ims-entitlement",
                    kind=PrerequisiteKind.ENTITLEMENT,
                    description="Proprietary IMS entitlement and runtime",
                ),
            ),
            limitations=(
                "IBM registry access returned UNAUTHORIZED; execution "
                "requires licensed software.",
            ),
        ),
        RuntimeAdapterCapability(
            runtime_id="jcl-zos",
            display_name="JCL behavioural execution",
            families=("JCL",),
            state=RuntimeCapabilityState.BLOCKED,
            prerequisites=(
                RuntimePrerequisite(
                    name="zos-runtime",
                    kind=PrerequisiteKind.RUNTIME,
                    description="z/OS or compatible JCL job runtime",
                ),
            ),
            limitations=(
                "Only generated Spring Boot build/start is tested; JCL "
                "job semantics are not executed.",
            ),
        ),
    ))
