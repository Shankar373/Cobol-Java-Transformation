"""Docker availability must drive capability levels — never a hardcoded True.

P0 regression (release blocker): the capability report used to assume Docker
was always present, claiming runtime capability the host may not have.  This
file pins the full mapping from a *probed* ``docker_available`` flag to the
reported capability level, including the two fail-closed edges that a
success-happy probe would get wrong:

* daemon absent  -> UNAVAILABLE  (not SUPPORTED, not UNKNOWN);
* probe *timeout* -> UNAVAILABLE (a hung daemon is not a present daemon);
* probe raising  -> UNAVAILABLE (an erroring daemon is not a present daemon).

It also pins the ``ModernizationConfig`` default: constructing the pipeline
without an explicit probe must not silently assert Docker availability.

Dependency-light on purpose: only ``engine.docker_cli`` (stdlib ``subprocess``)
and ``engine.modernization`` are imported, so this stays in the fast
capability-truth gate.
"""

from __future__ import annotations

import subprocess

import pytest

from engine import docker_cli
from engine.modernization.capability_analyzer import (
    CapabilityAnalyzer,
    CapabilityLevel,
)
from engine.modernization.pipeline import ModernizationConfig
from engine.transformation.ir import (
    CobolApplication,
    CobolProgram,
    CobolProgramUnit,
    MoveStatement,
    Paragraph,
)


def _simple_app() -> CobolApplication:
    """A minimal, fully-supported workload (one MOVE)."""
    program = CobolProgram(program_id="SIMPLE", paragraphs=(
        Paragraph(name="MAIN", statements=(
            MoveStatement(source="1", target="A"),
        )),
    ))
    return CobolApplication(application_id="APP", programs=(
        CobolProgramUnit(program_id="SIMPLE", source_path="MAIN.cob", program=program),
    ))


def _program_component(report):
    return next(c for c in report.components if c.component_type == "PROGRAM")


class TestDockerProbeDrivesCapabilityLevel:
    """``docker_available`` must be honoured, not assumed."""

    def test_docker_available_supports_simple_workload(self):
        report = CapabilityAnalyzer(docker_available=True).analyze(_simple_app())
        assert _program_component(report).level == CapabilityLevel.SUPPORTED

    def test_docker_unavailable_downgrades_to_unavailable(self):
        report = CapabilityAnalyzer(docker_available=False).analyze(_simple_app())
        cap = _program_component(report)
        assert cap.level == CapabilityLevel.UNAVAILABLE
        assert "Docker" in cap.reason

    def test_unavailable_never_reports_supported(self):
        """The regression that must never come back: a present-looking level."""
        report = CapabilityAnalyzer(docker_available=False).analyze(_simple_app())
        for comp in report.components:
            assert comp.level != CapabilityLevel.SUPPORTED, (
                f"component {comp.component_id!r} claimed SUPPORTED without "
                "Docker: capability level must reflect runtime availability"
            )

    def test_overall_level_is_never_supported_without_docker(self):
        report = CapabilityAnalyzer(docker_available=False).analyze(_simple_app())
        assert report.overall_level != CapabilityLevel.SUPPORTED


class TestProbeFailClosedEdges:
    """A probe that cannot succeed must read as absent, not present."""

    def test_probe_returns_false_when_binary_missing(self, monkeypatch):
        def _raise(*args, **kwargs):
            raise FileNotFoundError("docker not on PATH")
        monkeypatch.setattr(docker_cli.subprocess, "run", _raise)
        assert docker_cli.check_docker_available() is False

    def test_probe_returns_false_on_timeout(self, monkeypatch):
        def _raise(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd="docker", timeout=10)
        monkeypatch.setattr(docker_cli.subprocess, "run", _raise)
        assert docker_cli.check_docker_available() is False

    def test_probe_returns_false_on_nonzero_exit(self, monkeypatch):
        monkeypatch.setattr(
            docker_cli.subprocess, "run",
            lambda *a, **k: subprocess.CompletedProcess(args=["docker"], returncode=1),
        )
        assert docker_cli.check_docker_available() is False

    def test_probe_returns_true_on_success(self, monkeypatch):
        monkeypatch.setattr(
            docker_cli.subprocess, "run",
            lambda *a, **k: subprocess.CompletedProcess(args=["docker"], returncode=0),
        )
        assert docker_cli.check_docker_available() is True

    @pytest.mark.parametrize("outcome", ["timeout", "missing", "error"])
    def test_unsuccessful_probe_maps_to_unavailable_capability(self, monkeypatch, outcome):
        """Whichever way the probe fails, capability stays UNAVAILABLE."""
        if outcome == "timeout":
            def _raise(*a, **k):
                raise subprocess.TimeoutExpired(cmd="docker", timeout=10)
        elif outcome == "missing":
            def _raise(*a, **k):
                raise FileNotFoundError("docker not on PATH")
        else:
            def _raise(*a, **k):
                raise OSError("daemon connection refused")
        monkeypatch.setattr(docker_cli.subprocess, "run", _raise)

        available = docker_cli.check_docker_available()
        report = CapabilityAnalyzer(docker_available=available).analyze(_simple_app())
        cap = _program_component(report)
        assert available is False
        assert cap.level == CapabilityLevel.UNAVAILABLE


