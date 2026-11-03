"""Target-runtime-aware candidate adapter selection.

The runtime target configured for an application determines which build +
execute lane validates it.  Selection is fail-closed: an unknown target names
the supported set instead of silently falling back to another lane.
"""
from __future__ import annotations

from engine.candidate.adapter import CandidateAdapter
from engine.transformation.runtime_registry import (
    LANE_MAVEN,
    LANE_SPRING_BOOT,
    RUNTIME_KEYS,
    runtime_target,
)

# The lane per target is a column of the runtime registry: Spring Boot
# applications are built by the Spring Boot lane; plain_java / jakarta_ee /
# quarkus / micronaut are Maven projects building one runnable jar, built by
# the generic Maven lane (the offline image pre-caches the Quarkus and
# Micronaut dependencies).
_SUPPORTED_TARGETS = RUNTIME_KEYS


def candidate_adapter_for_target(target_runtime: str) -> CandidateAdapter:
    """Resolve the build + execute adapter for a configured runtime target.

    - ``spring_boot`` → ``DockerSpringBootCandidateAdapter``
    - ``plain_java`` / ``jakarta_ee`` / ``quarkus`` / ``micronaut`` →
      ``MavenProjectCandidateAdapter``
    - unknown target → ``ValueError`` naming the supported set (never a
      silent fallback to another lane).
    """
    # Imported inside the function so the resolution stays monkeypatchable
    # (tests patch the adapter classes at their defining modules).
    try:
        lane = runtime_target(target_runtime).lane
    except ValueError:
        raise ValueError(
            f"invalid target_runtime: {target_runtime!r} — supported "
            f"target_runtime values: "
            f"{', '.join(repr(t) for t in _SUPPORTED_TARGETS)}"
        ) from None
    if lane == LANE_SPRING_BOOT:
        from engine.candidate.docker_spring_boot_adapter import (
            DockerSpringBootCandidateAdapter,
        )

        return DockerSpringBootCandidateAdapter()
    if lane == LANE_MAVEN:
        from engine.candidate.maven_adapter import MavenProjectCandidateAdapter

        return MavenProjectCandidateAdapter()
    raise ValueError(f"unknown candidate lane {lane!r} for {target_runtime!r}")
