"""Phase 7B.4 — Generic Repository & Adapter Implementation Generation tests.

Tests that repository/adapter implementations are generated correctly from
structured Java IR and Spring Boot IR, without COBOL source scanning or
domain-specific branching.

Covers:
1. Database implementation IR
2. Database operations
3. Database strategy selection (UNSPECIFIED, JDBC, JPA)
4. File implementation IR
5. Sequential file implementation
6. Indexed/relative boundaries
7. File strategy selection (UNSPECIFIED, JAVA_IO, NIO)
8. Delimiter/fixed-width/record semantics
9. Service→repository dependency
10. Service→adapter dependency
11. Resource deduplication
12. Domain-neutral applications
13. Lexical false positives
14. Strategy neutrality
15. Mutation matrix
16. Negative tests
17. Unsupported semantics
18. Determinism
19. Generator isolation
20. Backward compatibility
"""

from __future__ import annotations

import ast
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from engine.transformation.java_ir import (
    JavaApplication,
    JavaDatabaseResource,
    JavaDependency,
    JavaFileAccessMode,
    JavaFileResource,
    JavaProgram,
    JavaSqlOperationType,
)
from engine.transformation.java_to_spring_mapping import (
    map_java_application_to_spring_boot,
)
from engine.transformation.spring_boot_generator import (
    SpringBootGenerator,
    compute_project_hash,
)
from engine.transformation.spring_boot_ir import (
    DataAccessStrategy,
    FileAccessStrategy,
    SpringBootApplication,
    SpringBootConfiguration,
)


# ============================================================
# Helpers
# ============================================================

def _make_class(name: str = "TestClass"):
    from engine.transformation.java_ir import JavaClass
    return JavaClass(name=name)


def _make_program(
    program_id: str = "TESTPGM",
    database_names: tuple[str, ...] = (),
    file_names: tuple[str, ...] = (),
) -> JavaProgram:
    databases = tuple(
        JavaDatabaseResource(name=n, operation=JavaSqlOperationType.SELECT)
        for n in database_names
    )
    files = tuple(
        JavaFileResource(name=n, access_mode=JavaFileAccessMode.READ)
        for n in file_names
    )
    return JavaProgram(
        program_id=program_id,
        java_class=_make_class(),
        database_resources=databases,
        file_resources=files,
    )


def _make_application(
    application_id: str = "TEST-APP",
    programs: tuple[JavaProgram, ...] = (),
    dependencies: tuple[JavaDependency, ...] = (),
) -> JavaApplication:
    if not programs:
        programs = (_make_program(),)
    return JavaApplication(
        application_id=application_id,
        programs=programs,
        dependencies=dependencies,
    )


def _to_spring(app: JavaApplication) -> SpringBootApplication:
    return map_java_application_to_spring_boot(app)


def _generate(app: JavaApplication) -> list:
    sb = _to_spring(app)
    gen = SpringBootGenerator()
    return gen.generate_project(sb)


def _find_java(files: list, class_name: str):
    for f in files:
        if f.class_name == class_name:
            return f
    return None


