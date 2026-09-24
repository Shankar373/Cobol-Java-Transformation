"""JCL → Spring Boot generation tests.

Proves the full generation pipeline:
    JCL → JclDiscovery → modernize_jcl → SpringBatchApplication
    → jcl_to_spring_boot → SpringBootApplication
    → SpringBootGenerator → GeneratedFile list

Does NOT test Maven compilation or Docker execution (those are
runtime claims requiring separate verification).
"""

from __future__ import annotations

from pathlib import Path

from engine.transformation.jcl_consumer import (
    modernize_jcl_from_sources,
    modernize_jcl_workload,
)
from engine.transformation.jcl_spring_boot_adapter import jcl_to_spring_boot
from engine.transformation.spring_boot_generator import SpringBootGenerator

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "workload-jcl"


def load_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _generate_from_fixtures():
    """Helper: full pipeline from fixture directory."""
    result = modernize_jcl_workload(FIXTURES, application_id="gen-test")
    spring_app = jcl_to_spring_boot(result.profile.application, base_package="com.generated.jcl")
    gen = SpringBootGenerator()
    files = gen.generate_project(spring_app)
    return result, spring_app, files


# ---------------------------------------------------------------------------
# 1. Adapter produces valid SpringBootApplication
# ---------------------------------------------------------------------------

class TestAdapterOutput:
    """The adapter must produce a valid SpringBootApplication."""

    def test_services_match_jobs(self) -> None:
        result, spring_app, _ = _generate_from_fixtures()
        assert len(spring_app.services) == result.job_count

    def test_entry_point_set(self) -> None:
        _, spring_app, _ = _generate_from_fixtures()
        assert spring_app.entry_point is not None
        assert spring_app.entry_point.class_name == "JclBatchApplication"

    def test_dependencies_include_batch(self) -> None:
        _, spring_app, _ = _generate_from_fixtures()
        dep_names = {d.name for d in spring_app.dependencies}
        assert "spring-boot-starter" in dep_names
        assert "spring-boot-starter-batch" in dep_names

    def test_methods_per_job(self) -> None:
        result, spring_app, _ = _generate_from_fixtures()
        methods_per_service = {s.name: len(s.methods) for s in spring_app.services}
        for job in result.profile.application.jobs:
            assert job.job_bean in methods_per_service
            assert methods_per_service[job.job_bean] == len(job.steps)

    def test_method_names_are_camel_step(self) -> None:
        _, spring_app, _ = _generate_from_fixtures()
        simpleb = next(s for s in spring_app.services if s.name == "SimplebJob")
        method_names = [m.name for m in simpleb.methods]
        assert "step01" in method_names
        assert "step02" in method_names

    def test_application_id_propagated(self) -> None:
        _, spring_app, _ = _generate_from_fixtures()
        assert spring_app.application_id == "gen-test"


# ---------------------------------------------------------------------------
# 2. Generator produces valid files
# ---------------------------------------------------------------------------

class TestGeneratorOutput:
    """The generator must produce a complete set of files."""

    def test_pom_exists(self) -> None:
        _, _, files = _generate_from_fixtures()
        paths = {f.path for f in files}
        assert "pom.xml" in paths

    def test_entry_point_exists(self) -> None:
        _, _, files = _generate_from_fixtures()
        paths = {f.path for f in files}
        assert any("JclBatchApplication.java" in p for p in paths)

    def test_service_files_exist(self) -> None:
        _, _, files = _generate_from_fixtures()
        class_names = {f.class_name for f in files}
        assert "SimplebJob" in class_names
        assert "PayorderJob" in class_names
        assert "CondjobJob" in class_names
        assert "UnsuppJob" in class_names

    def test_application_properties_exists(self) -> None:
        _, _, files = _generate_from_fixtures()
        paths = {f.path for f in files}
        assert any("application.properties" in p for p in paths)

    def test_file_count(self) -> None:
        _, _, files = _generate_from_fixtures()
        # pom.xml + application.properties + entry point + 4 services = 7
        assert len(files) == 7

    def test_all_files_have_source(self) -> None:
        _, _, files = _generate_from_fixtures()
        for f in files:
            assert f.source_code, f"{f.path} has empty source"
            assert len(f.source_code) > 10, f"{f.path} too short"


# ---------------------------------------------------------------------------
# 3. Generated code structure
# ---------------------------------------------------------------------------

