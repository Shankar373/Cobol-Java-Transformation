"""M6 tests — executed static cross-program CALL semantics.

Proves the full CALL chain for the MVP static form ``CALL 'PROGRAM-ID'``:

    discovery (CALL edge, no concatenation)
    -> COBOL IR (positioned CallStatement)
    -> Java IR (application-resolved static call node)
    -> Spring mapping (injected bean call, single-service entry)
    -> generated project (MainService invokes ClaimsService)
    -> Docker Maven build + JAR execution (call-chain output)
    -> independent GnuCOBOL oracle behaviour at the CALL boundary

Docker-free except the explicitly gated runtime classes at the end, which
skip cleanly when Docker is unavailable.

Known architectural boundary (asserted, not hidden): the GnuCOBOL oracle
adapter compiles a single COBOL module, so a cross-file CALL cannot link
on the oracle side. The committed Docker test pins the exact observed
behaviour (MAIN executes, reaches the CALL, module lookup fails) rather
than claiming oracle-side CALL execution.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Fixture workload (fresh, supported constructs only)
# ---------------------------------------------------------------------------

MAIN_COB = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. MAIN.\n"
    "       DATA DIVISION.\n"
    "       WORKING-STORAGE SECTION.\n"
    "       COPY COMMON.\n"
    "       01 WS-FLAG PIC X(1) VALUE 'N'.\n"
    "       PROCEDURE DIVISION.\n"
    "       MAIN-PARA.\n"
    '           DISPLAY "MAIN-START".\n'
    "           MOVE 'X' TO WS-FLAG.\n"
    "           CALL 'CLAIMS'.\n"
    '           DISPLAY "MAIN-END".\n'
    "           STOP RUN.\n"
)

CLAIMS_COB = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. CLAIMS.\n"
    "       DATA DIVISION.\n"
    "       WORKING-STORAGE SECTION.\n"
    "       COPY COMMON.\n"
    "       01 WS-DUMMY PIC X(1) VALUE 'N'.\n"
    "       PROCEDURE DIVISION.\n"
    "       CLAIM-PARA.\n"
    '           DISPLAY "CLAIMS-CALLED".\n'
    "           STOP RUN.\n"
)

COMMON_CPY = "       01 COMMON-REC PIC X(20).\n"

EXPECTED_CHAIN = ["MAIN-START", "CLAIMS-CALLED", "MAIN-END"]
SPRING_ENTRY = "com.generated.app.Application"
MAIN_SERVICE = "src/main/java/com/generated/app/service/Main.java"
CLAIMS_SERVICE = "src/main/java/com/generated/app/service/Claims.java"


def _write_fixture(tmp_path: Path) -> Path:
    (tmp_path / "MAIN.cob").write_text(MAIN_COB, encoding="utf-8")
    (tmp_path / "CLAIMS.cob").write_text(CLAIMS_COB, encoding="utf-8")
    (tmp_path / "COMMON.cpy").write_text(COMMON_CPY, encoding="utf-8")
    return tmp_path


def _discover(src_dir: str):
    from engine.transformation.application_discovery import ApplicationDiscovery
    return ApplicationDiscovery().discover(src_dir, application_id="call-app")


def _spring_project(tmp_path: Path):
    """Full Docker-free chain to a written Spring Boot project dir."""
    from engine.transformation.application_generator import ApplicationGenerator
    from engine.transformation.cobol_to_java_mapping import (
        map_cobol_programs_to_application,
    )
    from engine.transformation.java_to_spring_mapping import (
        map_java_application_to_spring_boot,
    )
    from engine.transformation.spring_boot_generator import SpringBootGenerator

    discovered = _discover(str(tmp_path))
    gen_result = ApplicationGenerator().generate(
        discovered, entrypoint="MAIN", source_root=tmp_path
    )
    assert gen_result.success

    programs = tuple(u.program for u in discovered.programs if u.program is not None)
    java_app = map_cobol_programs_to_application(
        programs=programs,
        application_id=discovered.application_id,
        copybooks=discovered.copybooks,
        edges=discovered.edges,
    )
    spring_app = map_java_application_to_spring_boot(java_app, entry_program="MAIN")
    assert spring_app.validate() == []

    project = tmp_path / "generated-app"
    for f in SpringBootGenerator().generate_project(spring_app):
        target = project / Path(*(Path(f.path or f.filename).parts))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f.source_code, encoding="utf-8")
    return discovered, spring_app, project


# ---------------------------------------------------------------------------
# 1. CALL edge discovered (no concatenation)
# ---------------------------------------------------------------------------

class TestCallDiscovery:
    def test_call_edge_present(self, tmp_path: Path) -> None:
        _write_fixture(tmp_path)
        app = _discover(str(tmp_path))

        assert {u.program_id for u in app.programs} == {"MAIN", "CLAIMS"}
        call_edges = [e for e in app.edges if e.edge_type == "CALL"]
        assert [(e.source, e.target) for e in call_edges] == [("MAIN", "CLAIMS")]
        # Copybook is a dependency, not a program.
        assert len(app.programs) == 2
        assert "COMMON" in app.copybooks


# ---------------------------------------------------------------------------
# 2. CALL survives COBOL -> Java transformation (positioned executable node)
# ---------------------------------------------------------------------------

class TestCallJavaMapping:
    def test_plain_java_contains_positioned_call(self, tmp_path: Path) -> None:
        _write_fixture(tmp_path)
        from engine.transformation.application_generator import ApplicationGenerator
        from engine.transformation.cobol_parser import CobolParser
        from engine.transformation.cobol_to_java_mapping import (
            map_cobol_programs_to_application,
        )
        from engine.transformation.java_generator import JavaGenerator

        discovered = _discover(str(tmp_path))
        parser = CobolParser()
        java_app = map_cobol_programs_to_application(
            (parser.parse(MAIN_COB), parser.parse(CLAIMS_COB)),
            application_id="call-app",
        )
        files = {
            f.class_name: f.source_code
            for f in JavaGenerator().generate_from_java(java_app)
        }

        main_src = files["Main"]
        start = main_src.index("MAIN-START")
        call = main_src.index("Claims.CLAIM_PARA();")
        end = main_src.index("MAIN-END")
        assert start < call < end
        # No unresolved-call comment left in the caller.
        assert "unresolved" not in main_src


# ---------------------------------------------------------------------------
# 3. CALL survives Java -> Spring Boot mapping
# ---------------------------------------------------------------------------

class TestCallSpringMapping:
    def test_main_service_depends_on_claims(self, tmp_path: Path) -> None:
        _write_fixture(tmp_path)
        _, spring_app, _ = _spring_project(tmp_path)

        by_name = {s.name: s for s in spring_app.services}
        assert set(by_name) == {"Main", "Claims"}
        assert by_name["Main"].depends_on == ("Claims",)
        assert by_name["Main"].source_program == "MAIN"
        assert by_name["Claims"].source_program == "CLAIMS"

    def test_call_body_uses_bean_reference(self, tmp_path: Path) -> None:
        _write_fixture(tmp_path)
        _, spring_app, _ = _spring_project(tmp_path)

        main = next(s for s in spring_app.services if s.name == "Main")
        body_names: list[str] = []

        def _walk(stmt) -> None:
            from engine.transformation.java_ir import (
                JavaBlock, JavaIf, JavaMethodCallStatement,
            )
            if isinstance(stmt, JavaMethodCallStatement):
                body_names.append(
                    (str(stmt.call.object_ref), stmt.call.method_name)
                )
            elif isinstance(stmt, JavaIf):
                for s in stmt.then_body + stmt.else_body:
                    _walk(s)
            elif isinstance(stmt, JavaBlock):
                for s in stmt.statements:
                    _walk(s)

        for method in main.methods:
            for stmt in method.body_statements:
                _walk(stmt)

        assert any(
            ref == "JavaVariableRef(name='claims')" and name == "CLAIM_PARA"
            for ref, name in body_names
        )


# ---------------------------------------------------------------------------
# 4-6. Generated project: DI dependency, single-service entry, call order
# ---------------------------------------------------------------------------

class TestGeneratedCallProject:
    def test_main_service_injects_claims(self, tmp_path: Path) -> None:
        _write_fixture(tmp_path)
        _, _, project = _spring_project(tmp_path)

        main_src = (project / MAIN_SERVICE).read_text(encoding="utf-8")
        assert "private final Claims claims;" in main_src
        assert "public Main(Claims claims)" in main_src

    def test_entry_runs_only_main_service(self, tmp_path: Path) -> None:
        _write_fixture(tmp_path)
        _, _, project = _spring_project(tmp_path)

        entry_src = (
            project / "src/main/java/com/generated/app/Application.java"
        ).read_text(encoding="utf-8")
        assert "main.MAIN_PARA();" in entry_src
        # ClaimsService is reached through the CALL, never independently.
        assert "claims." not in entry_src.lower().replace("claims claims", "")

    def test_call_chain_order_in_main_service(self, tmp_path: Path) -> None:
        _write_fixture(tmp_path)
        _, _, project = _spring_project(tmp_path)

        main_src = (project / MAIN_SERVICE).read_text(encoding="utf-8")
        start = main_src.index("MAIN-START")
        call = main_src.index("claims.CLAIM_PARA();")
        end = main_src.index("MAIN-END")
        assert start < call < end


# ---------------------------------------------------------------------------
# Docker-gated: 7. build, 8. call-chain output, 9. oracle CALL boundary
# ---------------------------------------------------------------------------

def _docker_available() -> bool:
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


needs_docker = pytest.mark.skipif(
    not _docker_available(), reason="Docker not available"
)


@needs_docker
class TestDockerCallChain:
    def test_generated_project_builds(self, tmp_path: Path) -> None:
        _write_fixture(tmp_path)
        _, _, project = _spring_project(tmp_path)

        from engine.candidate.adapter import CandidateManifest
        from engine.candidate.docker_spring_boot_adapter import (
            DockerSpringBootCandidateAdapter,
        )

        manifest = CandidateManifest(
            candidate_id="call-app",
            workload_id="wl-call",
            source_hash="test",
            generated_files={"pom.xml": "test"},
            entrypoint=SPRING_ENTRY,
        )
        result = DockerSpringBootCandidateAdapter().compile(
            str(project), manifest
        )
        assert result.success, result.compilation_errors
        assert list((project / "target").glob("*.jar"))

    def test_generated_app_produces_call_chain_output(
        self, tmp_path: Path
    ) -> None:
        _write_fixture(tmp_path)
        _, _, project = _spring_project(tmp_path)

        from engine.candidate.adapter import CandidateManifest
        from engine.candidate.docker_spring_boot_adapter import (
            DockerSpringBootCandidateAdapter,
        )
        from engine.domain.identities import RunId

        manifest = CandidateManifest(
            candidate_id="call-app",
            workload_id="wl-call",
            source_hash="test",
            generated_files={"pom.xml": "test"},
            entrypoint=SPRING_ENTRY,
        )
        adapter = DockerSpringBootCandidateAdapter()
        compilation = adapter.compile(str(project), manifest)
        assert compilation.success, compilation.compilation_errors

        outcome = adapter.execute(
            RunId(value="run-call-test"), str(project), manifest
        )
        lines = outcome.stdout.decode(errors="replace").splitlines()
        assert lines == EXPECTED_CHAIN
        assert outcome.exit_code == 0

    def test_oracle_reaches_call_without_callee_module(
        self, tmp_path: Path
    ) -> None:
        """Pins the oracle-side boundary: MAIN executes standalone through
        the real DockerOracleAdapter, prints MAIN-START (proof it reached
        the CALL), then fails resolving the cross-file module.

        The fixture dir holds ONLY MAIN.cob (+copybook) so adapter file
        selection is deterministic.
        """
        (tmp_path / "MAIN.cob").write_text(MAIN_COB, encoding="utf-8")
        (tmp_path / "COMMON.cpy").write_text(COMMON_CPY, encoding="utf-8")

        from engine.domain.identities import RunId
        from engine.oracle.adapter import OracleAdapterConfig
        from engine.oracle.docker_adapter import DockerOracleAdapter

        adapter = DockerOracleAdapter(OracleAdapterConfig(
            oracle_id="gnucobol-3.1.2",
            image_digest=DockerOracleAdapter.V1_DIGEST,
            compiler_version="3.1.2.0",
            timeout_seconds=60,
        ))
        outcome = adapter.execute(RunId(value="run-call-oracle"), str(tmp_path))

        stdout = outcome.stdout.decode(errors="replace")
        stderr = outcome.stderr.decode(errors="replace")
        # MAIN really executed up to the CALL boundary...
        assert "MAIN-START" in stdout
        assert "MAIN-END" not in stdout
        # ...then the single-module oracle could not resolve the callee.
        assert outcome.exit_code != 0
        assert "CLAIMS" in stderr
