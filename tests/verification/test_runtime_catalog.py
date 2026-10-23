"""Runtime catalog: declarations, fail-closed discovery, deterministic output."""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.verification.runtime_catalog import (
    PrerequisiteKind,
    PrerequisiteObservation,
    PrerequisiteStatus,
    RuntimeAdapterCapability,
    RuntimeCapabilityState,
    RuntimeCatalog,
    RuntimePrerequisite,
    default_runtime_catalog,
    observe_local_prerequisites,
)


def _capability(
    state: RuntimeCapabilityState,
    prerequisites: tuple[RuntimePrerequisite, ...] = (),
    runtime_id: str = "runtime-under-test",
) -> RuntimeAdapterCapability:
    return RuntimeAdapterCapability(
        runtime_id=runtime_id,
        display_name=runtime_id,
        families=("TEST",),
        state=state,
        prerequisites=prerequisites,
    )


def _catalog(capability: RuntimeAdapterCapability) -> RuntimeCatalog:
    return RuntimeCatalog((capability,))


class TestCapabilityVocabulary:
    def test_exactly_six_states(self) -> None:
        assert {state.value for state in RuntimeCapabilityState} == {
            "IMPLEMENTED", "PARTIAL", "BLOCKED", "UNAVAILABLE",
            "UNSUPPORTED", "UNKNOWN",
        }

    def test_duplicate_runtime_ids_rejected(self) -> None:
        capability = _capability(RuntimeCapabilityState.BLOCKED)
        with pytest.raises(ValueError, match="Duplicate runtime_id"):
            RuntimeCatalog((capability, capability))

    def test_duplicate_prerequisites_rejected(self) -> None:
        prerequisite = RuntimePrerequisite(
            name="docker", kind=PrerequisiteKind.EXECUTABLE, description="d"
        )
        with pytest.raises(ValueError, match="duplicate prerequisite"):
            _capability(
                RuntimeCapabilityState.IMPLEMENTED,
                prerequisites=(prerequisite, prerequisite),
            )


class TestDiscoveryNeverUpgrades:
    def test_blocked_stays_blocked_even_when_prerequisites_satisfied(self) -> None:
        prerequisite = RuntimePrerequisite(
            name="entitlement", kind=PrerequisiteKind.ENTITLEMENT, description="d"
        )
        report = _catalog(
            _capability(RuntimeCapabilityState.BLOCKED, (prerequisite,))
        ).discover((
            PrerequisiteObservation(
                "entitlement", PrerequisiteStatus.SATISFIED
            ),
        ))
        status = report.statuses[0]
        assert status.declared_state is RuntimeCapabilityState.BLOCKED
        assert status.effective_state is RuntimeCapabilityState.BLOCKED
        assert not status.certifies_runtime

    def test_unknown_stays_unknown_even_when_prerequisites_satisfied(self) -> None:
        prerequisite = RuntimePrerequisite(
            name="docker", kind=PrerequisiteKind.EXECUTABLE, description="d"
        )
        report = _catalog(
            _capability(RuntimeCapabilityState.UNKNOWN, (prerequisite,))
        ).discover((
            PrerequisiteObservation("docker", PrerequisiteStatus.SATISFIED),
        ))
        assert report.statuses[0].effective_state is RuntimeCapabilityState.UNKNOWN

    def test_implemented_with_satisfied_prerequisites_remains_implemented(self) -> None:
        prerequisite = RuntimePrerequisite(
            name="docker", kind=PrerequisiteKind.EXECUTABLE, description="d"
        )
        report = _catalog(
            _capability(RuntimeCapabilityState.IMPLEMENTED, (prerequisite,))
        ).discover((
            PrerequisiteObservation("docker", PrerequisiteStatus.SATISFIED),
        ))
        status = report.statuses[0]
        assert status.effective_state is RuntimeCapabilityState.IMPLEMENTED
        assert status.certifies_runtime
        assert status.satisfied_prerequisites == ("docker",)


class TestDiscoveryDowngradesFailClosed:
    def _catalog_with_two(self) -> RuntimeCatalog:
        return _catalog(_capability(
            RuntimeCapabilityState.IMPLEMENTED,
            (
                RuntimePrerequisite(
                    name="docker", kind=PrerequisiteKind.EXECUTABLE, description="d"
                ),
                RuntimePrerequisite(
                    name="image:test", kind=PrerequisiteKind.CONTAINER_IMAGE,
                    description="i",
                ),
            ),
        ))

    def test_missing_required_downgrades_to_unavailable(self) -> None:
        report = self._catalog_with_two().discover((
            PrerequisiteObservation("docker", PrerequisiteStatus.MISSING),
            PrerequisiteObservation("image:test", PrerequisiteStatus.SATISFIED),
        ))
        status = report.statuses[0]
        assert status.effective_state is RuntimeCapabilityState.UNAVAILABLE
        assert status.missing_prerequisites == ("docker",)
        assert not status.certifies_runtime
        assert "missing" in (status.downgrade_reason or "")

    def test_unobserved_required_downgrades_to_unknown(self) -> None:
        report = self._catalog_with_two().discover((
            PrerequisiteObservation("docker", PrerequisiteStatus.SATISFIED),
        ))
        status = report.statuses[0]
        assert status.effective_state is RuntimeCapabilityState.UNKNOWN
        assert status.unknown_prerequisites == ("image:test",)
        assert not status.certifies_runtime

    def test_conflicting_observations_are_unknown(self) -> None:
        report = self._catalog_with_two().discover((
            PrerequisiteObservation("docker", PrerequisiteStatus.SATISFIED),
            PrerequisiteObservation("docker", PrerequisiteStatus.MISSING),
            PrerequisiteObservation("image:test", PrerequisiteStatus.SATISFIED),
        ))
        status = report.statuses[0]
        assert status.effective_state is RuntimeCapabilityState.UNKNOWN
        assert "docker" in status.unknown_prerequisites

    def test_partial_with_unobserved_prerequisite_becomes_unknown(self) -> None:
        report = _catalog(_capability(
            RuntimeCapabilityState.PARTIAL,
            (
                RuntimePrerequisite(
                    name="lane", kind=PrerequisiteKind.RUNTIME, description="d"
                ),
            ),
        )).discover(())
        assert report.statuses[0].effective_state is RuntimeCapabilityState.UNKNOWN

    def test_stray_observations_are_reported_not_used(self) -> None:
        report = _catalog(_capability(RuntimeCapabilityState.IMPLEMENTED)).discover((
            PrerequisiteObservation("unrelated", PrerequisiteStatus.SATISFIED),
        ))
        assert report.stray_observations == ("unrelated",)
        assert report.statuses[0].effective_state is RuntimeCapabilityState.IMPLEMENTED