class TestGeneratedCodeStructure:
    """Verify the generated Java code has correct structure."""

    def test_pom_has_spring_boot_parent(self) -> None:
        _, _, files = _generate_from_fixtures()
        pom = next(f for f in files if f.path == "pom.xml")
        assert "spring-boot-starter-parent" in pom.source_code
        assert "3.2.5" in pom.source_code

    def test_pom_has_batch_dependency(self) -> None:
        _, _, files = _generate_from_fixtures()
        pom = next(f for f in files if f.path == "pom.xml")
        assert "spring-boot-starter-batch" in pom.source_code

    def test_entry_point_has_main(self) -> None:
        _, _, files = _generate_from_fixtures()
        ep = next(f for f in files if "JclBatchApplication" in f.path)
        assert "public static void main" in ep.source_code
        assert "SpringApplication.run" in ep.source_code

    def test_entry_point_has_runner(self) -> None:
        _, _, files = _generate_from_fixtures()
        ep = next(f for f in files if "JclBatchApplication" in f.path)
        assert "CommandLineRunner" in ep.source_code
        assert "@Bean" in ep.source_code

    def test_entry_point_injects_all_jobs(self) -> None:
        _, _, files = _generate_from_fixtures()
        ep = next(f for f in files if "JclBatchApplication" in f.path)
        assert "CondjobJob" in ep.source_code
        assert "PayorderJob" in ep.source_code
        assert "SimplebJob" in ep.source_code
        assert "UnsuppJob" in ep.source_code

    def test_service_has_println(self) -> None:
        _, _, files = _generate_from_fixtures()
        svc = next(f for f in files if f.class_name == "SimplebJob")
        assert "System.out.println" in svc.source_code

    def test_service_has_step_comments(self) -> None:
        _, _, files = _generate_from_fixtures()
        svc = next(f for f in files if f.class_name == "SimplebJob")
        assert "STEP01" in svc.source_code
        assert "SIMPLE-CALC" in svc.source_code

    def test_service_has_annotation(self) -> None:
        _, _, files = _generate_from_fixtures()
        svc = next(f for f in files if f.class_name == "SimplebJob")
        assert "@Service" in svc.source_code

    def test_properties_has_app_name(self) -> None:
        _, _, files = _generate_from_fixtures()
        props = next(f for f in files if "application.properties" in f.path)
        assert "spring.application.name" in props.source_code


# ---------------------------------------------------------------------------
# 4. In-memory generation
# ---------------------------------------------------------------------------

class TestInMemoryGeneration:
    """Generation works from in-memory JCL sources."""

    def test_single_job_generation(self) -> None:
        jcl = (
            "//MYJOB JOB CLASS=A\n"
            "//STEP01 EXEC PGM=HELLO\n"
            "//SYSOUT DD SYSOUT=*\n"
        )
        result = modernize_jcl_from_sources({"test.jcl": jcl}, application_id="mem-gen")
        spring_app = jcl_to_spring_boot(result.profile.application)
        gen = SpringBootGenerator()
        files = gen.generate_project(spring_app)
        assert len(files) >= 3  # pom + props + entry + service
        svc = next(f for f in files if f.class_name == "MyjobJob")
        assert "System.out.println" in svc.source_code
        assert "HELLO" in svc.source_code

    def test_empty_generation(self) -> None:
        result = modernize_jcl_from_sources({}, application_id="empty-gen")
        spring_app = jcl_to_spring_boot(result.profile.application)
        gen = SpringBootGenerator()
        files = gen.generate_project(spring_app)
        # Empty: pom + props + entry = 3 files
        assert len(files) == 3


# ---------------------------------------------------------------------------
# 5. Determinism
# ---------------------------------------------------------------------------

class TestGenerationDeterminism:
    """Generated output must be deterministic."""

    def test_two_runs_identical(self) -> None:
        _, _, files_a = _generate_from_fixtures()
        _, _, files_b = _generate_from_fixtures()
        assert len(files_a) == len(files_b)
        for fa, fb in zip(files_a, files_b):
            assert fa.path == fb.path
            assert fa.source_code == fb.source_code


# ---------------------------------------------------------------------------
# 6. Regression: existing generator behavior unchanged
# ---------------------------------------------------------------------------

class TestGeneratorRegression:
    """The existing SpringBootGenerator is not broken by JCL usage."""

    def test_generator_still_works_for_cobol_shaped_input(self) -> None:
        from engine.transformation.java_ir import JavaBasicType, JavaType
        from engine.transformation.spring_boot_ir import (
            SpringBootApplication,
            SpringBootEntryPoint,
            SpringBootService,
            SpringBootServiceMethod,
        )

        app = SpringBootApplication(
            application_id="regression-test",
            base_package="com.test",
            services=(
                SpringBootService(
                    name="TestService",
                    package="com.test",
                    methods=(
                        SpringBootServiceMethod(
                            name="execute",
                            return_type=JavaType(basic_type=JavaBasicType.VOID),
                        ),
                    ),
                ),
            ),
            entry_point=SpringBootEntryPoint(
                class_name="Application",
                package="com.test",
                application_name="regression-test",
            ),
        )
        gen = SpringBootGenerator()
        files = gen.generate_project(app)
        assert len(files) >= 3
        ep = next(f for f in files if "Application" in f.path)
        assert "public static void main" in ep.source_code
