"""The verdict scope names the runtime that actually ran (audit V7).

The sealed scope statement was a constant naming the Spring Boot adapter and
eclipse-temurin for every verdict - including quarkus, micronaut, plain_java
and host-lane runs - and the candidate's runtime image was not recorded in
the evidence. The pipeline now records the candidate lane (adapter class and
runtime image identity) in the candidate environment identity, and the scope
is built from the manifest.
"""

from __future__ import annotations

import dataclasses

from engine.domain.identities import EnvironmentIdentity
from engine.verdict.derivation import VerdictDeriver
from tests.adversarial.conftest import make_manifest


def _with_environments(*envs: EnvironmentIdentity):
    return dataclasses.replace(make_manifest(), environment_identities=envs)


def test_scope_names_the_recorded_candidate_lane_and_compiler() -> None:
    manifest = _with_environments(
        EnvironmentIdentity(runtime_id="oracle-gnucobol-3.1.2", os_base="gnucobol-ocesql"),
        EnvironmentIdentity(
            runtime_id="candidate-java",
            os_base="MavenProjectCandidateAdapter eclipse-temurin@sha256:" + "4" * 64,
        ),
    )
    scope = VerdictDeriver().derive(manifest).supported_scope_statement

    assert "MavenProjectCandidateAdapter eclipse-temurin@sha256:" in scope
    assert f"GnuCOBOL {manifest.oracle_identity.compiler_version} oracle" in scope
    assert "DockerSpringBootCandidateAdapter" not in scope


def test_scope_without_a_recorded_lane_says_so() -> None:
    scope = VerdictDeriver().derive(_with_environments()).supported_scope_statement
    assert "Java candidate (lane not recorded)" in scope
    assert "Spring Boot" not in scope


def test_pipeline_records_adapter_class_and_runtime_identity() -> None:
    from engine.pipeline import VerticalSlicePipeline

    class FakeLane:
        runtime_identity = "eclipse-temurin@sha256:" + "5" * 64

    pipeline = object.__new__(VerticalSlicePipeline)
    pipeline._candidate_adapter = FakeLane()
    assert pipeline._candidate_lane() == "FakeLane eclipse-temurin@sha256:" + "5" * 64

    class HostLane:
        pass

    pipeline._candidate_adapter = HostLane()
    assert pipeline._candidate_lane() == "HostLane"