class TestCanonicalReport:
    def test_output_is_deterministic_and_sorted(self) -> None:
        catalog = RuntimeCatalog((
            _capability(RuntimeCapabilityState.BLOCKED, runtime_id="z-runtime"),
            _capability(RuntimeCapabilityState.BLOCKED, runtime_id="a-runtime"),
        ))
        first = catalog.discover(()).to_bytes()
        second = catalog.discover(()).to_bytes()
        assert first == second
        report = catalog.discover(())
        assert [item.runtime_id for item in report.statuses] == [
            "a-runtime", "z-runtime",
        ]


class TestDefaultCatalog:
    def test_declares_proven_and_blocked_families(self) -> None:
        catalog = default_runtime_catalog()
        ids = {item.runtime_id for item in catalog.capabilities}
        assert {
            "gnucobol-batch", "gnucobol-indexed-relative-io",
            "java-docker-candidate", "db2-esql", "ibm-mq",
            "cics-transaction", "ims-transaction", "jcl-zos",
        } <= ids

        for runtime_id in (
            "db2-esql", "ibm-mq", "cics-transaction", "ims-transaction",
            "jcl-zos",
        ):
            assert catalog.get(runtime_id).state is RuntimeCapabilityState.BLOCKED

        assert (
            catalog.get("gnucobol-batch").state
            is RuntimeCapabilityState.IMPLEMENTED
        )
        assert (
            catalog.get("java-docker-candidate").state
            is RuntimeCapabilityState.IMPLEMENTED
        )

    def test_discovery_without_observations_cannot_claim_readiness(self) -> None:
        report = default_runtime_catalog().discover(())
        for runtime_id in (
            "gnucobol-batch", "gnucobol-indexed-relative-io",
            "java-docker-candidate",
        ):
            status = report.get(runtime_id)
            assert status.effective_state is RuntimeCapabilityState.UNKNOWN
            assert not status.certifies_runtime
        for runtime_id in (
            "db2-esql", "ibm-mq", "cics-transaction", "ims-transaction",
            "jcl-zos",
        ):
            assert report.get(runtime_id).effective_state is (
                RuntimeCapabilityState.BLOCKED
            )


class TestLocalObservation:
    def test_environment_and_file_are_observed(
        self, tmp_path: Path
    ) -> None:
        present = tmp_path / "present.dat"
        present.write_bytes(b"x")
        prerequisites = (
            RuntimePrerequisite(
                name="TEST_ENV", kind=PrerequisiteKind.ENVIRONMENT, description="e"
            ),
            RuntimePrerequisite(
                name="present", kind=PrerequisiteKind.FILE, description="f",
                probe=str(present),
            ),
            RuntimePrerequisite(
                name="absent", kind=PrerequisiteKind.FILE, description="f",
                probe=str(tmp_path / "absent.dat"),
            ),
        )
        observations = {
            item.prerequisite: item
            for item in observe_local_prerequisites(
                prerequisites, environ={"TEST_ENV": "1"}
            )
        }
        assert observations["TEST_ENV"].status is PrerequisiteStatus.SATISFIED
        assert observations["present"].status is PrerequisiteStatus.SATISFIED
        assert observations["absent"].status is PrerequisiteStatus.MISSING

    def test_container_image_is_never_locally_guessed(self) -> None:
        prerequisite = RuntimePrerequisite(
            name="image:x", kind=PrerequisiteKind.CONTAINER_IMAGE, description="i"
        )
        observation = observe_local_prerequisites((prerequisite,))[0]
        assert observation.status is PrerequisiteStatus.UNKNOWN

    def test_executable_uses_which(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "engine.verification.runtime_catalog.shutil.which",
            lambda name: f"/usr/bin/{name}" if name == "docker" else None,
        )
        prerequisites = (
            RuntimePrerequisite(
                name="docker", kind=PrerequisiteKind.EXECUTABLE, description="d"
            ),
            RuntimePrerequisite(
                name="cobc", kind=PrerequisiteKind.EXECUTABLE, description="c"
            ),
        )
        observations = observe_local_prerequisites(prerequisites)
        assert observations[0].status is PrerequisiteStatus.SATISFIED
        assert observations[1].status is PrerequisiteStatus.MISSING
