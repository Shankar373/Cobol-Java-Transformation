"""Build failures preserve Maven's stdout diagnostics and exit status."""
import subprocess
from tests.test_phase4_business_logic_verified import requires_docker

from engine.candidate.docker_spring_boot_adapter import (
    DockerSpringBootCandidateAdapter, DockerSpringBootConfig, CandidateManifest,
)
from engine.domain.identities import AdapterStatus


def test_maven_failure_keeps_both_streams_and_does_not_claim_missing_jar(tmp_path, monkeypatch):
    adapter = object.__new__(DockerSpringBootCandidateAdapter)
    adapter._status = AdapterStatus.AVAILABLE
    adapter._config = DockerSpringBootConfig()
    (tmp_path / "pom.xml").write_text("<project/>")
    commands = []
    def fail(command, **kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 1, b"[ERROR] unreachable statement\n", b"compiler failed\n")
    monkeypatch.setattr(subprocess, "run", fail)
    result = adapter.compile(str(tmp_path), CandidateManifest(
        candidate_id="regression", workload_id="regression", source_hash="test",
        generated_files={"pom.xml": "test"}, entrypoint="Main",
    ))
    assert not result.success
    assert result.class_files == {}
    assert "exit 1" in result.compilation_errors[0]
    assert "[ERROR] unreachable statement\n" in result.compilation_errors[0]
    assert "compiler failed\n" in result.compilation_errors[0]
    assert "no JAR" not in result.compilation_errors[0]
    assert "|| true" not in commands[0][-1]


@requires_docker
def test_real_maven_failure_reports_first_error(tmp_path):
    (tmp_path / "pom.xml").write_text("<project><broken>", encoding="utf-8")
    result = DockerSpringBootCandidateAdapter().compile(str(tmp_path), CandidateManifest(
        candidate_id="bad-pom", workload_id="bad-pom", source_hash="test",
        generated_files={"pom.xml": "test"}, entrypoint="Main",
    ))
    assert not result.success
    assert result.class_files == {}
    assert "pom.xml" in result.compilation_errors[0]
    assert "ProjectBuildingException" in result.compilation_errors[0]
    assert "no JAR" not in result.compilation_errors[0]