class TestUnsupportedWorkloadStaysUnsupportedWithDocker:
    """Runtime availability cannot upgrade an unsupported workload.

    Docker being present must not turn an out-of-scope construct into a
    claim of support: capability reflects the *workload* capability too.
    """

    def _program_with_out_of_scope_statement(self):
        from engine.transformation.ir import (
            CobolProgram,
            CobolProgramUnit,
            Paragraph,
        )

        class UnrecognizedStatement:
            """An IR node no transformer claims (stands in for out-of-scope)."""

            def __init__(self) -> None:
                self.value = "future-cics-command"

        program = CobolProgram(program_id="OUTSIDE", paragraphs=(
            Paragraph(name="MAIN", statements=(UnrecognizedStatement(),)),
        ))
        return CobolApplication(application_id="APP", programs=(
            CobolProgramUnit(
                program_id="OUTSIDE",
                source_path="MAIN.cob",
                program=program,
            ),
        ))

    def test_docker_present_does_not_upgrade_unsupported(self):
        report = CapabilityAnalyzer(docker_available=True).analyze(
            self._program_with_out_of_scope_statement()
        )
        cap = _program_component(report)
        assert cap.level == CapabilityLevel.UNSUPPORTED
        assert "Unrecognized/unmapped IR statement" in cap.reason

    def test_unparseable_program_is_unsupported_not_supported(self):
        from engine.transformation.ir import CobolProgramUnit, Paragraph

        app = CobolApplication(application_id="APP", programs=(
            CobolProgramUnit(
                program_id="BROKEN",
                source_path="MAIN.cob",
                program=None,
                parse_error="COBOL01 unexpected token",
            ),
        ))
        report = CapabilityAnalyzer(docker_available=True).analyze(app)
        cap = _program_component(report)
        assert cap.level == CapabilityLevel.UNSUPPORTED
        assert "Failed to parse program" in cap.reason

    def test_docker_flag_never_forces_unsupported_to_supported(self):
        """The regression guard: availability is necessary, never sufficient."""
        app = self._program_with_out_of_scope_statement()
        with_docker = CapabilityAnalyzer(docker_available=True).analyze(app)
        assert _program_component(with_docker).level is not (
            CapabilityLevel.SUPPORTED
        )


class TestModernizationConfigIsFailClosedByDefault:
    """Constructing the pipeline without a probe must not assert Docker."""

    def test_default_docker_available_is_false(self):
        cfg = ModernizationConfig(source_dir="s", output_dir="o")
        assert cfg.docker_available is False

    def test_explicit_true_is_honoured(self):
        cfg = ModernizationConfig(source_dir="s", output_dir="o", docker_available=True)
        assert cfg.docker_available is True

    def test_service_layer_probes_live_not_hardcoded(self):
        """api.service must call the live probe, never a literal True."""
        import inspect
        from api import service as svc

        src = inspect.getsource(svc.Service._generate_application)
        assert "docker_cli.check_docker_available()" in src, (
            "_generate_application must probe Docker via docker_cli"
        )
        assert "docker_available=True" not in src, (
            "hardcoded docker_available=True re-introduces the P0 capability lie"
        )
