"""Maven build staging and jar selection are deterministic (audit V13).

* Staging skipped every path containing a ``target`` directory, so a Java
  package named ``target`` was silently dropped from the build; only the
  project's top-level ``target/`` (build output) is excluded now.
* Which jar ran depended on directory order when a build produced more than
  one; more than one jar is now a build failure, and execution refuses to
  choose between several.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from engine.candidate.adapter import CandidateManifest
from engine.domain.identities import AdapterStatus


def _adapter(monkeypatch, fake_run):
    import engine.candidate.docker_spring_boot_adapter as mod

    adapter = object.__new__(mod.DockerSpringBootCandidateAdapter)
    adapter._status = AdapterStatus.AVAILABLE
    adapter._config = mod.DockerSpringBootConfig()
    monkeypatch.setattr(adapter, "_fresh_build_ref", lambda: ("img@sha256:" + "a" * 64, ""))
    monkeypatch.setattr(adapter, "_cleanup_container", lambda name: (True, "removed"))
    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    return adapter


def _mount(cmd: list[str], container_path: str) -> Path:
    for i, arg in enumerate(cmd):
        if arg == "-v" and cmd[i + 1].endswith(":" + container_path):
            return Path(cmd[i + 1][: -len(":" + container_path)])
        if arg.startswith("--mount") or arg == "--mount":
            continue
    raise AssertionError(f"no mount for {container_path}: {cmd}")


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    (project / "src" / "main" / "java" / "com" / "acme" / "target").mkdir(parents=True)
    (project / "src" / "main" / "java" / "com" / "acme" / "target" / "Rule.java").write_text("class Rule {}")
    (project / "pom.xml").write_text("<project/>")
    (project / "target").mkdir()
    (project / "target" / "old.jar").write_bytes(b"stale build output")
    return project


def test_package_named_target_is_staged_and_build_output_is_not(tmp_path, monkeypatch):
    seen: dict[str, list[str]] = {}

    def fake_run(cmd, **kwargs):
        staged = _mount(cmd, "/workspace/project")
        seen["files"] = sorted(p.relative_to(staged).as_posix() for p in staged.rglob("*") if p.is_file())
        (_mount(cmd, "/workspace/output") / "app.jar").write_bytes(b"PK jar")
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    project = _project(tmp_path)
    result = _adapter(monkeypatch, fake_run).compile(str(project), CandidateManifest(
        candidate_id="v13", workload_id="v13", source_hash="x",
        generated_files={"pom.xml": "x"}, entrypoint="Main",
    ))
    assert "src/main/java/com/acme/target/Rule.java" in seen["files"], seen
    assert "target/old.jar" not in seen["files"], seen
    assert result.success is True, result.compilation_errors
    # The stale jar of an earlier build is gone; only this build's remains.
    assert sorted(p.name for p in (project / "target").glob("*.jar")) == ["app.jar"]


def test_two_built_jars_fail_the_build(tmp_path, monkeypatch):
    def fake_run(cmd, **kwargs):
        out = _mount(cmd, "/workspace/output")
        (out / "a.jar").write_bytes(b"PK a")
        (out / "b.jar").write_bytes(b"PK b")
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    result = _adapter(monkeypatch, fake_run).compile(str(_project(tmp_path)), CandidateManifest(
        candidate_id="v13", workload_id="v13", source_hash="x",
        generated_files={"pom.xml": "x"}, entrypoint="Main",
    ))
    assert result.success is False
    assert "more than one JAR" in result.compilation_errors[0]
