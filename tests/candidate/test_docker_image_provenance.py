"""Focused regression tests for Docker image provenance verification."""

from engine.candidate.docker_spring_boot_adapter import (
    DockerSpringBootCandidateAdapter,
    DockerSpringBootConfig,
)
from engine.candidate.image_provenance import (
    DockerImageObservation,
    DockerImageProvenance,
)
from engine.domain.identities import AdapterStatus


LOCAL_IMAGE_ID = "sha256:" + "ab" * 32
REGISTRY_DIGEST = "example-registry.local/maven@sha256:" + "cd" * 32
EXPECTED_RUNTIME_DIGEST = "example-registry.local/temurin@sha256:" + "ef" * 32
OTHER_RUNTIME_DIGEST = "example-registry.local/temurin@sha256:" + "12" * 32


def _local_build_observation() -> DockerImageObservation:
    """Simulate a locally built image with no registry RepoDigest."""
    return DockerImageObservation(
        requested_ref="maven-offline-springboot:latest",
        repo_digests=(),
        image_id=LOCAL_IMAGE_ID,
    )


def _registry_runtime_observation(
    digest: str = EXPECTED_RUNTIME_DIGEST,
) -> DockerImageObservation:
    """Simulate a pulled runtime image with registry digest evidence."""
    return DockerImageObservation(
        requested_ref="eclipse-temurin:21-jdk",
        repo_digests=(digest,),
        image_id="sha256:" + "34" * 32,
    )


def _adapter_with_observations(
    monkeypatch,
    *,
    build_observation: DockerImageObservation,
    runtime_observation: DockerImageObservation,
    build_identity: str,
    runtime_digest: str,
) -> DockerSpringBootCandidateAdapter:
    """Create an adapter with deterministic Docker identity observations."""
    monkeypatch.setattr(
        DockerSpringBootCandidateAdapter, "_check_docker", lambda self: True
    )
    monkeypatch.setattr(
        DockerSpringBootCandidateAdapter,
        "_resolve_build_observation",
        lambda self: build_observation,
    )
    monkeypatch.setattr(
        DockerSpringBootCandidateAdapter,
        "_resolve_runtime_observation",
        lambda self: runtime_observation,
    )
    monkeypatch.setattr(
        DockerSpringBootCandidateAdapter,
        "_detect_java_version",
        lambda self: "openjdk version 21",
    )
    monkeypatch.setattr(
        DockerSpringBootCandidateAdapter,
        "_detect_maven_version",
        lambda self: "Apache Maven 3.9",
    )
    config = DockerSpringBootConfig(
        build_identity=build_identity,
        runtime_digest=runtime_digest,
    )
    return DockerSpringBootCandidateAdapter(config)


class TestImageIdentitySelection:
    def test_local_build_without_repo_digest_uses_image_id(self):
        observation = _local_build_observation()

        assert observation.identity == LOCAL_IMAGE_ID
        assert observation.identity_kind == "image-id"
        assert observation.is_complete

    def test_registry_repo_digest_takes_precedence(self):
        observation = DockerImageObservation(
            requested_ref="maven-offline-springboot:latest",
            repo_digests=(REGISTRY_DIGEST,),
            image_id=LOCAL_IMAGE_ID,
        )

        assert observation.identity == REGISTRY_DIGEST
        assert observation.identity_kind == "repo-digest"
        assert observation.is_complete

    def test_inconsistent_provenance_evidence_is_rejected(self):
        provenance = DockerImageProvenance(
            build_image="maven-offline-springboot:latest",
            build_identity=REGISTRY_DIGEST,
            build_identity_kind="repo-digest",
            build_repo_digests=(),
            build_image_id=LOCAL_IMAGE_ID,
            runtime_image="eclipse-temurin:21-jdk",
            runtime_identity=EXPECTED_RUNTIME_DIGEST,
            runtime_repo_digests=(EXPECTED_RUNTIME_DIGEST,),
            runtime_image_id="sha256:" + "34" * 32,
        )

        assert any(
            "build_identity does not match" in violation
            for violation in provenance.validate()
        )


class TestAdapterProvenanceDecisions:
    def test_runtime_digest_exact_match_is_available(self, monkeypatch):
        adapter = _adapter_with_observations(
            monkeypatch,
            build_observation=_local_build_observation(),
            runtime_observation=_registry_runtime_observation(),
            build_identity=LOCAL_IMAGE_ID,
            runtime_digest=EXPECTED_RUNTIME_DIGEST,
        )

        assert adapter.status == AdapterStatus.AVAILABLE
        assert adapter.available
        assert adapter.build_identity == LOCAL_IMAGE_ID
        assert adapter.runtime_identity == EXPECTED_RUNTIME_DIGEST

    def test_runtime_digest_mismatch_is_unavailable(self, monkeypatch):
        adapter = _adapter_with_observations(
            monkeypatch,
            build_observation=_local_build_observation(),
            runtime_observation=_registry_runtime_observation(OTHER_RUNTIME_DIGEST),
            build_identity=LOCAL_IMAGE_ID,
            runtime_digest=EXPECTED_RUNTIME_DIGEST,
        )

        assert adapter.status == AdapterStatus.UNAVAILABLE
        assert not adapter.available

    def test_missing_identity_is_unavailable(self, monkeypatch):
        adapter = _adapter_with_observations(
            monkeypatch,
            build_observation=DockerImageObservation(
                requested_ref="maven-offline-springboot:latest"
            ),
            runtime_observation=_registry_runtime_observation(),
            build_identity=LOCAL_IMAGE_ID,
            runtime_digest=EXPECTED_RUNTIME_DIGEST,
        )

        assert adapter.status == AdapterStatus.UNAVAILABLE
        assert not adapter.available
