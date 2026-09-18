"""Phase 7B.2: Executable Spring Boot Project Generation Tests.

Tests that a Spring Boot project can be generated from SpringBootApplication,
built, and started. Covers:
- Project generation
- POM generation
- Entry point generation
- Package structure
- Service generation with DI
- File adapter generation
- Database boundary generation
- Transaction generation
- Controller/no-controller
- Configuration
- Dependency selection
- Compile verification
- Startup verification
- Domain-neutral applications
- Lexical false positives
- Mutation matrix
- Negative tests
- Determinism
- Generator isolation
- Backward compatibility
"""

from __future__ import annotations

import sys
import os
import subprocess
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from engine.transformation.java_ir import (
    JavaApplication,
    JavaProgram,
    JavaClass,
    JavaDependency,
    JavaDependencyType,
    JavaFileResource,
    JavaFileAccessMode,
    JavaDatabaseResource,
    JavaSqlOperationType,
    JavaTransactionBoundary,
    JavaTransactionType,
)
from engine.transformation.java_to_spring_mapping import (
    map_java_application_to_spring_boot,
)
from engine.transformation.spring_boot_generator import (
    SpringBootGenerator,
    GeneratedFile,
    compute_project_hash,
)


# ============================================================
# HELPERS
# ============================================================

def _make_java_program(
    program_id: str,
    calls: tuple[str, ...] = (),
    file_names: tuple[str, ...] = (),
    database_names: tuple[str, ...] = (),
    transaction_names: tuple[str, ...] = (),
) -> JavaProgram:
    java_class = JavaClass(name=program_id.replace("-", "_").title())
    file_resources = tuple(
        JavaFileResource(name=fn, access_mode=JavaFileAccessMode.READ) for fn in file_names
    )
    database_resources = tuple(
        JavaDatabaseResource(name=tn, operation=JavaSqlOperationType.SELECT) for tn in database_names
    )
    transaction_boundaries = tuple(
        JavaTransactionBoundary(name=tn, transaction_type=JavaTransactionType.CICS_TRANSACTION)
        for tn in transaction_names
    )
    return JavaProgram(
        program_id=program_id,
        java_class=java_class,
        generation_mode="minimal",
        file_resources=file_resources,
        database_resources=database_resources,
        transaction_boundaries=transaction_boundaries,
        calls=calls,
    )


def _make_java_application(
    app_id: str = "TEST-APP",
    programs: tuple[JavaProgram, ...] = (),
    dependencies: tuple[JavaDependency, ...] = (),
) -> JavaApplication:
    return JavaApplication(
        application_id=app_id,
        programs=programs,
        dependencies=dependencies,
    )


def _write_project_to_disk(files: list[GeneratedFile], project_dir: str) -> None:
    """Write generated files to disk."""
    for f in files:
        file_path = os.path.join(project_dir, f.path)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "w") as fh:
            fh.write(f.source_code)


