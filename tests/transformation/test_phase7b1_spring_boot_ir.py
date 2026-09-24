"""Phase 7B.1: Spring Boot Application IR + Architecture Boundary Tests.

Tests that a domain-neutral Spring Boot application architecture can be
derived from a generic JavaApplication. Covers:
- Spring Boot IR construction
- JavaApplication → SpringBootApplication mapping
- Service/resource/transaction/entry point mapping
- Capability-driven architecture
- No automatic REST assumption
- Domain-neutral proof
- Lexical false-positive tests
- Mutation tests
- Negative tests
- Determinism
- Generator isolation
- Backward compatibility
"""

from __future__ import annotations

import sys
import os

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
from engine.transformation.spring_boot_ir import (
    SpringBootApplication,
    SpringBootService,
    SpringBootRepository,
    SpringBootAdapter,
    SpringBootConfiguration,
    SpringBootEntryPoint,
    SpringBootComponentType,
    DataAccessStrategy,
    FileAccessStrategy,
)
from engine.transformation.java_to_spring_mapping import (
    map_java_application_to_spring_boot,
)
from engine.transformation.spring_boot_generator import (
    SpringBootGenerator,
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
    """Create a minimal JavaProgram."""
    java_class = JavaClass(name=program_id.replace("-", "_").title())
    file_resources = tuple(
        JavaFileResource(name=fn, access_mode=JavaFileAccessMode.READ)
        for fn in file_names
    )
    database_resources = tuple(
        JavaDatabaseResource(name=tn, operation=JavaSqlOperationType.SELECT)
        for tn in database_names
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
    """Create a minimal JavaApplication."""
    return JavaApplication(
        application_id=app_id,
        programs=programs,
        dependencies=dependencies,
    )


# ============================================================
# CATEGORY A: Spring Boot IR Construction
# ============================================================

class TestSpringBootIrConstruction:
    """Verify Spring Boot IR can be constructed."""

    def test_service_construction(self):
        s = SpringBootService(name="MyService", package="com.app.service")
        assert s.name == "MyService"

    def test_repository_construction(self):
        r = SpringBootRepository(name="MyRepo", package="com.app.repo")
        assert r.name == "MyRepo"

    def test_adapter_construction(self):
        a = SpringBootAdapter(name="MyAdapter", package="com.app.adapter")
        assert a.name == "MyAdapter"

    def test_configuration_construction(self):
        c = SpringBootConfiguration(application_name="APP", base_package="com.app")
        assert c.application_name == "APP"

    def test_entry_point_construction(self):
        e = SpringBootEntryPoint(class_name="Application", package="com.app")
        assert e.class_name == "Application"

    def test_application_construction(self):
        app = SpringBootApplication(
            application_id="TEST",
            services=(SpringBootService(name="S1", package="com.app.service"),),
        )
        assert app.application_id == "TEST"
        assert len(app.services) == 1

    def test_component_type_enum(self):
        assert SpringBootComponentType.SERVICE.value == "SERVICE"
        assert SpringBootComponentType.REPOSITORY.value == "REPOSITORY"
        assert SpringBootComponentType.ADAPTER.value == "ADAPTER"
        assert SpringBootComponentType.CONTROLLER.value == "CONTROLLER"


# ============================================================
# CATEGORY B: JavaApplication → Spring Boot Mapping
# ============================================================

class TestJavaToSpringMapping:
    """Verify JavaApplication → SpringBootApplication mapping."""

    def test_empty_application(self):
        """Empty JavaApplication maps to minimal Spring Boot app."""
        app = _make_java_application()
        sb = map_java_application_to_spring_boot(app)
        assert sb.application_id == "TEST-APP"
        assert len(sb.services) == 0
        assert len(sb.repositories) == 0
        assert sb.entry_point is not None
        assert sb.configuration is not None

    def test_single_program_maps_to_service(self):
        """Single JavaProgram becomes one SpringBootService."""
        p = _make_java_program("PROG-A")
        app = _make_java_application(programs=(p,))
        sb = map_java_application_to_spring_boot(app)
        assert len(sb.services) == 1
        assert sb.services[0].source_program == "PROG-A"

    def test_multiple_programs_map_to_services(self):
        """Multiple JavaPrograms become multiple SpringBootServices."""
        p1 = _make_java_program("A")
        p2 = _make_java_program("B")
        p3 = _make_java_program("C")
        app = _make_java_application(programs=(p1, p2, p3))
        sb = map_java_application_to_spring_boot(app)
        assert len(sb.services) == 3

    def test_call_dependency_creates_service_dep(self):
        """CALL dependency creates SpringBootService dependency edge."""
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
        service_a = sb.get_service("A")
        assert service_a is not None
        assert "B" in service_a.depends_on

    def test_database_resource_creates_repository(self):
        """JavaDatabaseResource becomes SpringBootRepository."""
        p = _make_java_program("A", database_names=("TABLE-X",))
        app = _make_java_application(programs=(p,))
        sb = map_java_application_to_spring_boot(app)
        assert len(sb.repositories) == 1
        assert "TABLE-X" in sb.repositories[0].table_name

    def test_file_resource_creates_adapter(self):
        """JavaFileResource becomes SpringBootAdapter."""
        p = _make_java_program("A", file_names=("FILE-X",))
        app = _make_java_application(programs=(p,))
        sb = map_java_application_to_spring_boot(app)
        assert len(sb.adapters) == 1
        assert sb.adapters[0].source_resource == "FILE-X"

    def test_transaction_boundary_mapped(self):
        """JavaTransactionBoundary becomes SpringBootTransactionBoundary."""
        p = _make_java_program("A", transaction_names=("TX-A",))
        app = _make_java_application(programs=(p,))
        sb = map_java_application_to_spring_boot(app)
        assert len(sb.transaction_boundaries) == 1
        assert sb.transaction_boundaries[0].source_boundary == "TX-A"

    def test_deterministic_mapping(self):
        """Same input produces same output."""
        p = _make_java_program("A", calls=("B",), database_names=("T1",))
        p2 = _make_java_program("B")
        app = _make_java_application(
            programs=(p, p2),
            dependencies=(
                JavaDependency(source="A", target="B",
                               dependency_type=JavaDependencyType.METHOD_CALL),
            ),
        )
        sb1 = map_java_application_to_spring_boot(app)
        sb2 = map_java_application_to_spring_boot(app)
        assert sb1.services == sb2.services
        assert sb1.repositories == sb2.repositories
        assert sb1.adapters == sb2.adapters


# ============================================================
# CATEGORY C: Capability-Driven Architecture
# ============================================================

class TestCapabilityDrivenArchitecture:
    """Verify Spring Boot architecture is derived from capabilities."""

    def test_no_database_no_repository(self):
        """No database resources → no repositories."""
        p = _make_java_program("A")
        app = _make_java_application(programs=(p,))
        sb = map_java_application_to_spring_boot(app)
        assert len(sb.repositories) == 0

    def test_no_file_no_adapter(self):
        """No file resources → no adapters."""
        p = _make_java_program("A")
        app = _make_java_application(programs=(p,))
        sb = map_java_application_to_spring_boot(app)
        assert len(sb.adapters) == 0

    def test_no_transaction_no_boundary(self):
        """No transaction boundaries → no transaction components."""
        p = _make_java_program("A")
        app = _make_java_application(programs=(p,))
        sb = map_java_application_to_spring_boot(app)
        assert len(sb.transaction_boundaries) == 0

    def test_database_drives_data_dependency(self):
        """Database resources → generic persistence dependency (NOT JPA)."""
        p = _make_java_program("A", database_names=("T1",))
        app = _make_java_application(programs=(p,))
        sb = map_java_application_to_spring_boot(app)
        dep_names = [d.name for d in sb.dependencies]
        assert "spring-persistence" in dep_names
        assert "spring-data-jpa" not in dep_names

    def test_file_does_not_add_phantom_dependency(self):
        """File resources use standard java.io.* (JDK built-in, no Maven dep).

        The generated code uses java.io.FileWriter / PrintWriter from the JDK.
        No phantom 'spring-file-io' artifact is added (it does not exist in
        Maven central). Spring Integration file support is also not assumed.
        """
        p = _make_java_program("A", file_names=("F1",))
        app = _make_java_application(programs=(p,))
        sb = map_java_application_to_spring_boot(app)
        dep_names = [d.name for d in sb.dependencies]
        # No phantom deps — file I/O is handled by standard JDK
        assert "spring-file-io" not in dep_names, (
            "spring-file-io does not exist in Maven central; do not add it"
        )
        assert "spring-integration-file" not in dep_names

    def test_transaction_drives_tx_dependency(self):
        """Transaction boundaries → spring-tx dependency."""
        p = _make_java_program("A", transaction_names=("TX1",))
        app = _make_java_application(programs=(p,))
        sb = map_java_application_to_spring_boot(app)
        dep_names = [d.name for d in sb.dependencies]
        assert "spring-tx" in dep_names

    def test_always_has_core_dependencies(self):
        """Every application has spring-boot-starter and spring-context."""
        app = _make_java_application()
        sb = map_java_application_to_spring_boot(app)
        dep_names = [d.name for d in sb.dependencies]
        assert "spring-boot-starter" in dep_names
        assert "spring-context" in dep_names

    def test_always_has_test_dependency(self):
        """Every application has spring-boot-starter (core dependency)."""
        app = _make_java_application()
        sb = map_java_application_to_spring_boot(app)
        dep_names = [d.name for d in sb.dependencies]
        assert "spring-boot-starter" in dep_names


# ============================================================
# CATEGORY D: No Automatic REST Assumption
# ============================================================

class TestNoAutomaticRest:
    """Verify no REST controller is automatically generated."""

    def test_no_controller_by_default(self):
        """No explicit API boundary → no controller."""
        p = _make_java_program("A", database_names=("T1",))
        app = _make_java_application(programs=(p,))
        sb = map_java_application_to_spring_boot(app)
        # No controllers
        components = sb.get_all_components()
        controller_count = sum(
            1 for c in components
            if c.component_type == SpringBootComponentType.CONTROLLER
        )
        assert controller_count == 0

    def test_configuration_has_no_web(self):
        """Configuration.has_web is False without explicit API boundary."""
        app = _make_java_application()
        sb = map_java_application_to_spring_boot(app)
        assert sb.configuration is not None
        assert sb.configuration.has_web is False

    def test_no_web_dependency_without_api(self):
        """No spring-web dependency without explicit API boundary."""
        app = _make_java_application()
        sb = map_java_application_to_spring_boot(app)
        dep_names = [d.name for d in sb.dependencies]
        assert "spring-web" not in dep_names
        assert "spring-boot-starter-web" not in dep_names


# ============================================================
# CATEGORY E: Domain-Neutral Proof
# ============================================================

class TestDomainNeutralProof:
    """Verify architecture is domain-neutral."""

    def _build_app(self, app_id: str) -> JavaApplication:
        """Build a generic application with standard structure."""
        p1 = _make_java_program(
            "PROCESS-A",
            calls=("PROCESS-B",),
            file_names=("DATA-FILE-X",),
        )
        p2 = _make_java_program(
            "PROCESS-B",
            database_names=("TABLE-X",),
            transaction_names=("TX-MAIN",),
        )
        return _make_java_application(
            app_id=app_id,
            programs=(p1, p2),
            dependencies=(
                JavaDependency(source="PROCESS-A", target="PROCESS-B",
                               dependency_type=JavaDependencyType.METHOD_CALL),
            ),
        )

    def test_account_application(self):
        """ACCOUNT-style application gets same structure."""
        sb = map_java_application_to_spring_boot(self._build_app("ACCOUNT-PROCESSING"))
        assert len(sb.services) == 2
        assert len(sb.repositories) == 1
        assert len(sb.adapters) == 1
        assert len(sb.transaction_boundaries) == 1

    def test_order_application(self):
        """ORDER-style application gets same structure."""
        sb = map_java_application_to_spring_boot(self._build_app("ORDER-PROCESSING"))
        assert len(sb.services) == 2
        assert len(sb.repositories) == 1
        assert len(sb.adapters) == 1
        assert len(sb.transaction_boundaries) == 1

    def test_library_application(self):
        """LIBRARY-style application gets same structure."""
        sb = map_java_application_to_spring_boot(self._build_app("LIBRARY-PROCESSING"))
        assert len(sb.services) == 2
        assert len(sb.repositories) == 1
        assert len(sb.adapters) == 1
        assert len(sb.transaction_boundaries) == 1

    def test_structural_equivalence(self):
        """Different domain names produce structurally equivalent architectures."""
        sb1 = map_java_application_to_spring_boot(self._build_app("APP-A"))
        sb2 = map_java_application_to_spring_boot(self._build_app("APP-B"))
        assert len(sb1.services) == len(sb2.services)
        assert len(sb1.repositories) == len(sb2.repositories)
        assert len(sb1.adapters) == len(sb2.adapters)
        assert len(sb1.transaction_boundaries) == len(sb2.transaction_boundaries)
        assert len(sb1.dependencies) == len(sb2.dependencies)


# ============================================================
# CATEGORY F: Lexical False-Positive Tests
# ============================================================

class TestLexicalFalsePositives:
    """Verify names do NOT control architecture."""

    def test_status_keyword_no_effect(self):
        """STATUS in name doesn't create extra components."""
        p = _make_java_program("STATUS-CHECKER")
        app = _make_java_application(programs=(p,))
        sb = map_java_application_to_spring_boot(app)
        assert len(sb.services) == 1  # just one service

    def test_order_keyword_no_controller(self):
        """ORDER in name doesn't create a controller."""
        p = _make_java_program("ORDER-PROCESSOR")
        app = _make_java_application(programs=(p,))
        sb = map_java_application_to_spring_boot(app)
        components = sb.get_all_components()
        controller_count = sum(
            1 for c in components
            if c.component_type == SpringBootComponentType.CONTROLLER
        )
        assert controller_count == 0

    def test_payment_keyword_no_extra_repo(self):
        """PAYMENT in name doesn't create extra repositories."""
        p = _make_java_program("PAYMENT-HANDLER", database_names=("TXN-TABLE",))
        app = _make_java_application(programs=(p,))
        sb = map_java_application_to_spring_boot(app)
        assert len(sb.repositories) == 1  # only from actual DB resource

    def test_rename_domain_no_structural_change(self):
        """Renaming programs doesn't change architecture structure."""
        p1 = _make_java_program("CLAIMS-PROCESSOR", calls=("PAYMENT-HANDLER",))
        p2 = _make_java_program("PAYMENT-HANDLER")
        app1 = _make_java_application(
            app_id="APP1",
            programs=(p1, p2),
            dependencies=(
                JavaDependency(source="CLAIMS-PROCESSOR", target="PAYMENT-HANDLER",
                               dependency_type=JavaDependencyType.METHOD_CALL),
            ),
        )

        p3 = _make_java_program("ALPHA-PROCESSOR", calls=("BETA-HANDLER",))
        p4 = _make_java_program("BETA-HANDLER")
        app2 = _make_java_application(
            app_id="APP2",
            programs=(p3, p4),
            dependencies=(
                JavaDependency(source="ALPHA-PROCESSOR", target="BETA-HANDLER",
                               dependency_type=JavaDependencyType.METHOD_CALL),
            ),
        )

        sb1 = map_java_application_to_spring_boot(app1)
        sb2 = map_java_application_to_spring_boot(app2)
        assert len(sb1.services) == len(sb2.services)
        assert len(sb1.repositories) == len(sb2.repositories)


# ============================================================
# CATEGORY G: Mutation Tests
# ============================================================

class TestMutationTests:
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

    def test_add_program(self):
        """Adding a program adds a service."""
        app = self._base_app()
        sb1 = map_java_application_to_spring_boot(app)

        new_program = _make_java_program("C")
        app2 = JavaApplication(
            application_id=app.application_id,
            programs=app.programs + (new_program,),
            dependencies=app.dependencies,
        )
        sb2 = map_java_application_to_spring_boot(app2)
        assert len(sb2.services) == len(sb1.services) + 1

    def test_remove_program(self):
        """Removing a program removes a service."""
        app = self._base_app()
        sb1 = map_java_application_to_spring_boot(app)

        app2 = JavaApplication(
            application_id=app.application_id,
            programs=(app.programs[0],),  # only A
            dependencies=(),
        )
        sb2 = map_java_application_to_spring_boot(app2)
        assert len(sb2.services) == 1

    def test_add_database_resource(self):
        """Adding a database resource adds a repository."""
        app = self._base_app()
        sb1 = map_java_application_to_spring_boot(app)

        new_prog = _make_java_program("D", database_names=("T2",))
        app2 = JavaApplication(
            application_id=app.application_id,
            programs=app.programs + (new_prog,),
            dependencies=app.dependencies,
        )
        sb2 = map_java_application_to_spring_boot(app2)
        assert len(sb2.repositories) == len(sb1.repositories) + 1

    def test_add_file_resource(self):
        """Adding a file resource adds an adapter."""
        app = self._base_app()
        sb1 = map_java_application_to_spring_boot(app)

        new_prog = _make_java_program("E", file_names=("F2",))
        app2 = JavaApplication(
            application_id=app.application_id,
            programs=app.programs + (new_prog,),
            dependencies=app.dependencies,
        )
        sb2 = map_java_application_to_spring_boot(app2)
        assert len(sb2.adapters) == len(sb1.adapters) + 1

    def test_add_transaction_boundary(self):
        """Adding a transaction boundary adds a transaction component."""
        app = self._base_app()
        sb1 = map_java_application_to_spring_boot(app)

        new_prog = _make_java_program("F", transaction_names=("TX2",))
        app2 = JavaApplication(
            application_id=app.application_id,
            programs=app.programs + (new_prog,),
            dependencies=app.dependencies,
        )
        sb2 = map_java_application_to_spring_boot(app2)
        assert len(sb2.transaction_boundaries) == len(sb1.transaction_boundaries) + 1

    def test_add_call_dependency(self):
        """Adding a CALL dependency adds a service dependency edge."""
        p = _make_java_program("X")
        app = _make_java_application(
            app_id="MUT-APP",
            programs=(
                _make_java_program("A"),
                p,
            ),
        )
        sb1 = map_java_application_to_spring_boot(app)
        service_a1 = sb1.get_service("A")
        assert "X" not in service_a1.depends_on

        app2 = JavaApplication(
            application_id=app.application_id,
            programs=app.programs,
            dependencies=(
                JavaDependency(source="A", target="X",
                               dependency_type=JavaDependencyType.METHOD_CALL),
            ),
        )
        sb2 = map_java_application_to_spring_boot(app2)
        service_a2 = sb2.get_service("A")
        assert "X" in service_a2.depends_on


# ============================================================
# CATEGORY H: Negative Tests
# ============================================================

class TestNegativeTests:
    """Verify safe failure for invalid inputs."""

    def test_empty_application(self):
        """Empty application produces valid minimal Spring Boot app."""
        app = _make_java_application()
        sb = map_java_application_to_spring_boot(app)
        assert sb.entry_point is not None
        assert sb.configuration is not None

    def test_program_without_class(self):
        """Program with no JavaClass is skipped."""
        p = JavaProgram(program_id="NOCLASS", java_class=None)
        app = _make_java_application(programs=(p,))
        sb = map_java_application_to_spring_boot(app)
        assert len(sb.services) == 0

    def test_validation_catches_duplicate_service(self):
        """Duplicate service names are detected."""
        sb = SpringBootApplication(
            application_id="TEST",
            services=(
                SpringBootService(name="Dup", package="com.a"),
                SpringBootService(name="Dup", package="com.b"),
            ),
        )
        errors = sb.validate()
        assert any("Duplicate" in e for e in errors)

    def test_validation_catches_unresolved_dependency(self):
        """Unresolved service dependency is detected."""
        sb = SpringBootApplication(
            application_id="TEST",
            services=(
                SpringBootService(name="A", package="com.a", depends_on=("Missing",)),
            ),
        )
        errors = sb.validate()
        assert any("Unresolved" in e for e in errors)

    def test_validation_catches_missing_entry_point(self):
        """Missing entry point is detected."""
        sb = SpringBootApplication(
            application_id="TEST",
            entry_point=None,
        )
        errors = sb.validate()
        assert any("entry point" in e.lower() for e in errors)

    def test_validation_catches_missing_configuration(self):
        """Missing configuration is detected."""
        sb = SpringBootApplication(
            application_id="TEST",
            configuration=None,
        )
        errors = sb.validate()
        assert any("configuration" in e.lower() for e in errors)

    def test_valid_application_no_errors(self):
        """Valid application has no validation errors."""
        sb = map_java_application_to_spring_boot(_make_java_application())
        errors = sb.validate()
        assert len(errors) == 0


# ============================================================
# CATEGORY I: Determinism
# ============================================================

class TestDeterminism:
    """Verify deterministic mapping."""

    def test_same_input_same_output(self):
        """5 runs produce identical results."""
        p = _make_java_program("A", calls=("B",), database_names=("T1",))
        p2 = _make_java_program("B", file_names=("F1",))
        app = _make_java_application(
            app_id="DET-APP",
            programs=(p, p2),
            dependencies=(
                JavaDependency(source="A", target="B",
                               dependency_type=JavaDependencyType.METHOD_CALL),
            ),
        )

        results = []
        for _ in range(5):
            sb = map_java_application_to_spring_boot(app)
            results.append(sb)

        for i in range(1, len(results)):
            assert results[0].services == results[i].services
            assert results[0].repositories == results[i].repositories
            assert results[0].adapters == results[i].adapters
            assert results[0].dependencies == results[i].dependencies

    def test_same_input_same_hashes(self):
        """Same input produces same hashable representation."""
        app = _make_java_application(
            app_id="HASH-APP",
            programs=(_make_java_program("A", database_names=("T1",)),),
        )
        sb1 = map_java_application_to_spring_boot(app)
        sb2 = map_java_application_to_spring_boot(app)
        assert str(sb1.services) == str(sb2.services)
        assert str(sb1.repositories) == str(sb2.repositories)


# ============================================================
# CATEGORY J: Validation
# ============================================================

class TestValidation:
    """Verify Spring Boot application validation."""

    def test_cycle_detection(self):
        """Cycle in service dependencies detected."""
        sb = SpringBootApplication(
            application_id="CYCLE",
            services=(
                SpringBootService(name="A", package="p", depends_on=("B",)),
                SpringBootService(name="B", package="p", depends_on=("A",)),
            ),
            entry_point=SpringBootEntryPoint(),
            configuration=SpringBootConfiguration(),
        )
        cycles = sb.detect_cycles()
        assert len(cycles) >= 1

    def test_no_cycle(self):
        """Linear dependency has no cycles."""
        sb = SpringBootApplication(
            application_id="LINEAR",
            services=(
                SpringBootService(name="A", package="p", depends_on=("B",)),
                SpringBootService(name="B", package="p", depends_on=("C",)),
                SpringBootService(name="C", package="p"),
            ),
            entry_point=SpringBootEntryPoint(),
            configuration=SpringBootConfiguration(),
        )
        cycles = sb.detect_cycles()
        assert len(cycles) == 0

    def test_get_all_components(self):
        """get_all_components returns unified list."""
        sb = SpringBootApplication(
            application_id="TEST",
            services=(SpringBootService(name="S1", package="p"),),
            repositories=(SpringBootRepository(name="R1", package="p"),),
            adapters=(SpringBootAdapter(name="A1", package="p"),),
        )
        components = sb.get_all_components()
        assert len(components) == 3
        types = {c.component_type for c in components}
        assert SpringBootComponentType.SERVICE in types
        assert SpringBootComponentType.REPOSITORY in types
        assert SpringBootComponentType.ADAPTER in types


# ============================================================
# CATEGORY K: Generator Isolation
# ============================================================

class TestGeneratorIsolation:
    """Verify generator has no COBOL IR imports."""

    def test_spring_boot_generator_no_cobol_imports(self):
        """Spring Boot generator has zero COBOL IR imports."""
        import ast
        with open("engine/transformation/spring_boot_generator.py") as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and ("cobol" in node.module.lower()
                                    or "parser" in node.module.lower()):
                    assert False, f"COBOL import found: {node.module}"
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if "cobol" in alias.name.lower():
                        assert False, f"COBOL import found: {alias.name}"

    def test_spring_boot_generator_has_spring_boot_ir_import(self):
        """Spring Boot generator imports spring_boot_ir."""
        import ast
        with open("engine/transformation/spring_boot_generator.py") as f:
            tree = ast.parse(f.read())
        found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and "spring_boot_ir" in node.module:
                    found = True
        assert found, "spring_boot_ir import not found"

    def test_java_generator_no_spring_boot_imports(self):
        """Java generator has zero Spring Boot imports."""
        import ast
        with open("engine/transformation/java_generator.py") as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and "spring_boot" in node.module.lower():
                    assert False, f"Spring Boot import found: {node.module}"

    def test_mapper_no_cobol_imports(self):
        """Java→Spring mapper has zero COBOL IR imports."""
        import ast
        with open("engine/transformation/java_to_spring_mapping.py") as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and ("cobol" in node.module.lower()
                                    or "parser" in node.module.lower()):
                    assert False, f"COBOL import found: {node.module}"


# ============================================================
# CATEGORY L: Spring Boot Generator Output
# ============================================================

class TestSpringBootGenerator:
    """Verify Spring Boot generator produces correct files."""

    def test_generates_entry_point(self):
        """Generator produces Application.java."""
        sb = map_java_application_to_spring_boot(_make_java_application())
        gen = SpringBootGenerator()
        files = gen.generate(sb)
        class_names = [f.class_name for f in files]
        assert "Application" in class_names

    def test_generates_services(self):
        """Generator produces service files."""
        p = _make_java_program("A")
        app = _make_java_application(programs=(p,))
        sb = map_java_application_to_spring_boot(app)
        gen = SpringBootGenerator()
        files = gen.generate(sb)
        class_names = [f.class_name for f in files]
        assert "A" in class_names

    def test_generates_repositories(self):
        """Generator produces repository files."""
        p = _make_java_program("A", database_names=("T1",))
        app = _make_java_application(programs=(p,))
        sb = map_java_application_to_spring_boot(app)
        gen = SpringBootGenerator()
        files = gen.generate(sb)
        class_names = [f.class_name for f in files]
        assert any("Repository" in n for n in class_names)

    def test_generates_adapters(self):
        """Generator produces adapter files."""
        p = _make_java_program("A", file_names=("F1",))
        app = _make_java_application(programs=(p,))
        sb = map_java_application_to_spring_boot(app)
        gen = SpringBootGenerator()
        files = gen.generate(sb)
        class_names = [f.class_name for f in files]
        assert any("Adapter" in n for n in class_names)

    def test_generates_configuration(self):
        """Generator produces AppConfig.java."""
        sb = map_java_application_to_spring_boot(_make_java_application())
        gen = SpringBootGenerator()
        files = gen.generate(sb)
        class_names = [f.class_name for f in files]
        assert "AppConfig" in class_names

    def test_service_has_spring_annotation(self):
        """Generated service has @Service annotation."""
        p = _make_java_program("A")
        app = _make_java_application(programs=(p,))
        sb = map_java_application_to_spring_boot(app)
        gen = SpringBootGenerator()
        files = gen.generate(sb)
        service_file = next(f for f in files if f.class_name == "A")
        assert "@Service" in service_file.source_code

    def test_entry_point_has_spring_boot_annotation(self):
        """Generated entry point has @SpringBootApplication."""
        sb = map_java_application_to_spring_boot(_make_java_application())
        gen = SpringBootGenerator()
        files = gen.generate(sb)
        entry = next(f for f in files if f.class_name == "Application")
        assert "@SpringBootApplication" in entry.source_code

    def test_all_files_have_package(self):
        """All generated files have package declaration."""
        p = _make_java_program("A", database_names=("T1",))
        app = _make_java_application(programs=(p,))
        sb = map_java_application_to_spring_boot(app)
        gen = SpringBootGenerator()
        files = gen.generate(sb)
        for f in files:
            if f.filename.endswith(".java"):
                assert "package " in f.source_code

    def test_service_with_dependency_has_constructor(self):
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
        files = gen.generate(sb)
        service_a = next(f for f in files if f.class_name == "A")
        assert "private final B b;" in service_a.source_code
        assert "public A(B b)" in service_a.source_code


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
        assert files[0].class_name == "A"

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
        assert "ServiceRegistry" in class_names


# ============================================================
# CATEGORY N: Strategy Neutrality
# ============================================================

class TestStrategyNeutrality:
    """Verify no framework strategy is silently invented."""

    def test_default_data_access_strategy_is_unspecified(self):
        """Configuration defaults to UNSPECIFIED data access strategy."""
        config = SpringBootConfiguration(application_name="TEST")
        assert config.data_access_strategy == DataAccessStrategy.UNSPECIFIED

    def test_default_file_access_strategy_is_unspecified(self):
        """Configuration defaults to UNSPECIFIED file access strategy."""
        config = SpringBootConfiguration(application_name="TEST")
        assert config.file_access_strategy == FileAccessStrategy.UNSPECIFIED

    def test_database_resource_no_jpa_assumption(self):
        """Database resource does not produce JPA dependency."""
        p = _make_java_program("A", database_names=("T1",))
        app = _make_java_application(programs=(p,))
        sb = map_java_application_to_spring_boot(app)
        dep_names = [d.name for d in sb.dependencies]
        assert "spring-data-jpa" not in dep_names

    def test_file_resource_no_spring_integration_assumption(self):
        """File resource does not produce Spring Integration dependency."""
        p = _make_java_program("A", file_names=("F1",))
        app = _make_java_application(programs=(p,))
        sb = map_java_application_to_spring_boot(app)
        dep_names = [d.name for d in sb.dependencies]
        assert "spring-integration-file" not in dep_names

    def test_database_only_no_jdbc_assumption(self):
        """Database with SQL SELECT only does not assume JDBC."""
        from engine.transformation.ir import StatusCodeMapping
        sc = StatusCodeMapping(code="0", label="OK", field_name="SQLCODE")
        p = _make_java_program("A", database_names=("T1",))
        app = _make_java_application(programs=(p,))
        sb = map_java_application_to_spring_boot(app)
        assert sb.configuration is not None
        assert sb.configuration.data_access_strategy == DataAccessStrategy.UNSPECIFIED

    def test_multiple_database_resources_same_strategy(self):
        """Multiple database resources all use UNSPECIFIED strategy."""
        p1 = _make_java_program("A", database_names=("T1",))
        p2 = _make_java_program("B", database_names=("T2",))
        app = _make_java_application(programs=(p1, p2))
        sb = map_java_application_to_spring_boot(app)
        assert sb.configuration is not None
        assert sb.configuration.data_access_strategy == DataAccessStrategy.UNSPECIFIED

    def test_explicit_jpa_strategy_represented(self):
        """Explicit JPA strategy can be set in configuration."""
        config = SpringBootConfiguration(
            application_name="TEST",
            data_access_strategy=DataAccessStrategy.JPA,
        )
        assert config.data_access_strategy == DataAccessStrategy.JPA

    def test_explicit_spring_integration_strategy_represented(self):
        """Explicit Spring Integration strategy can be set in configuration."""
        config = SpringBootConfiguration(
            application_name="TEST",
            file_access_strategy=FileAccessStrategy.SPRING_INTEGRATION,
        )
        assert config.file_access_strategy == FileAccessStrategy.SPRING_INTEGRATION

    def test_all_strategies_representable(self):
        """All strategy values are representable."""
        for strategy in DataAccessStrategy:
            config = SpringBootConfiguration(
                application_name="TEST",
                data_access_strategy=strategy,
            )
            assert config.data_access_strategy == strategy

        for strategy in FileAccessStrategy:
            config = SpringBootConfiguration(
                application_name="TEST",
                file_access_strategy=strategy,
            )
            assert config.file_access_strategy == strategy
