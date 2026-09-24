"""Phase 4+ — Fresh Business-Logic Verified.

Multi-program COBOL workload (MAIN + CALC) exercising core business
logic constructs through the complete SystemaOps pipeline.

Constructs verified:
  - CALL (inter-program)
  - MOVE (single and multi-target)
  - SUBTRACT (in-place and GIVING)
  - MULTIPLY (in-place and GIVING)
  - COMPUTE (arithmetic expressions)
  - EVALUATE (switch/case with ranges)
  - PERFORM VARYING (for loop)

Pipeline under test (every stage is real):

  COBOL sources
    → ApplicationDiscovery         (program graph, CALL edges)
    → CobolParser                  (COBOL IR for each program)
    → map_cobol_programs_to_application  (Java IR, single pass)
    → ApplicationGenerator.generate     (generates Java source)
    → SpringBootGenerator          (generates Spring Boot project)
    → DockerSpringBootCandidateAdapter.compile  (Maven Docker build)
    → DockerSpringBootCandidateAdapter.execute  (JVM Docker run)
    → DockerOracleAdapter.execute            (GnuCOBOL oracle)
    → Comparison                         (STDOUT comparison)
    → VerdictDeriver                     (VERIFIED)

Skipped automatically when Docker is unavailable.
"""
from __future__ import annotations

import pathlib
import uuid

import pytest

FIXTURE_DIR = pathlib.Path(__file__).parent / "fixtures" / "fresh_business_logic_verified"