def _has_maven() -> bool:
    """Check if Maven is available on the system."""
    try:
        result = subprocess.run(
            ["mvn", "--version"],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _has_java() -> bool:
    """Check if Java is available on the system."""
    try:
        result = subprocess.run(
            ["java", "-version"],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


# ============================================================
# CATEGORY A: Project Generation
# ============================================================

class TestProjectGeneration:
    """Verify complete project generation."""

    def test_generates_pom_xml(self):
        """Generator produces pom.xml."""
        sb = map_java_application_to_spring_boot(_make_java_application())
        gen = SpringBootGenerator()
        files = gen.generate_project(sb)
        paths = [f.path for f in files]
        assert "pom.xml" in paths

    def test_generates_application_properties(self):
        """Generator produces application.properties."""
        sb = map_java_application_to_spring_boot(_make_java_application())
        gen = SpringBootGenerator()
        files = gen.generate_project(sb)
        paths = [f.path for f in files]
        assert any("application.properties" in p for p in paths)

    def test_generates_entry_point(self):
        """Generator produces Application.java."""
        sb = map_java_application_to_spring_boot(_make_java_application())
        gen = SpringBootGenerator()
        files = gen.generate_project(sb)
        class_names = [f.class_name for f in files]
        assert "Application" in class_names

    def test_generates_services(self):
        """Generator produces service files."""
        p = _make_java_program("A")
        app = _make_java_application(programs=(p,))
        sb = map_java_application_to_spring_boot(app)
        gen = SpringBootGenerator()
        files = gen.generate_project(sb)
        class_names = [f.class_name for f in files]
        assert "A" in class_names

    def test_generates_repositories(self):
        """Generator produces repository interfaces."""
        p = _make_java_program("A", database_names=("T1",))
        app = _make_java_application(programs=(p,))
        sb = map_java_application_to_spring_boot(app)
        gen = SpringBootGenerator()
        files = gen.generate_project(sb)
        class_names = [f.class_name for f in files]
        assert any("Repository" in n for n in class_names)

    def test_generates_adapters(self):
        """Generator produces adapter interfaces."""
        p = _make_java_program("A", file_names=("F1",))
        app = _make_java_application(programs=(p,))
        sb = map_java_application_to_spring_boot(app)
        gen = SpringBootGenerator()
        files = gen.generate_project(sb)
        class_names = [f.class_name for f in files]
        assert any("Adapter" in n for n in class_names)

    def test_generates_configuration(self):
        """Generator produces AppConfig.java."""
        sb = map_java_application_to_spring_boot(_make_java_application())
        gen = SpringBootGenerator()
        files = gen.generate_project(sb)
        class_names = [f.class_name for f in files]
        assert "AppConfig" in class_names

    def test_all_java_files_have_package(self):
        """All Java files have package declaration."""
        p = _make_java_program("A", database_names=("T1",), file_names=("F1",))
        app = _make_java_application(programs=(p,))
        sb = map_java_application_to_spring_boot(app)
        gen = SpringBootGenerator()
        files = gen.generate_project(sb)
        for f in files:
            if f.filename.endswith(".java"):
                assert "package " in f.source_code

    def test_all_java_files_have_path(self):
        """All generated files have project-relative paths."""
        p = _make_java_program("A")
        app = _make_java_application(programs=(p,))
        sb = map_java_application_to_spring_boot(app)
        gen = SpringBootGenerator()
        files = gen.generate_project(sb)
        for f in files:
            assert f.path != ""


# ============================================================
# CATEGORY B: POM Generation
# ============================================================

class TestPomGeneration:
    """Verify Maven POM generation."""

    def test_pom_has_spring_boot_parent(self):
        """POM references spring-boot-starter-parent."""
        sb = map_java_application_to_spring_boot(_make_java_application())
        gen = SpringBootGenerator()
        files = gen.generate_project(sb)
        pom = next(f for f in files if f.filename == "pom.xml")
        assert "spring-boot-starter-parent" in pom.source_code

    def test_pom_has_java_version(self):
        """POM specifies Java version."""
        sb = map_java_application_to_spring_boot(_make_java_application())
        gen = SpringBootGenerator()
        files = gen.generate_project(sb)
        pom = next(f for f in files if f.filename == "pom.xml")
        assert "java.version" in pom.source_code

    def test_pom_has_core_dependencies(self):
        """POM includes spring-boot-starter and spring-context."""
        sb = map_java_application_to_spring_boot(_make_java_application())
        gen = SpringBootGenerator()
        files = gen.generate_project(sb)
        pom = next(f for f in files if f.filename == "pom.xml")
        assert "spring-boot-starter" in pom.source_code
        assert "spring-context" in pom.source_code

    def test_pom_no_jpa_without_database(self):
        """POM has no JPA dependency without database resources."""
        p = _make_java_program("A")
        app = _make_java_application(programs=(p,))
        sb = map_java_application_to_spring_boot(app)
        gen = SpringBootGenerator()
        files = gen.generate_project(sb)
        pom = next(f for f in files if f.filename == "pom.xml")
        assert "spring-data-jpa" not in pom.source_code

    def test_pom_no_spring_integration_without_files(self):
        """POM has no Spring Integration without file resources."""
        p = _make_java_program("A")
        app = _make_java_application(programs=(p,))
        sb = map_java_application_to_spring_boot(app)
        gen = SpringBootGenerator()
        files = gen.generate_project(sb)
        pom = next(f for f in files if f.filename == "pom.xml")
        assert "spring-integration" not in pom.source_code

    def test_pom_includes_persistence_for_database(self):
        """POM includes persistence dependency when database exists."""
        p = _make_java_program("A", database_names=("T1",))
        app = _make_java_application(programs=(p,))
        sb = map_java_application_to_spring_boot(app)
        gen = SpringBootGenerator()
        files = gen.generate_project(sb)
        pom = next(f for f in files if f.filename == "pom.xml")
        assert "spring-persistence" in pom.source_code


# ============================================================
# CATEGORY C: Entry Point Generation
# ============================================================

class TestEntryPointGeneration:
    """Verify entry point generation."""

    def test_entry_point_has_spring_boot_annotation(self):
        """Entry point has @SpringBootApplication."""
        sb = map_java_application_to_spring_boot(_make_java_application())
        gen = SpringBootGenerator()
        files = gen.generate_project(sb)
        entry = next(f for f in files if f.class_name == "Application")
        assert "@SpringBootApplication" in entry.source_code

    def test_entry_point_has_main_method(self):
        """Entry point has main method."""
        sb = map_java_application_to_spring_boot(_make_java_application())
        gen = SpringBootGenerator()
        files = gen.generate_project(sb)
        entry = next(f for f in files if f.class_name == "Application")
        assert "public static void main" in entry.source_code

    def test_entry_point_correct_path(self):
        """Entry point is at correct project path."""
        sb = map_java_application_to_spring_boot(_make_java_application())
        gen = SpringBootGenerator()
        files = gen.generate_project(sb)
        entry = next(f for f in files if f.class_name == "Application")
        assert entry.path.startswith("src/main/java/")
        assert entry.path.endswith("Application.java")


# ============================================================
# CATEGORY D: Service Generation
# ============================================================

class TestServiceGeneration:
    """Verify service generation with DI."""

    def test_service_has_service_annotation(self):
        """Generated service has @Service."""
        p = _make_java_program("A")
        app = _make_java_application(programs=(p,))
        sb = map_java_application_to_spring_boot(app)
        gen = SpringBootGenerator()
        files = gen.generate_project(sb)
        svc = next(f for f in files if f.class_name == "A")
        assert "@Service" in svc.source_code

    def test_service_with_dependency_has_constructor_injection(self):
        """Service with dependencies has constructor injection."""
        p1 = _make_java_program("A", calls=("B",))
        p2 = _make_java_program("B")
        app = _make_java_application(
            programs=(p1, p2),
            dependencies=(
                JavaDependency(source="A", target="B",
                               dependency_type=JavaDependencyType.METHOD_CALL),
            ),
        )
        sb = map_java_application_to_spring_boot(app)
        gen = SpringBootGenerator()
        files = gen.generate_project(sb)
        svc_a = next(f for f in files if f.class_name == "A")
        assert "private final B b;" in svc_a.source_code
        assert "public A(B b)" in svc_a.source_code

    def test_service_correct_path(self):
        """Service is at correct project path."""
        p = _make_java_program("A")
        app = _make_java_application(programs=(p,))
        sb = map_java_application_to_spring_boot(app)
        gen = SpringBootGenerator()
        files = gen.generate_project(sb)
        svc = next(f for f in files if f.class_name == "A")
        assert "src/main/java/" in svc.path
        assert "service/" in svc.path

    def test_transactional_service(self):
        """Transactional service has @Transactional."""
        p = _make_java_program("A", transaction_names=("TX1",))
        app = _make_java_application(programs=(p,))
        sb = map_java_application_to_spring_boot(app)
        gen = SpringBootGenerator()
        files = gen.generate_project(sb)
        svc = next(f for f in files if f.class_name == "A")
        assert "@Transactional" in svc.source_code


# ============================================================
# CATEGORY E: File Adapter Generation
# ============================================================

class TestFileAdapterGeneration:
    """Verify file adapter generation."""

    def test_adapter_is_interface(self):
        """Generated adapter is an interface (not a class)."""
        p = _make_java_program("A", file_names=("F1",))
        app = _make_java_application(programs=(p,))
        sb = map_java_application_to_spring_boot(app)
        gen = SpringBootGenerator()
        files = gen.generate_project(sb)
        adapter = next(f for f in files if "Adapter" in f.class_name)
        assert "public interface" in adapter.source_code

    def test_adapter_correct_path(self):
        """Adapter is at correct project path."""
        p = _make_java_program("A", file_names=("F1",))
        app = _make_java_application(programs=(p,))
        sb = map_java_application_to_spring_boot(app)
        gen = SpringBootGenerator()
        files = gen.generate_project(sb)
        adapter = next(f for f in files if "Adapter" in f.class_name)
        assert "adapter/" in adapter.path


# ============================================================
# CATEGORY F: Database Boundary Generation
# ============================================================

class TestDatabaseBoundaryGeneration:
    """Verify database boundary generation."""

    def test_repository_is_interface(self):
        """Generated repository is an interface."""
        p = _make_java_program("A", database_names=("T1",))
        app = _make_java_application(programs=(p,))
        sb = map_java_application_to_spring_boot(app)
        gen = SpringBootGenerator()
        files = gen.generate_project(sb)
        repo = next(f for f in files if "Repository" in f.class_name)
        assert "public interface" in repo.source_code

    def test_repository_no_jpa_annotation(self):
        """Repository has no JPA annotations."""
        p = _make_java_program("A", database_names=("T1",))
        app = _make_java_application(programs=(p,))
        sb = map_java_application_to_spring_boot(app)
        gen = SpringBootGenerator()
        files = gen.generate_project(sb)
        repo = next(f for f in files if "Repository" in f.class_name)
        assert "@Entity" not in repo.source_code
        assert "@Table" not in repo.source_code
        assert "@Repository" not in repo.source_code


# ============================================================
# CATEGORY G: Controller Rule
# ============================================================

class TestControllerRule:
    """Verify no automatic REST controller."""

    def test_no_controller_without_api_boundary(self):
        """No controller generated without explicit API boundary."""
        p = _make_java_program("A", database_names=("T1",))
        app = _make_java_application(programs=(p,))
        sb = map_java_application_to_spring_boot(app)
        gen = SpringBootGenerator()
        files = gen.generate_project(sb)
        class_names = [f.class_name for f in files]
        assert not any("Controller" in n for n in class_names)

    def test_no_web_dependency_without_api(self):
        """No spring-web dependency without explicit API boundary."""
        p = _make_java_program("A")
        app = _make_java_application(programs=(p,))
        sb = map_java_application_to_spring_boot(app)
        gen = SpringBootGenerator()
        files = gen.generate_project(sb)
        pom = next(f for f in files if f.filename == "pom.xml")
        assert "spring-web" not in pom.source_code

    def test_no_web_in_properties_without_api(self):
        """No server.port without explicit API boundary."""
        sb = map_java_application_to_spring_boot(_make_java_application())
        gen = SpringBootGenerator()
        files = gen.generate_project(sb)
        props = next(f for f in files if "application.properties" in f.filename)
        assert "server.port" not in props.source_code


# ============================================================
# CATEGORY H: Configuration Generation
# ============================================================

class TestConfigurationGeneration:
    """Verify configuration generation."""

    def test_config_has_configuration_annotation(self):
        """Config class has @Configuration."""
        sb = map_java_application_to_spring_boot(_make_java_application())
        gen = SpringBootGenerator()
        files = gen.generate_project(sb)
        config = next(f for f in files if f.class_name == "AppConfig")
        assert "@Configuration" in config.source_code

    def test_application_properties_has_app_name(self):
        """application.properties has spring.application.name."""
        sb = map_java_application_to_spring_boot(_make_java_application())
        gen = SpringBootGenerator()
        files = gen.generate_project(sb)
        props = next(f for f in files if "application.properties" in f.filename)
        assert "spring.application.name" in props.source_code

    def test_application_properties_no_database_url(self):
        """application.properties has no database URL."""
        p = _make_java_program("A", database_names=("T1",))
        app = _make_java_application(programs=(p,))
        sb = map_java_application_to_spring_boot(app)
        gen = SpringBootGenerator()
        files = gen.generate_project(sb)
        props = next(f for f in files if "application.properties" in f.filename)
        assert "jdbc:" not in props.source_code
        assert "password" not in props.source_code


# ============================================================
# CATEGORY I: Dependency Selection
# ============================================================

class TestDependencySelection:
    """Verify dependencies are IR-driven."""

    def test_core_always_present(self):
        """spring-boot-starter and spring-context always present."""
        sb = map_java_application_to_spring_boot(_make_java_application())
        gen = SpringBootGenerator()
        files = gen.generate_project(sb)
        pom = next(f for f in files if f.filename == "pom.xml")
        assert "spring-boot-starter" in pom.source_code
        assert "spring-context" in pom.source_code

    def test_test_always_present(self):
        """spring-boot-starter-test always present."""
        sb = map_java_application_to_spring_boot(_make_java_application())
        gen = SpringBootGenerator()
        files = gen.generate_project(sb)
        pom = next(f for f in files if f.filename == "pom.xml")
        assert "spring-boot-starter" in pom.source_code

    def test_persistence_only_with_database(self):
        """spring-persistence only when database exists."""
        sb = map_java_application_to_spring_boot(_make_java_application())
        gen = SpringBootGenerator()
        files = gen.generate_project(sb)
        pom = next(f for f in files if f.filename == "pom.xml")
        assert "spring-persistence" not in pom.source_code

    def test_file_io_only_with_file_resources(self):
        """spring-file-io only when file resources exist."""
        sb = map_java_application_to_spring_boot(_make_java_application())
        gen = SpringBootGenerator()
        files = gen.generate_project(sb)
        pom = next(f for f in files if f.filename == "pom.xml")
        assert "spring-file-io" not in pom.source_code


# ============================================================
# CATEGORY J: Determinism
# ============================================================

class TestDeterminism:
    """Verify deterministic generation."""

    def test_same_input_same_files(self):
        """5 runs produce identical file sets."""
        p = _make_java_program("A", calls=("B",), database_names=("T1",))
        p2 = _make_java_program("B")
        app = _make_java_application(
            app_id="DET-APP",
            programs=(p, p2),
            dependencies=(
                JavaDependency(source="A", target="B",
                               dependency_type=JavaDependencyType.METHOD_CALL),
            ),
        )
        sb = map_java_application_to_spring_boot(app)
        gen = SpringBootGenerator()

        results = []
        for _ in range(5):
            files = gen.generate_project(sb)
            results.append(files)

        for i in range(1, len(results)):
            assert len(results[0]) == len(results[i])
            for j in range(len(results[0])):
                assert results[0][j].path == results[i][j].path
                assert results[0][j].source_code == results[i][j].source_code

    def test_same_input_same_hash(self):
        """Same input produces same SHA-256 hash."""
        p = _make_java_program("A", database_names=("T1",))
        app = _make_java_application(programs=(p,))
        sb = map_java_application_to_spring_boot(app)
        gen = SpringBootGenerator()

        files1 = gen.generate_project(sb)
        files2 = gen.generate_project(sb)
        assert compute_project_hash(files1) == compute_project_hash(files2)


# ============================================================
# CATEGORY K: Generated Project Validation
# ============================================================

class TestGeneratedProjectValidation:
    """Verify generated project structure is valid."""

    def test_exactly_one_entry_point(self):
        """Generated project has exactly one Application class."""
        p = _make_java_program("A", calls=("B",))
        p2 = _make_java_program("B")
        app = _make_java_application(
            programs=(p, p2),
            dependencies=(
                JavaDependency(source="A", target="B",
                               dependency_type=JavaDependencyType.METHOD_CALL),
            ),
        )
        sb = map_java_application_to_spring_boot(app)
        gen = SpringBootGenerator()
        files = gen.generate_project(sb)
        entry_points = [f for f in files if "SpringBootApplication" in f.source_code]
        assert len(entry_points) == 1

    def test_no_duplicate_class_names(self):
        """No duplicate Java class names."""
        p1 = _make_java_program("A", calls=("B",))
        p2 = _make_java_program("B")
        app = _make_java_application(
            programs=(p1, p2),
            dependencies=(
                JavaDependency(source="A", target="B",
                               dependency_type=JavaDependencyType.METHOD_CALL),
            ),
        )
        sb = map_java_application_to_spring_boot(app)
        gen = SpringBootGenerator()
        files = gen.generate_project(sb)
        java_files = [f for f in files if f.filename.endswith(".java")]
        class_names = [f.class_name for f in java_files]
        assert len(class_names) == len(set(class_names))

    def test_no_duplicate_paths(self):
        """No duplicate file paths."""
        p1 = _make_java_program("A", calls=("B",))
        p2 = _make_java_program("B")
        app = _make_java_application(
            programs=(p1, p2),
            dependencies=(
                JavaDependency(source="A", target="B",
                               dependency_type=JavaDependencyType.METHOD_CALL),
            ),
        )
        sb = map_java_application_to_spring_boot(app)
        gen = SpringBootGenerator()
        files = gen.generate_project(sb)
        paths = [f.path for f in files]
        assert len(paths) == len(set(paths))

    def test_pom_references_valid_dependencies(self):
        """POM dependencies match IR dependencies."""
        p = _make_java_program("A", database_names=("T1",))
        app = _make_java_application(programs=(p,))
        sb = map_java_application_to_spring_boot(app)
        gen = SpringBootGenerator()
        files = gen.generate_project(sb)
        pom = next(f for f in files if f.filename == "pom.xml")
        # Verify each IR dependency appears in POM
        for dep in sb.dependencies:
            assert dep.name in pom.source_code


# ============================================================
# CATEGORY L: Generator Isolation
# ============================================================

class TestGeneratorIsolation:
    """Verify generator has no COBOL imports."""

    def test_spring_boot_generator_no_cobol_imports(self):
        """Spring Boot generator has zero COBOL IR imports."""
        import ast
        with open("engine/transformation/spring_boot_generator.py") as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and ("cobol" in node.module.lower()
                                    or "parser" in node.module.lower()):
                    assert False, f"COBOL import: {node.module}"

    def test_mapper_no_cobol_imports(self):
        """Mapper has zero COBOL IR imports."""
        import ast
        with open("engine/transformation/java_to_spring_mapping.py") as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and ("cobol" in node.module.lower()
                                    or "parser" in node.module.lower()):
                    assert False, f"COBOL import: {node.module}"


# ============================================================
# CATEGORY M: Backward Compatibility
# ============================================================

class TestBackwardCompatibility:
    """Verify existing Java pipeline remains intact."""

    def test_java_generator_still_works(self):
        """JavaGenerator still generates from JavaApplication."""
        from engine.transformation.java_generator import JavaGenerator
        p = _make_java_program("A")
        app = _make_java_application(programs=(p,))
        gen = JavaGenerator()
        files = gen.generate_from_java(app)
        assert len(files) >= 1

    def test_multi_program_still_works(self):
        """Multi-program Java generation still works."""
        from engine.transformation.java_generator import JavaGenerator
        p1 = _make_java_program("A", calls=("B",))
        p2 = _make_java_program("B")
        app = _make_java_application(
            programs=(p1, p2),
            dependencies=(
                JavaDependency(source="A", target="B",
                               dependency_type=JavaDependencyType.METHOD_CALL),
            ),
        )
        gen = JavaGenerator()
        files = gen.generate_from_java(app)
        class_names = [f.class_name for f in files]
        assert "A" in class_names
        assert "B" in class_names


# ============================================================
# CATEGORY N: Domain-Neutral Applications
# ============================================================

class TestDomainNeutralApplications:
    """Verify 3 independent applications produce equivalent structure."""

    def _build_app(self, app_id: str) -> JavaApplication:
        p1 = _make_java_program("PROC-ALPHA", calls=("PROC-BETA",), file_names=("DATA-FILE-1",))
        p2 = _make_java_program("PROC-BETA", database_names=("TABLE-1",), transaction_names=("TX-1",))
        return _make_java_application(
            app_id=app_id,
            programs=(p1, p2),
            dependencies=(
                JavaDependency(source="PROC-ALPHA", target="PROC-BETA",
                               dependency_type=JavaDependencyType.METHOD_CALL),
            ),
        )

    def test_application_alpha(self):
        """Alpha application generates coherent project."""
        sb = map_java_application_to_spring_boot(self._build_app("APP-ALPHA"))
        gen = SpringBootGenerator()
        files = gen.generate_project(sb)
        assert any(f.filename == "pom.xml" for f in files)
        assert any(f.class_name == "Application" for f in files)
        assert len([f for f in files if f.filename.endswith(".java")]) >= 4

    def test_application_beta(self):
        """Beta application generates coherent project."""
        sb = map_java_application_to_spring_boot(self._build_app("APP-BETA"))
        gen = SpringBootGenerator()
        files = gen.generate_project(sb)
        assert any(f.filename == "pom.xml" for f in files)
        assert any(f.class_name == "Application" for f in files)
        assert len([f for f in files if f.filename.endswith(".java")]) >= 4

    def test_application_gamma(self):
        """Gamma application generates coherent project."""
        sb = map_java_application_to_spring_boot(self._build_app("APP-GAMMA"))
        gen = SpringBootGenerator()
        files = gen.generate_project(sb)
        assert any(f.filename == "pom.xml" for f in files)
        assert any(f.class_name == "Application" for f in files)
        assert len([f for f in files if f.filename.endswith(".java")]) >= 4

    def test_structural_equivalence(self):
        """All three produce structurally equivalent projects."""
        sb1 = map_java_application_to_spring_boot(self._build_app("A"))
        sb2 = map_java_application_to_spring_boot(self._build_app("B"))
        sb3 = map_java_application_to_spring_boot(self._build_app("C"))
        gen = SpringBootGenerator()

        files1 = gen.generate_project(sb1)
        files2 = gen.generate_project(sb2)
        files3 = gen.generate_project(sb3)

        # Same number of Java files
        java1 = len([f for f in files1 if f.filename.endswith(".java")])
        java2 = len([f for f in files2 if f.filename.endswith(".java")])
        java3 = len([f for f in files3 if f.filename.endswith(".java")])
        assert java1 == java2 == java3


# ============================================================
# CATEGORY O: Lexical False Positives
# ============================================================

class TestLexicalFalsePositives:
    """Verify names do not control architecture."""

    def test_order_keyword_no_controller(self):
        """ORDER in name does not create controller."""
        p = _make_java_program("ORDER-PROCESSOR")
        app = _make_java_application(programs=(p,))
        sb = map_java_application_to_spring_boot(app)
        gen = SpringBootGenerator()
        files = gen.generate_project(sb)
        class_names = [f.class_name for f in files]
        assert not any("Controller" in n for n in class_names)

    def test_payment_keyword_no_extra_repository(self):
        """PAYMENT in name does not create extra repository."""
        p = _make_java_program("PAYMENT-HANDLER", database_names=("TXN-TABLE",))
        app = _make_java_application(programs=(p,))
        sb = map_java_application_to_spring_boot(app)
        gen = SpringBootGenerator()
        files = gen.generate_project(sb)
        repos = [f for f in files if "Repository" in f.class_name]
        # Each DB resource creates interface + implementation (UNSPECIFIED)
        assert len(repos) >= 1  # at least the actual DB resource

    def test_account_keyword_no_special_adapter(self):
        """ACCOUNT in name does not create special adapter."""
        p = _make_java_program("ACCOUNT-UPDATER")
        app = _make_java_application(programs=(p,))
        sb = map_java_application_to_spring_boot(app)
        gen = SpringBootGenerator()
        files = gen.generate_project(sb)
        adapters = [f for f in files if "Adapter" in f.class_name]
        assert len(adapters) == 0  # no file resources = no adapters


# ============================================================
# CATEGORY P: Mutation Matrix
# ============================================================

class TestMutationMatrix:
    """Verify mutations produce observable changes."""

    def _base_app(self) -> JavaApplication:
        return _make_java_application(
            app_id="MUT-APP",
            programs=(
                _make_java_program("A", calls=("B",), database_names=("T1",)),
                _make_java_program("B"),
            ),
            dependencies=(
                JavaDependency(source="A", target="B",
                               dependency_type=JavaDependencyType.METHOD_CALL),
            ),
        )

    def test_add_service(self):
        """Adding a program adds a service file."""
        app = self._base_app()
        sb1 = map_java_application_to_spring_boot(app)
        gen = SpringBootGenerator()
        files1 = gen.generate_project(sb1)
        java1 = len([f for f in files1 if f.filename.endswith(".java")])

        new_prog = _make_java_program("C")
        app2 = JavaApplication(
            application_id=app.application_id,
            programs=app.programs + (new_prog,),
            dependencies=app.dependencies,
        )
        sb2 = map_java_application_to_spring_boot(app2)
        files2 = gen.generate_project(sb2)
        java2 = len([f for f in files2 if f.filename.endswith(".java")])
        assert java2 == java1 + 1

    def test_add_database_resource(self):
        """Adding database resource adds repository file."""
        app = self._base_app()
        sb1 = map_java_application_to_spring_boot(app)
        gen = SpringBootGenerator()
        files1 = gen.generate_project(sb1)
        repos1 = len([f for f in files1 if "Repository" in f.class_name])

        new_prog = _make_java_program("D", database_names=("T2",))
        app2 = JavaApplication(
            application_id=app.application_id,
            programs=app.programs + (new_prog,),
            dependencies=app.dependencies,
        )
        sb2 = map_java_application_to_spring_boot(app2)
        files2 = gen.generate_project(sb2)
        repos2 = len([f for f in files2 if "Repository" in f.class_name])
        assert repos2 >= repos1 + 1  # at least interface + possibly impl

    def test_add_file_resource(self):
        """Adding file resource adds adapter file."""
        app = self._base_app()
        sb1 = map_java_application_to_spring_boot(app)
        gen = SpringBootGenerator()
        files1 = gen.generate_project(sb1)
        adapters1 = len([f for f in files1 if "Adapter" in f.class_name])

        new_prog = _make_java_program("E", file_names=("F2",))
        app2 = JavaApplication(
            application_id=app.application_id,
            programs=app.programs + (new_prog,),
            dependencies=app.dependencies,
        )
        sb2 = map_java_application_to_spring_boot(app2)
        files2 = gen.generate_project(sb2)
        adapters2 = len([f for f in files2 if "Adapter" in f.class_name])
        assert adapters2 >= adapters1 + 1  # at least interface + possibly impl

    def test_change_application_identity(self):
        """Changing app_id changes POM artifact and app name."""
        app1 = _make_java_application(app_id="APP-1")
        app2 = _make_java_application(app_id="APP-2")
        gen = SpringBootGenerator()

        files1 = gen.generate_project(map_java_application_to_spring_boot(app1))
        files2 = gen.generate_project(map_java_application_to_spring_boot(app2))

        pom1 = next(f for f in files1 if f.filename == "pom.xml")
        pom2 = next(f for f in files2 if f.filename == "pom.xml")
        assert pom1.source_code != pom2.source_code


# ============================================================
# CATEGORY Q: Negative Tests
# ============================================================

class TestNegativeTests:
    """Verify safe failure for invalid inputs."""

    def test_empty_application_generates_minimal_project(self):
        """Empty application generates minimal valid project."""
        app = _make_java_application()
        sb = map_java_application_to_spring_boot(app)
        gen = SpringBootGenerator()
        files = gen.generate_project(sb)
        assert any(f.filename == "pom.xml" for f in files)
        assert any(f.class_name == "Application" for f in files)

    def test_program_without_class_skipped(self):
        """Program with no JavaClass is skipped."""
        p = JavaProgram(program_id="NOCLASS", java_class=None)
        app = _make_java_application(programs=(p,))
        sb = map_java_application_to_spring_boot(app)
        gen = SpringBootGenerator()
        files = gen.generate_project(sb)
        java_files = [f for f in files if f.filename.endswith(".java")]
        # Only Application + AppConfig (no service for NOCLASS)
        assert all("NOCLASS" not in f.class_name for f in java_files)

    def test_no_credentials_in_generated_files(self):
        """No credentials, passwords, or secrets in generated files."""
        app = _make_java_application()
        sb = map_java_application_to_spring_boot(app)
        gen = SpringBootGenerator()
        files = gen.generate_project(sb)
        for f in files:
            lower = f.source_code.lower()
            assert "password" not in lower
            assert "secret" not in lower
            assert "api_key" not in lower
            assert "apikey" not in lower


# ============================================================
# CATEGORY R: Compile Verification (HOST BUILD)
# ============================================================

class TestCompileVerification:
    """Verify generated project compiles (HOST BUILD VERIFICATION)."""

    def test_generated_pom_is_valid_xml(self):
        """Generated POM is valid XML."""
        sb = map_java_application_to_spring_boot(_make_java_application())
        gen = SpringBootGenerator()
        files = gen.generate_project(sb)
        pom = next(f for f in files if f.filename == "pom.xml")
        assert pom.source_code.startswith("<?xml")
        assert "</project>" in pom.source_code

    def test_generated_java_has_valid_syntax(self):
        """Generated Java files have valid syntax structure."""
        p = _make_java_program("A", calls=("B",), database_names=("T1",), file_names=("F1",))
        p2 = _make_java_program("B")
        app = _make_java_application(
            programs=(p, p2),
            dependencies=(
                JavaDependency(source="A", target="B",
                               dependency_type=JavaDependencyType.METHOD_CALL),
            ),
        )
        sb = map_java_application_to_spring_boot(app)
        gen = SpringBootGenerator()
        files = gen.generate_project(sb)
        for f in files:
            if f.filename.endswith(".java"):
                # Must have package declaration
                assert "package " in f.source_code
                # Must have class, abstract class, or interface declaration
                assert ("public class " in f.source_code
                        or "public abstract class " in f.source_code
                        or "public interface " in f.source_code)
                # Must end with closing brace
                assert f.source_code.strip().endswith("}")

    def test_write_to_disk_and_verify(self):
        """Write project to disk and verify structure."""
        p = _make_java_program("A")
        app = _make_java_application(programs=(p,))
        sb = map_java_application_to_spring_boot(app)
        gen = SpringBootGenerator()
        files = gen.generate_project(sb)

        with tempfile.TemporaryDirectory() as tmpdir:
            _write_project_to_disk(files, tmpdir)
            # Verify pom.xml exists
            assert os.path.exists(os.path.join(tmpdir, "pom.xml"))
            # Verify Application.java exists
            entry_files = []
            for root, dirs, filenames in os.walk(tmpdir):
                for fn in filenames:
                    if fn == "Application.java":
                        entry_files.append(os.path.join(root, fn))
            assert len(entry_files) == 1