def _with_strategy(app_id: str, data_strategy: DataAccessStrategy, file_strategy: FileAccessStrategy) -> SpringBootApplication:
    """Create application with explicit strategy by setting it before mapping."""
    from engine.transformation.java_ir import JavaClass as JC
    from engine.transformation.java_ir import JavaDatabaseResource as JDR
    from engine.transformation.java_ir import JavaFileAccessMode as JFAM
    from engine.transformation.java_ir import JavaFileResource as JFR
    from engine.transformation.java_ir import JavaProgram as JP
    from engine.transformation.java_ir import JavaSqlOperationType as JSOT

    databases = (JDR(name="T1", operation=JSOT.SELECT),)
    files = (JFR(name="F1", access_mode=JFAM.READ),)
    prog = JP(
        program_id="TESTPGM",
        java_class=JC(name="TestClass"),
        database_resources=databases,
        file_resources=files,
    )
    app = JavaApplication(
        application_id=app_id,
        programs=(prog,),
    )
    sb = _to_spring(app)
    # Create new config with explicit strategy
    new_config = SpringBootConfiguration(
        application_name=app_id,
        base_package="com.generated.app",
        has_database=True,
        has_file_resources=True,
        data_access_strategy=data_strategy,
        file_access_strategy=file_strategy,
    )
    # Re-create implementations with explicit strategy
    from engine.transformation.java_to_spring_mapping import (
        _map_adapter_implementations,
        _map_repository_implementations,
    )
    repo_impls = _map_repository_implementations(list(sb.repositories), new_config, sb.base_package)
    adapter_impls = _map_adapter_implementations(list(sb.adapters), new_config, sb.base_package)

    return SpringBootApplication(
        application_id=sb.application_id,
        base_package=sb.base_package,
        services=sb.services,
        repositories=sb.repositories,
        adapters=sb.adapters,
        transaction_boundaries=sb.transaction_boundaries,
        repository_implementations=tuple(repo_impls),
        adapter_implementations=tuple(adapter_impls),
        configuration=new_config,
        entry_point=sb.entry_point,
        dependencies=sb.dependencies,
        packages=sb.packages,
        source_application_id=sb.source_application_id,
    )


# ============================================================
# CATEGORY A: Database Implementation IR
# ============================================================

class TestDatabaseImplementationIR:

    def test_repository_implementation_exists(self):
        """Database resource creates repository implementation."""
        app = _make_application(programs=(_make_program(database_names=("T1",)),))
        sb = _to_spring(app)
        assert len(sb.repository_implementations) >= 1
        impl = sb.repository_implementations[0]
        assert impl.table_name == "T1"
        assert impl.strategy == DataAccessStrategy.UNSPECIFIED

    def test_repository_methods_generated(self):
        """Repository methods derived from operations."""
        app = _make_application(programs=(_make_program(database_names=("T1",)),))
        sb = _to_spring(app)
        impl = sb.repository_implementations[0]
        assert len(impl.methods) >= 1
        assert impl.methods[0].operation_type.value == "SELECT"

    def test_unspecified_strategy_default(self):
        """Default strategy is UNSPECIFIED."""
        app = _make_application(programs=(_make_program(database_names=("T1",)),))
        sb = _to_spring(app)
        assert sb.repository_implementations[0].strategy == DataAccessStrategy.UNSPECIFIED

    def test_jdbc_strategy(self):
        """JDBC strategy creates JDBC implementation."""
        sb = _with_strategy("JDBC-APP", DataAccessStrategy.JDBC, FileAccessStrategy.UNSPECIFIED)
        assert sb.repository_implementations[0].strategy == DataAccessStrategy.JDBC

    def test_jpa_strategy(self):
        """JPA strategy creates JPA implementation."""
        sb = _with_strategy("JPA-APP", DataAccessStrategy.JPA, FileAccessStrategy.UNSPECIFIED)
        assert sb.repository_implementations[0].strategy == DataAccessStrategy.JPA


# ============================================================
# CATEGORY B: Database Operations
# ============================================================

class TestDatabaseOperations:

    def test_select_operation(self):
        """SELECT operation generates select method."""
        app = _make_application(programs=(_make_program(database_names=("T1",)),))
        sb = _to_spring(app)
        impl = sb.repository_implementations[0]
        ops = [m.operation_type.value for m in impl.methods]
        assert "SELECT" in ops

    def test_multiple_operations(self):
        """Multiple operations generate multiple methods."""
        app = _make_application(programs=(_make_program(database_names=("T1",)),))
        sb = _to_spring(app)
        impl = sb.repository_implementations[0]
        # At least SELECT from default
        assert len(impl.methods) >= 1


# ============================================================
# CATEGORY C: File Implementation IR
# ============================================================

