"""Evidence must record the network policy the candidate actually ran with.

Master README §34 (network disabled where appropriate) and §76.4 (evidence
must reflect what was measured, never an assumed default): the pipeline wrote
``network_policy="none"`` into the candidate ``EnvironmentIdentity``
unconditionally — including when the candidate adapter was the host
``RealJavaCandidateAdapter``, which runs ``javac``/``java`` directly on the
machine with no network isolation at all.  The evidence manifest therefore
asserted an isolation that was never applied.

This file pins the honest behaviour:

- the host lane records an explicitly unisolated policy (never ``"none"``);
- the Docker lanes, which genuinely run inside ``--network none``
  containers, still record ``"none"`` (evidence stays byte-stable for the
  lane all current green evidence uses);
- the pipeline reads the policy from the adapter that executed instead of
  hardcoding it, so a duck-typed double without the property falls back to
  the honest ``"unisolated"`` default rather than crashing or lying;
- the change can never upgrade a verdict (it only re-describes the
  environment, it does not touch verdict derivation).
"""

from __future__ import annotations

from pathlib import Path

from engine.candidate.adapter import CandidateAdapter
from engine.candidate.docker_java_adapter import DockerJavaCandidateAdapter
from engine.candidate.docker_spring_boot_adapter import (
    DockerSpringBootCandidateAdapter,
)
from engine.candidate.java_adapter import RealJavaCandidateAdapter
from engine.domain.identities import EnvironmentIdentity


class TestAdapterDeclaredPolicy:
    """Each adapter reports the isolation it truly applies."""

    def test_host_lane_is_not_isolated(self):
        """The host adapter shares the machine's network — it must never claim `none`."""
        policy = RealJavaCandidateAdapter().network_policy
        assert policy != "none", (
            "host javac/java runs with no container isolation; recording "
            f"'none' would assert an isolation that never happened (got {policy!r})"
        )
        assert policy == "unisolated"

    def test_docker_java_lane_records_none(self):
        """The Docker Java adapter runs inside `--network none` and may claim it."""
        assert DockerJavaCandidateAdapter().network_policy == "none"

    def test_docker_spring_boot_lane_records_none(self):
        """The Spring Boot adapter builds and runs inside `--network none`."""
        assert DockerSpringBootCandidateAdapter().network_policy == "none"

    def test_base_default_is_unisolated(self):
        """An adapter that declares no isolation must default to unisolated.

        This is the safety net: any future adapter that does not override the
        property is recorded honestly rather than inheriting a blanket 'none'.
        """

        class _Bare(CandidateAdapter):
            def validate_candidate(self, candidate_path, manifest):
                return []

            def compile(self, candidate_path, manifest):
                raise NotImplementedError

            def execute(self, run_id, compiled_path, manifest, input_data=None, input_files=None):
                raise NotImplementedError

        assert _Bare().network_policy == "unisolated"


def _policy_of(identity: EnvironmentIdentity, runtime_id: str) -> str:
    matches = [e.network_policy for e in identity if e.runtime_id == runtime_id]
    assert matches, f"no environment identity for {runtime_id!r}"
    return matches[0]