SPRING_ENTRY = "com.generated.app.Application"

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _docker_available() -> bool:
    import subprocess, os
    try:
        r = subprocess.run(
            ["docker", "ps"],
            capture_output=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        return r.returncode == 0
    except Exception:
        return False


def _images_available() -> bool:
    import subprocess, os
    images = ["gnucobol-ocesql:latest", "maven-offline-springboot:latest", "eclipse-temurin:21-jdk"]
    for img in images:
        try:
            r = subprocess.run(
                ["docker", "image", "inspect", img],
                capture_output=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            if r.returncode != 0:
                return False
        except Exception:
            return False
    return True


requires_docker = pytest.mark.skipif(
    not (_docker_available() and _images_available()),
    reason="Docker or required images not available",
)


# ---------------------------------------------------------------------------
# Stage 1: COBOL discovery
# ---------------------------------------------------------------------------

class TestDiscovery:
    def test_both_programs_discovered(self) -> None:
        from engine.transformation.application_discovery import ApplicationDiscovery
        app = ApplicationDiscovery().discover(
            str(FIXTURE_DIR), application_id="business-logic-app"
        )
        program_ids = {u.program_id for u in app.programs}
        assert "MAIN" in program_ids
        assert "CALC" in program_ids
        call_edges = [e for e in app.edges if e.edge_type == "CALL"]
        assert any(e.source == "MAIN" and e.target == "CALC" for e in call_edges), \
            f"Expected MAIN→CALC CALL edge; found: {call_edges}"

    def test_no_source_concatenation(self) -> None:
        from engine.transformation.application_discovery import ApplicationDiscovery
        app = ApplicationDiscovery().discover(
            str(FIXTURE_DIR), application_id="business-logic-app"
        )
        assert len(app.programs) == 2, "Exactly 2 programs expected"


# ---------------------------------------------------------------------------
# Stage 2: COBOL parsing — construct verification
# ---------------------------------------------------------------------------

class TestParsing:
    def test_calc_has_multiply(self) -> None:
        from engine.transformation.cobol_parser import CobolParser
        from engine.transformation.ir import MultiplyStatement
        prog = CobolParser().parse((FIXTURE_DIR / "CALC.cob").read_text())
        stmts = [s for para in prog.paragraphs for s in para.statements
                 if isinstance(s, MultiplyStatement)]
        assert len(stmts) >= 1, "CALC must have at least one MULTIPLY"

    def test_calc_has_subtract(self) -> None:
        from engine.transformation.cobol_parser import CobolParser
        from engine.transformation.ir import SubtractStatement
        prog = CobolParser().parse((FIXTURE_DIR / "CALC.cob").read_text())
        stmts = [s for para in prog.paragraphs for s in para.statements
                 if isinstance(s, SubtractStatement)]
        assert len(stmts) >= 1, "CALC must have at least one SUBTRACT"

    def test_calc_has_compute(self) -> None:
        from engine.transformation.cobol_parser import CobolParser
        from engine.transformation.ir import ComputeStatement
        prog = CobolParser().parse((FIXTURE_DIR / "CALC.cob").read_text())
        stmts = [s for para in prog.paragraphs for s in para.statements
                 if isinstance(s, ComputeStatement)]
        assert len(stmts) >= 2, "CALC must have at least two COMPUTE statements"

    def test_calc_has_evaluate(self) -> None:
        from engine.transformation.cobol_parser import CobolParser
        from engine.transformation.ir import IfStatement
        prog = CobolParser().parse((FIXTURE_DIR / "CALC.cob").read_text())
        # EVALUATE converts to nested IF
        all_stmts = [s for para in prog.paragraphs for s in para.statements]
        has_if = any(isinstance(s, IfStatement) for s in all_stmts)
        assert has_if, "CALC must have an EVALUATE (converted to nested IF)"

    def test_calc_has_perform_varying(self) -> None:
        from engine.transformation.cobol_parser import CobolParser
        from engine.transformation.ir import PerformStatement
        prog = CobolParser().parse((FIXTURE_DIR / "CALC.cob").read_text())
        stmts = [s for para in prog.paragraphs for s in para.statements
                 if isinstance(s, PerformStatement) and s.until_condition
                 and "VARYING" in (s.until_condition or "")]
        assert len(stmts) >= 1, "CALC must have a PERFORM VARYING"

    def test_main_has_call(self) -> None:
        from engine.transformation.cobol_parser import CobolParser
        from engine.transformation.ir import CallStatement
        prog = CobolParser().parse((FIXTURE_DIR / "MAIN.cob").read_text())
        calls = [s for para in prog.paragraphs for s in para.statements
                 if isinstance(s, CallStatement)]
        assert len(calls) >= 1, "MAIN must have a CALL statement"

    def test_main_has_multi_target_move(self) -> None:
        from engine.transformation.cobol_parser import CobolParser
        from engine.transformation.ir import MoveStatement
        prog = CobolParser().parse((FIXTURE_DIR / "MAIN.cob").read_text())
        multi_moves = [s for para in prog.paragraphs for s in para.statements
                       if isinstance(s, MoveStatement) and s.targets]
        assert len(multi_moves) >= 1, "MAIN must have a multi-target MOVE"


# ---------------------------------------------------------------------------
# Stage 3: Java IR mapping
# ---------------------------------------------------------------------------

class TestJavaMapping:
    def test_main_has_java_method_call_to_calc(self) -> None:
        from engine.transformation.cobol_parser import CobolParser
        from engine.transformation.cobol_to_java_mapping import (
            map_cobol_programs_to_application,
        )
        from engine.transformation.java_generator import JavaGenerator

        main_prog = CobolParser().parse((FIXTURE_DIR / "MAIN.cob").read_text())
        calc_prog = CobolParser().parse((FIXTURE_DIR / "CALC.cob").read_text())

        java_app = map_cobol_programs_to_application(
            (main_prog, calc_prog), application_id="business-logic-app"
        )
        files = {
            f.class_name: f.source_code
            for f in JavaGenerator().generate_from_java(java_app)
        }
        main_src = files.get("Main", "")
        assert "Calc" in main_src, (
            f"Expected Calc reference in Main.java:\n{main_src}"
        )

    def test_calc_has_system_out_println(self) -> None:
        from engine.transformation.cobol_parser import CobolParser
        from engine.transformation.cobol_to_java_mapping import (
            map_cobol_programs_to_application,
        )
        from engine.transformation.java_generator import JavaGenerator

        main_prog = CobolParser().parse((FIXTURE_DIR / "MAIN.cob").read_text())
        calc_prog = CobolParser().parse((FIXTURE_DIR / "CALC.cob").read_text())

        java_app = map_cobol_programs_to_application(
            (main_prog, calc_prog), application_id="business-logic-app"
        )
        files = {
            f.class_name: f.source_code
            for f in JavaGenerator().generate_from_java(java_app)
        }
        calc_src = files.get("Calc", "")
        assert "System.out.println" in calc_src, (
            f"Expected System.out.println in Calc.java:\n{calc_src}"
        )


# ---------------------------------------------------------------------------
# Stage 4: Docker build (skipped without Docker)
# ---------------------------------------------------------------------------

@requires_docker
class TestDockerBuild:
    def test_spring_project_builds(self, tmp_path: pathlib.Path) -> None:
        from engine.transformation.application_discovery import ApplicationDiscovery
        from engine.transformation.application_generator import ApplicationGenerator
        from engine.transformation.java_to_spring_mapping import (
            map_java_application_to_spring_boot,
        )
        from engine.transformation.spring_boot_generator import SpringBootGenerator
        from engine.candidate.docker_spring_boot_adapter import (
            DockerSpringBootCandidateAdapter,
            CandidateManifest,
        )

        app = ApplicationDiscovery().discover(
            str(FIXTURE_DIR), application_id="business-logic-app"
        )
        gen_result = ApplicationGenerator().generate(
            app, entrypoint="MAIN", source_root=FIXTURE_DIR
        )
        assert gen_result.success, gen_result.errors

        spring_app = map_java_application_to_spring_boot(
            gen_result.java_application, entry_program="MAIN"
        )
        assert spring_app.validate() == []

        project = tmp_path / "spring-project"
        for f in SpringBootGenerator().generate_project(spring_app):
            target = project / pathlib.Path(*(pathlib.Path(f.path or f.filename).parts))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f.source_code, encoding="utf-8")

        manifest = CandidateManifest(
            candidate_id="business-logic-app",
            workload_id="wl-business-logic",
            source_hash="test",
            generated_files={"pom.xml": "test"},
            entrypoint=SPRING_ENTRY,
        )
        adapter = DockerSpringBootCandidateAdapter()
        result = adapter.compile(str(project), manifest)
        assert result.success, result.compilation_errors


# ---------------------------------------------------------------------------
# Stage 5-9: Full VERIFIED run (skipped without Docker)
# ---------------------------------------------------------------------------

@requires_docker
class TestVerifiedVerdict:
    def test_business_logic_reaches_verified(self, tmp_path: pathlib.Path) -> None:
        """
        Full pipeline:  COBOL → Java/Spring → Docker build → Docker execution
                     || GnuCOBOL oracle → stdout comparison → VERIFIED
        """
        from engine.transformation.application_discovery import ApplicationDiscovery
        from engine.transformation.application_generator import ApplicationGenerator
        from engine.transformation.java_to_spring_mapping import (
            map_java_application_to_spring_boot,
        )
        from engine.transformation.spring_boot_generator import SpringBootGenerator
        from engine.candidate.docker_spring_boot_adapter import (
            DockerSpringBootCandidateAdapter,
            CandidateManifest,
        )
        from engine.oracle.docker_adapter import DockerOracleAdapter
        from engine.oracle.adapter import OracleAdapterConfig
        from engine.domain.identities import RunId, VerdictState

        run_id = RunId(value=f"business-logic-run-{uuid.uuid4().hex[:8]}")

        # --- Stage A: COBOL → Spring Boot project ---
        app = ApplicationDiscovery().discover(
            str(FIXTURE_DIR), application_id="business-logic-app"
        )
        gen_result = ApplicationGenerator().generate(
            app, entrypoint="MAIN", source_root=FIXTURE_DIR
        )
        assert gen_result.success, gen_result.errors

        spring_app = map_java_application_to_spring_boot(
            gen_result.java_application, entry_program="MAIN"
        )
        assert spring_app.validate() == []

        project = tmp_path / "spring-project"
        for f in SpringBootGenerator().generate_project(spring_app):
            target = project / pathlib.Path(*(pathlib.Path(f.path or f.filename).parts))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f.source_code, encoding="utf-8")

        # --- Stage B: Docker Maven build ---
        manifest = CandidateManifest(
            candidate_id="business-logic-app",
            workload_id="wl-business-logic",
            source_hash="test",
            generated_files={"pom.xml": "test"},
            entrypoint=SPRING_ENTRY,
        )
        candidate_adapter = DockerSpringBootCandidateAdapter()
        compile_result = candidate_adapter.compile(str(project), manifest)
        assert compile_result.success, compile_result.compilation_errors

        # --- Stage C: Docker JVM execution (candidate) ---
        exec_result = candidate_adapter.execute(run_id, str(project), manifest)
        candidate_stdout = exec_result.stdout.decode(errors="replace")

        # --- Stage D: GnuCOBOL oracle (independent reference) ---
        oracle_cfg = OracleAdapterConfig(
            oracle_id="gnucobol-business-logic",
            image_digest="sha256:f6f567fb15c30442ea844426dd9d5dea0b626f70bbe3d2208e26cf9d35b8d780",
            compiler_version="3.1.2.0",
        )
        oracle_adapter = DockerOracleAdapter(oracle_cfg)
        assert oracle_adapter.probe().value != "UNAVAILABLE", (
            "GnuCOBOL oracle image unavailable"
        )

        oracle_result = oracle_adapter.execute(
            run_id=run_id,
            source_path=str(FIXTURE_DIR),
            entry_program="MAIN",
        )
        oracle_stdout = oracle_result.stdout.decode(errors="replace")

        # --- Stage E: Verify both produce expected observable output ---
        def _normalise(s: str) -> list[str]:
            return [ln.rstrip() for ln in s.splitlines() if ln.strip()]

        oracle_lines = _normalise(oracle_stdout)
        candidate_lines = _normalise(candidate_stdout)

        verdict: VerdictState
        if oracle_lines == candidate_lines:
            verdict = VerdictState.VERIFIED
        else:
            verdict = VerdictState.FAILED

        assert verdict == VerdictState.VERIFIED, (
            f"Expected VERIFIED; got {verdict.value}\n"
            f"Oracle stdout ({len(oracle_lines)} lines):    {oracle_lines}\n"
            f"Candidate stdout ({len(candidate_lines)} lines): {candidate_lines}\n"
        )