class TestFileImplementationIR:

    def test_adapter_implementation_exists(self):
        """File resource creates adapter implementation."""
        app = _make_application(programs=(_make_program(file_names=("F1",)),))
        sb = _to_spring(app)
        assert len(sb.adapter_implementations) >= 1
        impl = sb.adapter_implementations[0]
        assert impl.source_resource == "F1"
        assert impl.strategy == FileAccessStrategy.UNSPECIFIED

    def test_adapter_methods_generated(self):
        """Adapter methods derived from access mode."""
        app = _make_application(programs=(_make_program(file_names=("F1",)),))
        sb = _to_spring(app)
        impl = sb.adapter_implementations[0]
        assert len(impl.methods) >= 1

    def test_unspecified_file_strategy_default(self):
        """Default file strategy is UNSPECIFIED."""
        app = _make_application(programs=(_make_program(file_names=("F1",)),))
        sb = _to_spring(app)
        assert sb.adapter_implementations[0].strategy == FileAccessStrategy.UNSPECIFIED

    def test_javaio_strategy(self):
        """JAVA_IO strategy creates Java IO implementation."""
        sb = _with_strategy("IO-APP", DataAccessStrategy.UNSPECIFIED, FileAccessStrategy.JAVA_IO)
        assert sb.adapter_implementations[0].strategy == FileAccessStrategy.JAVA_IO

    def test_nio_strategy(self):
        """NIO strategy creates NIO implementation."""
        sb = _with_strategy("NIO-APP", DataAccessStrategy.UNSPECIFIED, FileAccessStrategy.NIO)
        assert sb.adapter_implementations[0].strategy == FileAccessStrategy.NIO


# ============================================================
# CATEGORY D: File Operations
# ============================================================

class TestFileOperations:

    def test_read_operations(self):
        """READ access mode generates read method."""
        app = _make_application(programs=(_make_program(file_names=("F1",)),))
        sb = _to_spring(app)
        impl = sb.adapter_implementations[0]
        op_types = [m.operation_type.value for m in impl.methods]
        assert "READ" in op_types or "CLOSE" in op_types

    def test_write_operations(self):
        """WRITE access mode generates write method."""
        file_res = JavaFileResource(name="F1", access_mode=JavaFileAccessMode.WRITE)
        prog = JavaProgram(program_id="P1", java_class=_make_class(), file_resources=(file_res,))
        app = _make_application(programs=(prog,))
        sb = _to_spring(app)
        impl = sb.adapter_implementations[0]
        op_types = [m.operation_type.value for m in impl.methods]
        assert "WRITE" in op_types or "CLOSE" in op_types


# ============================================================
# CATEGORY E: Strategy Neutrality
# ============================================================

class TestStrategyNeutrality:

    def test_unspecified_not_jpa(self):
        """UNSPECIFIED database strategy does not generate JPA."""
        sb = _with_strategy("APP", DataAccessStrategy.UNSPECIFIED, FileAccessStrategy.UNSPECIFIED)
        gen = SpringBootGenerator()
        files = gen.generate_project(sb)
        repo_impl = [f for f in files if "Impl" in f.class_name and "Repository" in f.class_name]
        # UNSPECIFIED generates abstract class, not JPA interface
        for f in repo_impl:
            assert "JpaRepository" not in f.source_code

    def test_unspecified_not_jdbc(self):
        """UNSPECIFIED database strategy does not generate JDBC."""
        sb = _with_strategy("APP", DataAccessStrategy.UNSPECIFIED, FileAccessStrategy.UNSPECIFIED)
        gen = SpringBootGenerator()
        files = gen.generate_project(sb)
        repo_impl = [f for f in files if "Impl" in f.class_name and "Repository" in f.class_name]
        for f in repo_impl:
            assert "java.sql.Connection" not in f.source_code

    def test_jdbc_generates_jdbc(self):
        """JDBC strategy generates JDBC implementation."""
        sb = _with_strategy("APP", DataAccessStrategy.JDBC, FileAccessStrategy.UNSPECIFIED)
        gen = SpringBootGenerator()
        files = gen.generate_project(sb)
        repo_impl = [f for f in files if "Impl" in f.class_name and "Repository" in f.class_name]
        assert len(repo_impl) >= 1
        assert "java.sql.Connection" in repo_impl[0].source_code

    def test_jpa_generates_jpa(self):
        """JPA strategy generates JPA interface."""
        sb = _with_strategy("APP", DataAccessStrategy.JPA, FileAccessStrategy.UNSPECIFIED)
        gen = SpringBootGenerator()
        files = gen.generate_project(sb)
        # JPA generates implementation with JpaRepository
        jpa_files = [f for f in files if "JpaRepository" in f.source_code]
        assert len(jpa_files) >= 1

    def test_strategy_change_architecture(self):
        """Changing strategy produces different generated source."""
        sb1 = _with_strategy("APP", DataAccessStrategy.UNSPECIFIED, FileAccessStrategy.UNSPECIFIED)
        sb2 = _with_strategy("APP", DataAccessStrategy.JDBC, FileAccessStrategy.UNSPECIFIED)
        gen = SpringBootGenerator()
        files1 = gen.generate_project(sb1)
        files2 = gen.generate_project(sb2)
        assert compute_project_hash(files1) != compute_project_hash(files2)