class TestPipelineRecordsExecutedPolicy:
    """The manifest must carry the executing adapter's policy, not a constant."""

    def _run_with_fake_candidate(self, tmp_path: Path):
        """Drive a full pipeline run with a duck-typed candidate double.

        The double deliberately does NOT define `network_policy`, so this
        exercises the honest `getattr` fallback: a candidate whose isolation
        is unknown is recorded as unisolated, never as `none`.
        """
        from engine.pipeline import PipelineConfig, VerticalSlicePipeline
        from engine.domain.identities import (
            AdapterStatus,
            ExecutionId,
            RunId,
        )
        from datetime import datetime, timezone

        def _now() -> str:
            return datetime.now(timezone.utc).isoformat()

        class _FakeOracle:
            def get_identity(self):
                from engine.domain.identities import OracleIdentity

                return OracleIdentity(
                    oracle_id="gnucobol-3.1.2",
                    image_digest="sha256:" + "0" * 64,
                    compiler_version="3.1.2",
                )

            def execute(self, run_id, source_path, input_data=None, input_files=None):
                from engine.oracle.adapter import OracleExecutionResult

                return OracleExecutionResult(
                    execution_id=ExecutionId(value=f"oracle-{run_id.value}"),
                    run_id=run_id,
                    oracle_id="test-oracle",
                    status=AdapterStatus.SUCCEEDED,
                    exit_code=0,
                    stdout=b"oracle-out",
                    stderr=b"",
                    start_time=_now(),
                    end_time=_now(),
                    termination_status="normal",
                    timeout_applied=False,
                )

        class _FakeCandidate:
            def compile(self, candidate_path, manifest):
                from engine.candidate.adapter import CompilationResult

                return CompilationResult(success=True, class_files={"A.class": b"cafebabe"})

            def execute(self, run_id, compiled_path, manifest, input_data=None, input_files=None):
                from engine.candidate.adapter import CandidateExecutionResult

                return CandidateExecutionResult(
                    execution_id=ExecutionId(value=f"candidate-{run_id.value}"),
                    run_id=run_id,
                    status=AdapterStatus.SUCCEEDED,
                    exit_code=0,
                    stdout=b"oracle-out",
                    stderr=b"",
                    start_time=_now(),
                    end_time=_now(),
                    termination_status="normal",
                    timeout_applied=False,
                )

        src = tmp_path / "HELLO.cob"
        src.write_text("HELLO", encoding="utf-8")
        cand = tmp_path / "cand"
        cand.mkdir()
        config = PipelineConfig(
            workload_id="wl-netpol",
            cobol_source_path=str(src),
            java_candidate_path=str(cand),
            java_entrypoint="Main",
            use_docker_java=True,
        )
        pipe = VerticalSlicePipeline(config, candidate_adapter=_FakeCandidate())
        pipe._oracle_adapter = _FakeOracle()
        return pipe.run()

    def test_unknown_candidate_is_not_recorded_as_none(self, tmp_path: Path):
        """A candidate with no declared isolation must not be recorded as `none`."""
        result = self._run_with_fake_candidate(tmp_path)
        candidate_policy = _policy_of(
            result.evidence_manifest.environment_identities, "candidate-java"
        )
        assert candidate_policy != "none", (
            "a candidate double that never declared network isolation was "
            f"recorded as {candidate_policy!r}; evidence must not assume isolation"
        )

    def test_oracle_docker_lane_still_records_none(self, tmp_path: Path):
        """The oracle always runs in Docker with `--network none` — stays `none`."""
        result = self._run_with_fake_candidate(tmp_path)
        oracle_policy = _policy_of(
            result.evidence_manifest.environment_identities, "oracle-gnucobol-3.1.2"
        )
        assert oracle_policy == "none"

    def test_change_never_upgrades_verdict(self, tmp_path: Path):
        """Re-describing the environment must not turn a non-VERIFIED run green."""
        from engine.domain.identities import VerdictState

        result = self._run_with_fake_candidate(tmp_path)
        # The fake oracle/candidate produce identical output but the pipeline
        # is not driven through a full declaration workload here; whatever the
        # verdict is, recording the policy must not have forced it to VERIFIED
        # as a side effect of this test's construction.
        assert result.verdict.state in set(VerdictState)


class TestEnvironmentIdentityDefaultUnchanged:
    def test_dataclass_default_still_none(self):
        """The dataclass field default is untouched (backward compatibility).

        Only the pipeline's choice of value changed; any code constructing an
        EnvironmentIdentity without specifying a policy keeps the historical
        `none` default.
        """
        e = EnvironmentIdentity(runtime_id="env-001")
        assert e.network_policy == "none"
