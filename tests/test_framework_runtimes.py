"""Phase 3 — Quarkus and Micronaut runtime targets (command mode).

The framework targets reuse the plain_java program classes unchanged and add
one entry class that runs the COBOL run unit inside the framework container
(``@QuarkusMain`` / ``ApplicationContext``), plus a pom that builds exactly one
runnable jar.  Docker-free: registry, assembly shape, shared sources, scope
disclosure, application servers refused, offline precache in sync with the
adapters.  Docker lane: offline build in the Maven image, ``java -jar`` in the
hardened runtime container, byte-for-byte stdout and exit code against
GnuCOBOL 3.1.2 (exit code 4 set by RETURN-CODE crosses the framework).
"""
from __future__ import annotations

import pathlib
import subprocess
import sys
import uuid

import pytest

from engine.modernization.pipeline import (
    ModernizationConfig,
    UniversalModernizationPipeline,
)
from engine.transformation.runtime_adapters import (
    MICRONAUT_PLATFORM_VERSION,
    QUARKUS_VERSION,
    get_runtime_adapter,
    plan_output_type_for,
)

REPO = pathlib.Path(__file__).resolve().parents[1]
FRAMEWORKS = ("quarkus", "micronaut")
ENTRY_CLASS = {"quarkus": "CobolQuarkusMain", "micronaut": "CobolMicronautMain"}

_HELLO_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HELLO.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-NUM  PIC 9(4) VALUE 42.
       PROCEDURE DIVISION.
           DISPLAY WS-NUM
           STOP RUN.