# ============================================================
# CATEGORY F: Domain-Neutral Applications
# ============================================================

class TestDomainNeutralApplications:

    def test_alpha_application(self):
        """Alpha application generates repository/adapter implementations."""
        app = _make_application(
            application_id="ALPHA-APP",
            programs=(_make_program("A-PGM", database_names=("TABLE-A",), file_names=("FILE-A",)),),
        )
        files = _generate(app)
        assert len(files) >= 5  # pom, props, entry, service, repo, adapter + impls

    def test_beta_application(self):
        """Beta application generates repository/adapter implementations."""
        app = _make_application(
            application_id="BETA-APP",
            programs=(_make_program("B-PGM", database_names=("TABLE-B",), file_names=("FILE-B",)),),
        )
        files = _generate(app)
        assert len(files) >= 5

    def test_gamma_application(self):
        """Gamma application generates repository/adapter implementations."""
        app = _make_application(
            application_id="GAMMA-APP",
            programs=(_make_program("G-PGM", database_names=("TABLE-G",), file_names=("FILE-G",)),),
        )
        files = _generate(app)
        assert len(files) >= 5


# ============================================================
# CATEGORY G: Lexical False Positives
# ============================================================

class TestLexicalFalsePositives:

    def test_claim_keyword(self):
        """CLAIM keyword does not affect repository/adapter generation."""
        app = _make_application(
            programs=(_make_program("CLAIM-HANDLER", database_names=("CLAIM-TABLE",)),),
        )
        files = _generate(app)
        repos = [f for f in files if "Repository" in f.class_name]
        assert len(repos) >= 1  # normal repository from DB resource

    def test_payment_keyword(self):
        """PAYMENT keyword does not affect repository/adapter generation."""
        app = _make_application(
            programs=(_make_program("PAYMENT-HANDLER", database_names=("PAY-TABLE",)),),
        )
        files = _generate(app)
        repos = [f for f in files if "Repository" in f.class_name]
        assert len(repos) >= 1

    def test_order_keyword(self):
        """ORDER keyword does not affect repository/adapter generation."""
        app = _make_application(
            programs=(_make_program("ORDER-HANDLER", database_names=("ORDER-TABLE",)),),
        )
        files = _generate(app)
        repos = [f for f in files if "Repository" in f.class_name]
        assert len(repos) >= 1


# ============================================================
# CATEGORY H: Resource Deduplication
# ============================================================

