"""Target-runtime-aware candidate adapter selection (Phase 9).

The §32 runtime target configured for an application determines which build +
execute lane validates it.  Selection is fail-closed: an unknown target names
the supported set instead of silently falling back to another lane.
"""
from __future__ import annotations

from engine.candidate.adapter import CandidateAdapter

# Targets whose generated project is a Spring Boot application (built by the
# Spring Boot lane).  plain_java / jakarta_ee are dependency-free Maven
# projects built by the generic Maven lane.
_SUPPORTED_TARGETS = ("spring_boot", "plain_java", "jakarta_ee")


def candidate_adapter_for_target(target_runtime: str) -> CandidateAdapter:
    """Resolve the build + execute adapter for a configured runtime target.

    - ``spring_boot`` → ``DockerSpringBootCandidateAdapter``
    - ``plain_java`` / ``jakarta_ee`` → ``MavenProjectCandidateAdapter``
    - unknown target → ``ValueError`` naming the supported set (never a
      silent fallback to another lane).
    """
    # Imported inside the function so the resolution stays monkeypatchable
    # (tests patch the adapter classes at their defining modules).
    if target_runtime == "spring_boot":
        from engine.candidate.docker_spring_boot_adapter import (
            DockerSpringBootCandidateAdapter,
        )

        return DockerSpringBootCandidateAdapter()
    if target_runtime in ("plain_java", "jakarta_ee"):
        from engine.candidate.maven_adapter import MavenProjectCandidateAdapter

        return MavenProjectCandidateAdapter()
    raise ValueError(
        f"invalid target_runtime: {target_runtime!r} — supported "
        f"target_runtime values: "
        f"{', '.join(repr(t) for t in _SUPPORTED_TARGETS)}"
    )
