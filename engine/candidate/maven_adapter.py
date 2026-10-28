"""Generic Maven project candidate adapter (Phase 9).

The ``DockerSpringBootCandidateAdapter`` already builds *any* Maven project
offline (``mvn -o package``) and executes the resulting jar — its build and
execution are not Spring-specific.  Phase 8's ``plain_java`` and ``jakarta_ee``
targets emit dependency-free Maven projects, so they are built and executed by
this honestly-named subclass rather than by the Spring-Boot-named adapter
(evidence provenance should name the lane that actually ran).

Only the validation wording differs; the proven Maven build + jar execution
are inherited unchanged.  No Spring dependency, wiring, or annotation is
assumed or emitted.
"""
from __future__ import annotations

from engine.candidate.docker_spring_boot_adapter import (
    CandidateManifest,
    DockerSpringBootCandidateAdapter,
)


class MavenProjectCandidateAdapter(DockerSpringBootCandidateAdapter):
    """Docker-backed Maven build + jar execution for a generic Maven project.

    Build phase: Maven builds the project inside a Docker container (offline,
    pre-cached plugins).  Execution phase: ``java -jar`` inside a disposable
    Docker container.  Used for the ``plain_java`` and ``jakarta_ee`` targets
    (dependency-free Maven projects).
    """

    def validate_candidate(
        self, candidate_path: str, manifest: CandidateManifest
    ) -> list[str]:
        # Same checks as the Spring Boot adapter, with target-neutral wording
        # (a dependency-free Maven project is valid here; no Spring required).
        violations = []
        missing = manifest.validate()
        if missing:
            violations.append(f"Missing manifest fields: {', '.join(missing)}")

        from pathlib import Path

        candidate_dir = Path(candidate_path)
        if not (candidate_dir / "pom.xml").exists():
            violations.append("No pom.xml found (Maven project required)")

        for rel_path in manifest.generated_files:
            if not (candidate_dir / rel_path).exists():
                violations.append(f"Declared file not found: {rel_path}")

        return violations