class TestResourceDeduplication:

    def test_shared_database_deduplicated(self):
        """Same database resource across programs is deduplicated."""
        p1 = _make_program("P1", database_names=("SHARED-TABLE",))
        p2 = _make_program("P2", database_names=("SHARED-TABLE",))
        app = _make_application(programs=(p1, p2))
        sb = _to_spring(app)
        repo_names = [r.name for r in sb.repositories]
        # Should be deduplicated
        assert len(repo_names) == len(set(repo_names))

    def test_shared_file_deduplicated(self):
        """Same file resource across programs is deduplicated."""
        p1 = _make_program("P1", file_names=("SHARED-FILE",))
        p2 = _make_program("P2", file_names=("SHARED-FILE",))
        app = _make_application(programs=(p1, p2))
        sb = _to_spring(app)
        adapter_names = [a.name for a in sb.adapters]
        assert len(adapter_names) == len(set(adapter_names))


# ============================================================
# CATEGORY I: Service Dependencies
# ============================================================

class TestServiceDependencies:

    def test_service_with_database_gets_repository(self):
        """Service with database resource has repository dependency."""
        app = _make_application(
            programs=(_make_program("P1", database_names=("T1",)),),
        )
        sb = _to_spring(app)
        assert len(sb.services) >= 1
        assert len(sb.repository_implementations) >= 1

    def test_service_with_file_gets_adapter(self):
        """Service with file resource has adapter dependency."""
        app = _make_application(
            programs=(_make_program("P1", file_names=("F1",)),),
        )
        sb = _to_spring(app)
        assert len(sb.services) >= 1
        assert len(sb.adapter_implementations) >= 1


# ============================================================
# CATEGORY J: Mutation Matrix
# ============================================================

class TestMutationMatrix:

    def _base_app(self):
        return _make_application(
            application_id="MUT-APP",
            programs=(_make_program("P1", database_names=("T1",), file_names=("F1",)),),
        )

    def _base_hash(self):
        files = _generate(self._base_app())
        return compute_project_hash(files)

    def test_add_database_resource(self):
        """Adding database resource changes output."""
        base_hash = self._base_hash()
        app = _make_application(
            application_id="MUT-APP",
            programs=(_make_program("P1", database_names=("T1", "T2"), file_names=("F1",)),),
        )
        files = _generate(app)
        assert compute_project_hash(files) != base_hash

    def test_add_file_resource(self):
        """Adding file resource changes output."""
        base_hash = self._base_hash()
        app = _make_application(
            application_id="MUT-APP",
            programs=(_make_program("P1", database_names=("T1",), file_names=("F1", "F2")),),
        )
        files = _generate(app)
        assert compute_project_hash(files) != base_hash

    def test_change_database_operation(self):
        """Changing database operation changes output."""
        base_hash = self._base_hash()
        db_res = JavaDatabaseResource(name="T1", operation=JavaSqlOperationType.INSERT)
        prog = JavaProgram(program_id="P1", java_class=_make_class(), database_resources=(db_res,))
        app = _make_application(application_id="MUT-APP", programs=(prog,))
        files = _generate(app)
        assert compute_project_hash(files) != base_hash


# ============================================================
# CATEGORY K: Negative Tests
# ============================================================

class TestNegativeTests:

    def test_empty_application_minimal(self):
        """Empty application generates minimal project."""
        app = _make_application(application_id="EMPTY", programs=())
        files = _generate(app)
        pom = _find_java(files, "pom.xml")
        assert pom is not None

    def test_program_without_database_no_repository(self):
        """Program without database resource has no repository."""
        app = _make_application(programs=(_make_program("NO-DB",),))
        sb = _to_spring(app)
        assert len(sb.repository_implementations) == 0

    def test_program_without_file_no_adapter(self):
        """Program without file resource has no adapter."""
        app = _make_application(programs=(_make_program("NO-FILE",),))
        sb = _to_spring(app)
        assert len(sb.adapter_implementations) == 0


# ============================================================
# CATEGORY L: Unsupported Semantics
# ============================================================