"""


def _generate(tmp_path: pathlib.Path, target: str, source: str = _HELLO_SOURCE,
              program: str = "HELLO"):
    src = tmp_path / f"src-{target}"
    src.mkdir()
    (src / f"{program}.cob").write_text(source, encoding="utf-8")
    report = UniversalModernizationPipeline(
        ModernizationConfig(
            source_dir=str(src),
            output_dir=str(tmp_path / f"out-{target}"),
            application_id=f"fw-{target}",
            entrypoint=program,
            docker_available=True,
            target_runtime=target,
        )
    ).execute()
    assert report.generation_success is True, report.generation_errors
    project = pathlib.Path(report.generated_project_dir)
    files = {
        p.relative_to(project).as_posix(): p.read_text(encoding="utf-8")
        for p in sorted(project.rglob("*"))
        if p.is_file()
    }
    return report, project, files


class TestRegistry:
    @pytest.mark.parametrize("target", FRAMEWORKS)
    def test_adapter_resolves(self, target):
        adapter = get_runtime_adapter(target)
        assert adapter.target_runtime == target
        assert plan_output_type_for(target) == target.upper()

    @pytest.mark.parametrize("target", FRAMEWORKS)
    def test_candidate_lane_is_the_maven_lane(self, target):
        from engine.candidate.factory import candidate_adapter_for_target
        from engine.candidate.maven_adapter import MavenProjectCandidateAdapter

        assert isinstance(
            candidate_adapter_for_target(target), MavenProjectCandidateAdapter
        )

    @pytest.mark.parametrize(
        "server", ["wildfly", "open_liberty", "liberty", "payara", "tomee"]
    )
    def test_application_servers_are_not_targets(self, server):
        # Deferred (documented as not supported): an application-server
        # target is an unknown value, never a fallback to another lane.
        from engine.candidate.factory import candidate_adapter_for_target

        with pytest.raises(ValueError, match="invalid target_runtime"):
            get_runtime_adapter(server)
        with pytest.raises(ValueError):
            candidate_adapter_for_target(server)


class TestAssembly:
    @pytest.mark.parametrize("target", FRAMEWORKS)
    def test_project_shape(self, tmp_path, target):
        report, _, files = _generate(tmp_path, target)
        entry = ENTRY_CLASS[target]
        assert report.target_runtime == target
        assert report.transformation_plan.assembly.output_type == target.upper()
        assert f"src/main/java/{entry}.java" in files
        assert "src/main/java/Hello.java" in files
        # The entry class runs the COBOL run unit (the program's main).
        assert "Hello.main(args);" in files[f"src/main/java/{entry}.java"]
        pom = files["pom.xml"]
        assert "<maven.compiler.release>21</maven.compiler.release>" in pom
        for content in files.values():
            assert "spring" not in content.lower()
        if target == "quarkus":
            assert "@QuarkusMain" in files[f"src/main/java/{entry}.java"]
            assert f"<quarkus.version>{QUARKUS_VERSION}</quarkus.version>" in pom
            props = files["src/main/resources/application.properties"]
            # stdout stays the program's own; one runnable jar in target/.
            assert "quarkus.banner.enabled=false" in props
            assert "quarkus.log.console.enable=false" in props
            assert "quarkus.package.jar.type=uber-jar" in props
            assert "quarkus.package.jar.add-runner-suffix=false" in props
        else:
            assert "ApplicationContext.run()" in files[f"src/main/java/{entry}.java"]
            assert f"<version>{MICRONAUT_PLATFORM_VERSION}</version>" in pom
            assert f"<mainClass>{entry}</mainClass>" in pom
            # The thin jar leaves target/ so the shaded jar is the only one.
            assert "${project.build.directory}/thin" in pom
            assert "slf4j-nop" in pom

    @pytest.mark.parametrize("target", FRAMEWORKS)
    def test_program_sources_identical_to_plain_java(self, tmp_path, target):
        # One transform, many runtimes: the framework project carries the
        # plain_java program classes byte for byte.
        _, _, plain = _generate(tmp_path, "plain_java")
        _, _, framework = _generate(tmp_path, target)
        plain_sources = {k: v for k, v in plain.items() if k.endswith(".java")}
        framework_sources = {
            k: v for k, v in framework.items()
            if k.endswith(".java") and not k.endswith(f"/{ENTRY_CLASS[target]}.java")
        }
        assert framework_sources == plain_sources

    @pytest.mark.parametrize("target", FRAMEWORKS)
    def test_scope_is_disclosed(self, tmp_path, target):
        report, _, _ = _generate(tmp_path, target)
        disclosure = "; ".join(report.limitations)
        assert f"target_runtime={target}: command-mode application" in disclosure
        assert "no HTTP endpoints" in disclosure


def test_offline_precache_matches_adapters():
    # Dockerfile.maven-offline pre-caches docker/maven-precache; a pom or
    # entry-class change in the adapters must regenerate it, or the offline
    # build of every generated framework project would fail.
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "generate_framework_precache.py"),
         "--check"],
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    dockerfile = (REPO / "Dockerfile.maven-offline").read_text(encoding="utf-8")
    assert "COPY docker/maven-precache /tmp/fwprecache" in dockerfile
    assert "for fw in quarkus micronaut" in dockerfile


_BATCH_RC = REPO / "fixtures" / "workload-batch-rc" / "cobol"


@pytest.mark.docker
@pytest.mark.parametrize("target", FRAMEWORKS)
def test_framework_jar_matches_gnucobol_exactly(tmp_path, target):
    """Offline build + hardened ``java -jar`` vs GnuCOBOL: identical stdout
    bytes, identical exit code (RETURN-CODE 4), and no framework output."""
    from engine.candidate.docker_spring_boot_adapter import CandidateManifest
    from engine.candidate.factory import candidate_adapter_for_target
    from engine.domain.identities import RunId
    from engine.oracle.adapter import OracleAdapterConfig
    from engine.oracle.docker_adapter import DockerOracleAdapter

    source = (_BATCH_RC / "VALIDATE.cob").read_text(encoding="utf-8")
    _, project, _ = _generate(tmp_path, target, source=source, program="VALIDATE")
    manifest = CandidateManifest(
        candidate_id=f"fw-{target}", workload_id=f"wl-fw-{target}",
        source_hash="test", generated_files={"pom.xml": "test"},
        entrypoint=ENTRY_CLASS[target],
    )
    run_id = RunId(value=f"fw-{target}-{uuid.uuid4().hex[:8]}")

    candidate = candidate_adapter_for_target(target)
    built = candidate.compile(str(project), manifest)
    assert built.success, built.compilation_errors
    executed = candidate.execute(run_id, str(project), manifest)

    oracle = DockerOracleAdapter(
        OracleAdapterConfig(
            oracle_id=f"gnucobol-fw-{target}", image_digest="",
            compiler_version="3.1.2.0",
        )
    )
    expected = oracle.execute(
        run_id=run_id, source_path=str(_BATCH_RC), entry_program="VALIDATE"
    )
    assert expected.exit_code == 4, expected
    assert executed.stdout == expected.stdout, (executed.stdout, expected.stdout)
    assert executed.exit_code == expected.exit_code
    assert executed.stderr == b"", executed.stderr
