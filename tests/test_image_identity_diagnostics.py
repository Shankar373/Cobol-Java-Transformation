"""G-21: a pinned-image mismatch says so, without relaxing the pin.

A local Maven image that does not match the pinned identity makes the Spring Boot lane
UNAVAILABLE and the build is recorded as a BUILD-phase failure.  The only text the evidence
carried was "Docker or Maven image not available", so the run looked like an application
problem.  The adapter now records *why* (expected and observed identity, what to do), in the
adapter and in the evidence stderr.  The check itself is unchanged: a different digest is
still refused, and the message never suggests accepting it.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from engine.candidate.adapter import AdapterStatus
from engine.candidate.docker_spring_boot_adapter import DockerSpringBootCandidateAdapter, DockerSpringBootConfig
from engine.candidate.image_provenance import (
    DockerImageObservation, describe_identity_problem, verify_image_identity,
)
from engine.domain.identities import RunId

PINNED = "sha256:" + "a" * 64
OTHER = "sha256:" + "b" * 64
DIGEST = "eclipse-temurin@sha256:" + "c" * 64


def observation(image_id: str = "", repo_digests: tuple[str, ...] = ()) -> DockerImageObservation:
    return DockerImageObservation(requested_ref="maven-offline-springboot:latest",
                                  repo_digests=repo_digests, image_id=image_id)


def test_a_matching_identity_has_no_problem():
    assert describe_identity_problem("build image", "maven:latest", PINNED, observation(PINNED), False) == ""


def test_a_mismatch_names_both_identities_and_the_remedy_and_never_suggests_relaxing_the_pin():
    text = describe_identity_problem("build image", "maven-offline-springboot:latest", PINNED, observation(OTHER), False)
    assert PINNED in text and OTHER in text and "maven-offline-springboot:latest" in text
    assert "record_docker_image_provenance" in text and "rebuild" in text.lower()
    assert "ignore" not in text.lower() and "skip" not in text.lower() and "relax" not in text.lower()


def test_no_pin_configured_is_reported_as_such():
    text = describe_identity_problem("build image", "maven:latest", "", observation(PINNED), False)
    assert "no pinned identity" in text and "docker-image-provenance.json" in text


def test_an_image_docker_cannot_resolve_is_reported_as_not_found_locally():
    text = describe_identity_problem("build image", "maven:latest", PINNED, observation(""), False)
    assert "not found locally" in text and "maven:latest" in text


def test_a_runtime_image_without_a_repo_digest_is_reported_as_such():
    text = describe_identity_problem("runtime image", "eclipse-temurin:21-jdk", DIGEST, observation(OTHER), True)
    assert "repo digest" in text.lower()


@pytest.mark.parametrize("expected,observed,require", [
    (PINNED, observation(PINNED), False), (PINNED, observation(OTHER), False), ("", observation(PINNED), False),
    (PINNED, observation(""), False), (DIGEST, observation(OTHER), True),
    (DIGEST, observation(repo_digests=(DIGEST,)), True),
])
def test_the_description_agrees_with_the_unchanged_verification(expected, observed, require):
    verified = verify_image_identity(expected_identity=expected, observed=observed, require_repo_digest=require)
    described = describe_identity_problem("image", "ref", expected, observed, require)
    assert (described == "") is verified     # a problem is described exactly when verification refuses


def _adapter(build_observation, runtime_observation, expected: str = PINNED) -> DockerSpringBootCandidateAdapter:
    config = DockerSpringBootConfig(build_identity=expected, runtime_digest=DIGEST)
    with patch.object(DockerSpringBootCandidateAdapter, "_check_docker", return_value=True), \
         patch.object(DockerSpringBootCandidateAdapter, "_resolve_build_observation", return_value=build_observation), \
         patch.object(DockerSpringBootCandidateAdapter, "_resolve_runtime_observation", return_value=runtime_observation), \
         patch.object(DockerSpringBootCandidateAdapter, "_detect_java_version", return_value="21"), \
         patch.object(DockerSpringBootCandidateAdapter, "_detect_maven_version", return_value="3.9"):
        return DockerSpringBootCandidateAdapter(config)


GOOD_RUNTIME = observation(repo_digests=(DIGEST,))


def test_a_mismatched_build_image_makes_the_adapter_unavailable_with_a_reason():
    adapter = _adapter(observation(OTHER), GOOD_RUNTIME)
    assert adapter.status is AdapterStatus.UNAVAILABLE      # the pin is still enforced
    assert PINNED in adapter.unavailable_reason and OTHER in adapter.unavailable_reason
    assert "build image" in adapter.unavailable_reason


def test_matching_images_leave_the_adapter_available_with_no_reason():
    adapter = _adapter(observation(PINNED), GOOD_RUNTIME)
    assert adapter.status is AdapterStatus.AVAILABLE and adapter.unavailable_reason == ""


def test_both_images_wrong_reports_both():
    adapter = _adapter(observation(OTHER), observation(OTHER))
    assert "build image" in adapter.unavailable_reason and "runtime image" in adapter.unavailable_reason


def test_docker_not_reachable_has_its_own_reason():
    with patch.object(DockerSpringBootCandidateAdapter, "_check_docker", return_value=False):
        adapter = DockerSpringBootCandidateAdapter(DockerSpringBootConfig(build_identity=PINNED, runtime_digest=DIGEST))
    assert adapter.status is AdapterStatus.UNAVAILABLE and "Docker daemon is not reachable" in adapter.unavailable_reason


def test_the_build_evidence_carries_the_reason_instead_of_a_generic_message(tmp_path):
    adapter = _adapter(observation(OTHER), GOOD_RUNTIME)
    result = adapter.compile(str(tmp_path), None)
    assert result.success is False and result.infrastructure_error is True   # still an infrastructure failure, never a verdict input
    message = " ".join(result.compilation_errors)
    assert PINNED in message and OTHER in message and "not available" in message


def test_the_execution_evidence_carries_the_reason_too(tmp_path):
    adapter = _adapter(observation(OTHER), GOOD_RUNTIME)
    result = adapter.execute(RunId(value="run-g21"), str(tmp_path), None)
    stderr = result.stderr.decode()
    assert result.status is AdapterStatus.UNAVAILABLE and result.termination_status == "error"
    assert PINNED in stderr and OTHER in stderr and "not available" in stderr