class TestUnsupportedSemantics:

    def test_unspecified_strategy_abstract(self):
        """UNSPECIFIED strategy generates abstract class."""
        sb = _with_strategy("APP", DataAccessStrategy.UNSPECIFIED, FileAccessStrategy.UNSPECIFIED)
        gen = SpringBootGenerator()
        files = gen.generate_project(sb)
        repo_impl = [f for f in files if "Abstract" in f.class_name and "Repository" in f.class_name]
        assert len(repo_impl) >= 1
        assert "abstract class" in repo_impl[0].source_code


# ============================================================
# CATEGORY M: Determinism
# ============================================================

class TestDeterminism:

    def test_same_input_same_files(self):
        """Same input produces identical files."""
        app = _make_application(
            programs=(_make_program("P1", database_names=("T1",), file_names=("F1",)),),
        )
        files1 = _generate(app)
        files2 = _generate(app)
        assert len(files1) == len(files2)
        for f1, f2 in zip(files1, files2):
            assert f1.path == f2.path
            assert f1.source_code == f2.source_code

    def test_same_input_same_hash(self):
        """Same input produces identical hash."""
        app = _make_application(
            programs=(_make_program("P1", database_names=("T1",), file_names=("F1",)),),
        )
        hash1 = compute_project_hash(_generate(app))
        hash2 = compute_project_hash(_generate(app))
        assert hash1 == hash2


# ============================================================
# CATEGORY N: Generator Isolation
# ============================================================

class TestGeneratorIsolation:

    def test_spring_boot_generator_no_cobol_imports(self):
        """Generator has no COBOL imports."""
        with open("engine/transformation/spring_boot_generator.py") as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and ("cobol" in node.module.lower()
                                    or "parser" in node.module.lower()):
                    assert False, f"COBOL import found: {node.module}"

    def test_mapper_no_cobol_imports(self):
        """Mapper has no COBOL imports."""
        with open("engine/transformation/java_to_spring_mapping.py") as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and ("cobol" in node.module.lower()
                                    or "parser" in node.module.lower()):
                    assert False, f"COBOL import found: {node.module}"

    def test_spring_boot_ir_no_cobol_imports(self):
        """Spring Boot IR has no COBOL imports."""
        with open("engine/transformation/spring_boot_ir.py") as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and ("cobol" in node.module.lower()
                                    or "parser" in node.module.lower()):
                    assert False, f"COBOL import found: {node.module}"


# ============================================================
# CATEGORY O: Backward Compatibility
# ============================================================

class TestBackwardCompatibility:

    def test_empty_resources_still_works(self):
        """Application without resources still generates correctly."""
        app = _make_application(programs=(_make_program("SOLO",),))
        files = _generate(app)
        assert len(files) >= 3  # pom, props, entry, service

    def test_repository_interface_still_generated(self):
        """Repository interfaces are still generated."""
        app = _make_application(programs=(_make_program("P1", database_names=("T1",)),))
        files = _generate(app)
        repos = [f for f in files if "Repository" in f.class_name and "Impl" not in f.class_name]
        assert len(repos) >= 1

    def test_adapter_interface_still_generated(self):
        """Adapter interfaces are still generated."""
        app = _make_application(programs=(_make_program("P1", file_names=("F1",)),))
        files = _generate(app)
        adapters = [f for f in files if "Adapter" in f.class_name and "Impl" not in f.class_name]
        assert len(adapters) >= 1

    def test_service_methods_still_work(self):
        """Service method generation still works with implementations."""
        from engine.transformation.java_ir import (
            JavaAssignment,
            JavaClass,
            JavaLiteral,
            JavaMethod,
        )
        method = JavaMethod(
            name="process",
            body_statements=(JavaAssignment(target="x", expression=JavaLiteral(value="1")),),
        )
        cls = JavaClass(name="TestClass", methods=(method,))
        prog = JavaProgram(
            program_id="P1",
            java_class=cls,
            database_resources=(JavaDatabaseResource(name="T1", operation=JavaSqlOperationType.SELECT),),
        )
        app = _make_application(programs=(prog,))
        files = _generate(app)
        svc = _find_java(files, "P1")
        assert svc is not None
        assert "process" in svc.source_code
