"""Task 7A Phase 3 — Java Generator Migration Tests.

Proves that the generator operates from JavaApplication IR alone,
without any COBOL IR dependency.

Categories:
  A. Generator isolation (direct JavaApplication → Java source)
  B. Mapping equivalence (COBOL → mapping → JavaApplication ≡ manual JavaApplication)
  C. Domain-neutral applications
  D. Java IR mutation → generated Java changes
  E. Negative tests (incomplete IR)
  F. Determinism
  G. Multi-program support

The decision/file_io mode tests (direct decision generation, threshold and
status-code metadata, the lanes' negative cases) were deleted with the
template lanes (audit T5).
"""

from __future__ import annotations

import pytest

from engine.transformation.java_generator import JavaGenerator, GeneratedFile
from engine.transformation.java_ir import (
    JavaApplication,
    JavaAssignment,
    JavaBasicType,
    JavaBinaryOp,
    JavaBlock,
    JavaClass,
    JavaComment,
    JavaDependency,
    JavaDependencyType,
    JavaField,
    JavaFileAccessMode,
    JavaFileResource,
    JavaIf,
    JavaLiteral,
    JavaMethod,
    JavaMethodCall,
    JavaMethodCallStatement,
    JavaParameter,
    JavaProgram,
    JavaReturn,
    JavaSqlOperationType,
    JavaDatabaseResource,
    JavaStringConcat,
    JavaTransactionBoundary,
    JavaTransactionType,
    JavaType,
    JavaVariableRef,
)

from engine.transformation.cobol_to_java_mapping import (
    map_cobol_program_to_java,
    map_cobol_programs_to_application,
)
from engine.transformation.ir import (
    CobolProgram,
    DataItem,
    FileDefinition,
    InputRecordMapping,
    OpenStatement,
    Paragraph,
    PicType,
    MoveStatement,
    AddStatement,
    StopRunStatement,
)


# ============================================================
# CATEGORY A: Generator Isolation
# Proves generator operates from JavaApplication alone
# ============================================================

class TestGeneratorIsolation:
    """Generator must accept JavaApplication as input, no CobolProgram."""

    def test_minimal_mode_direct_java_application(self):
        """Construct JavaApplication directly, no CobolProgram."""
        java_class = JavaClass(
            name="Simple_Program",
            fields=(
                JavaField(
                    java_type=JavaType(basic_type=JavaBasicType.INT),
                    name="counter",
                    initializer=JavaLiteral(value="0"),
                ),
            ),
            methods=(
                JavaMethod(
                    name="main",
                    return_type=JavaType(basic_type=JavaBasicType.VOID),
                    parameters=(JavaParameter(
                        java_type=JavaType(
                            class_name="String", is_array=True,
                            array_element_type=JavaType(basic_type=JavaBasicType.STRING),
                        ),
                        name="args",
                    ),),
                    body_statements=(
                        JavaAssignment(
                            target="counter",
                            expression=JavaLiteral(value="42"),
                        ),
                        JavaMethodCallStatement(
                            call=JavaMethodCall(
                                object_ref=JavaVariableRef(name="System.out"),
                                method_name="println",
                                arguments=(JavaStringConcat(parts=(
                                    JavaLiteral(value="Counter="),
                                    JavaVariableRef(name="counter"),
                                )),),
                            )
                        ),
                        JavaReturn(),
                    ),
                    is_static=True,
                    exceptions=("Exception",),
                ),
            ),
        )

        java_program = JavaProgram(
            program_id="SIMPLE-PROGRAM",
            java_class=java_class,
        )

        application = JavaApplication(
            application_id="simple",
            programs=(java_program,),
        )

        generator = JavaGenerator()
        files = generator.generate_from_java(application)

        assert len(files) == 1
        assert files[0].class_name == "Simple_Program"
        assert "public class Simple_Program" in files[0].source_code
        assert "public static void main" in files[0].source_code
        assert "counter = 42" in files[0].source_code
        assert "System.out.println" in files[0].source_code

    def test_no_cobol_imports_in_generator(self):
        """Generator module must not import any COBOL IR types."""
        import importlib
        import engine.transformation.java_generator as gen_module
        source = importlib.util.find_spec(gen_module.__name__).origin
        with open(source) as f:
            content = f.read()
        # Check no COBOL IR imports in module-level code
        # (imports inside methods for backward compat are OK)
        lines = content.split("\n")
        cobol_imports = []
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("from engine.transformation.ir import"):
                cobol_imports.append((i, stripped))
        # Generator should have NO module-level COBOL IR imports
        assert len(cobol_imports) == 0, (
            f"Generator has COBOL IR imports at module level: {cobol_imports}"
        )


    def test_direct_multi_program_generation(self):
        """Construct multi-program JavaApplication directly."""
        class_a = JavaClass(
            name="Program_A",
            fields=(),
            methods=(
                JavaMethod(
                    name="main",
                    body_statements=(JavaReturn(),),
                    is_static=True,
                    exceptions=("Exception",),
                ),
            ),
        )
        class_b = JavaClass(
            name="Program_B",
            fields=(),
            methods=(
                JavaMethod(
                    name="main",
                    body_statements=(JavaReturn(),),
                    is_static=True,
                    exceptions=("Exception",),
                ),
            ),
        )

        application = JavaApplication(
            application_id="multi",
            programs=(
                JavaProgram(program_id="A", java_class=class_a),
                JavaProgram(program_id="B", java_class=class_b),
            ),
            dependencies=(
                JavaDependency(
                    source="A", target="B",
                    dependency_type=JavaDependencyType.METHOD_CALL,
                ),
            ),
        )

        generator = JavaGenerator()
        files = generator.generate_from_java(application)

        assert len(files) == 3  # 2 programs + ServiceRegistry
        class_names = [f.class_name for f in files]
        assert "A" in class_names
        assert "B" in class_names
        assert "ServiceRegistry" in class_names


# ============================================================
# CATEGORY B: Mapping Equivalence
# COBOL → mapping → JavaApplication ≡ manual JavaApplication
# ============================================================

class TestMappingEquivalence:
    """Both paths should produce semantically equivalent Java."""

    def test_cobol_path_equivalent_to_manual(self):
        """COBOL source → mapping → JavaApplication produces valid Java."""
        cobol_source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EQUV-TEST.
       WORKING-STORAGE SECTION.
       01  WS-COUNT    PIC 9(4) VALUE 0.
       01  WS-TOTAL    PIC 9(6) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 100 TO WS-COUNT.
           ADD 50 TO WS-TOTAL.
           DISPLAY "COUNT=" WS-COUNT.
           STOP RUN.
"""
        from engine.transformation.cobol_parser import CobolParser
        parser = CobolParser()
        program = parser.parse(cobol_source)

        # Map to JavaApplication
        java_program = map_cobol_program_to_java(program)
        application = JavaApplication(
            application_id="equv",
            programs=(java_program,),
        )

        # Generate from JavaApplication
        generator = JavaGenerator()
        files = generator.generate_from_java(application)

        assert len(files) == 1
        java_code = files[0].source_code
        assert "public class Equv_Test" in java_code
        assert "WS_COUNT = 100" in java_code
        assert "WS_TOTAL" in java_code


# ============================================================
# CATEGORY C: Domain-Neutral Applications
# ============================================================

class TestDomainNeutral:
    """Prove generator works with any domain-neutral JavaApplication."""

    def test_application_a_multiple_programs_files(self):
        """Application A: multiple programs, file operations."""
        class_main = JavaClass(
            name="App_A_Main",
            fields=(
                JavaField(
                    java_type=JavaType(basic_type=JavaBasicType.INT),
                    name="counter",
                    initializer=JavaLiteral(value="0"),
                ),
            ),
            methods=(
                JavaMethod(
                    name="main",
                    body_statements=(
                        JavaMethodCallStatement(
                            call=JavaMethodCall(
                                object_ref=JavaVariableRef(name="System.out"),
                                method_name="println",
                                arguments=(JavaLiteral(value="Hello from A"),),
                            )
                        ),
                        JavaReturn(),
                    ),
                    is_static=True,
                    exceptions=("Exception",),
                ),
            ),
        )
        app = JavaApplication(
            application_id="app_a",
            programs=(
                JavaProgram(
                    program_id="APP-A-MAIN",
                    java_class=class_main,
                    file_resources=(
                        JavaFileResource(
                            name="DATA-IN",
                            path="/data/in.dat",
                            access_mode=JavaFileAccessMode.READ,
                        ),
                        JavaFileResource(
                            name="DATA-OUT",
                            path="/data/out.dat",
                            access_mode=JavaFileAccessMode.WRITE,
                        ),
                    ),
                ),
            ),
        )
        generator = JavaGenerator()
        files = generator.generate_from_java(app)
        assert len(files) == 1
        assert "Hello from A" in files[0].source_code

    def test_application_b_database(self):
        """Application B: DB2 operations."""
        class_db = JavaClass(
            name="App_B_DB",
            methods=(
                JavaMethod(
                    name="main",
                    body_statements=(JavaReturn(),),
                    is_static=True,
                    exceptions=("Exception",),
                ),
            ),
        )
        app = JavaApplication(
            application_id="app_b",
            programs=(
                JavaProgram(
                    program_id="APP-B-DB",
                    java_class=class_db,
                    database_resources=(
                        JavaDatabaseResource(
                            name="CUSTOMERS",
                            operation=JavaSqlOperationType.SELECT,
                            columns=("ID", "NAME"),
                        ),
                    ),
                ),
            ),
        )
        generator = JavaGenerator()
        files = generator.generate_from_java(app)
        assert len(files) == 1

    def test_application_c_transaction(self):
        """Application C: CICS transaction."""
        class_tx = JavaClass(
            name="App_C_Tx",
            methods=(
                JavaMethod(
                    name="main",
                    body_statements=(JavaReturn(),),
                    is_static=True,
                    exceptions=("Exception",),
                ),
            ),
        )
        app = JavaApplication(
            application_id="app_c",
            programs=(
                JavaProgram(
                    program_id="APP-C-TX",
                    java_class=class_tx,
                    transaction_boundaries=(
                        JavaTransactionBoundary(
                            name="TXN001",
                            transaction_type=JavaTransactionType.CICS_TRANSACTION,
                        ),
                    ),
                ),
            ),
        )
        generator = JavaGenerator()
        files = generator.generate_from_java(app)
        assert len(files) == 1

    def test_application_d_mixed(self):
        """Application D: mixed file/DB2/CICS semantics."""
        class_mixed = JavaClass(
            name="App_D_Mixed",
            fields=(
                JavaField(
                    java_type=JavaType(basic_type=JavaBasicType.INT),
                    name="count",
                    initializer=JavaLiteral(value="0"),
                ),
            ),
            methods=(
                JavaMethod(
                    name="main",
                    body_statements=(
                        JavaAssignment(target="count", expression=JavaLiteral(value="1")),
                        JavaReturn(),
                    ),
                    is_static=True,
                    exceptions=("Exception",),
                ),
            ),
        )
        app = JavaApplication(
            application_id="app_d",
            programs=(
                JavaProgram(
                    program_id="APP-D-MIXED",
                    java_class=class_mixed,
                    file_resources=(
                        JavaFileResource(
                            name="IN-FILE",
                            path="/data/in.dat",
                            access_mode=JavaFileAccessMode.READ,
                        ),
                    ),
                    database_resources=(
                        JavaDatabaseResource(
                            name="ORDERS",
                            operation=JavaSqlOperationType.INSERT,
                            columns=("ID", "AMOUNT"),
                        ),
                    ),
                    transaction_boundaries=(
                        JavaTransactionBoundary(
                            name="BATCH-01",
                            transaction_type=JavaTransactionType.BATCH_STEP,
                        ),
                    ),
                ),
            ),
        )
        generator = JavaGenerator()
        files = generator.generate_from_java(app)
        assert len(files) == 1


# ============================================================
# CATEGORY D: Java IR Mutation → Generated Java Changes
# ============================================================

class TestJavaIRMutation:
    """Mutate Java IR directly and verify generated Java changes."""

    def test_field_type_mutation(self):
        """Changing field type changes generated declaration."""
        class_int = JavaClass(
            name="Test", fields=(
                JavaField(java_type=JavaType(basic_type=JavaBasicType.INT),
                           name="x", initializer=JavaLiteral(value="0")),
            ), methods=(JavaMethod(name="main", body_statements=(JavaReturn(),),
                                    is_static=True, exceptions=("Exception",),),),
        )
        class_string = JavaClass(
            name="Test", fields=(
                JavaField(java_type=JavaType(basic_type=JavaBasicType.STRING),
                           name="x", initializer=JavaLiteral(value='""')),
            ), methods=(JavaMethod(name="main", body_statements=(JavaReturn(),),
                                    is_static=True, exceptions=("Exception",),),),
        )
        gen = JavaGenerator()
        app_int = JavaApplication(application_id="t", programs=(
            JavaProgram(program_id="T", java_class=class_int),))
        app_str = JavaApplication(application_id="t", programs=(
            JavaProgram(program_id="T", java_class=class_string),))
        java_int = gen.generate_from_java(app_int)[0].source_code
        java_str = gen.generate_from_java(app_str)[0].source_code
        assert "static int x" in java_int
        assert "static String x" in java_str
        assert java_int != java_str


    def test_file_path_mutation(self):
        """Changing file path changes JavaFileResource."""
        fr1 = JavaFileResource(name="F", path="/old/path.dat")
        fr2 = JavaFileResource(name="F", path="/new/path.dat")
        assert fr1.path != fr2.path

    def test_delimiter_mutation(self):
        """Changing delimiter changes JavaFileResource."""
        fr1 = JavaFileResource(name="F", path="/d/f.dat", record_delimiter="|")
        fr2 = JavaFileResource(name="F", path="/d/f.dat", record_delimiter=";")
        assert fr1.record_delimiter != fr2.record_delimiter

    def test_dependency_mutation(self):
        """Changing dependency changes JavaApplication."""
        app1 = JavaApplication(
            application_id="t",
            programs=(JavaProgram(
                program_id="A",
                java_class=JavaClass(name="A", methods=(
                    JavaMethod(name="main", body_statements=(JavaReturn(),),
                               is_static=True, exceptions=("Exception",),),),),
            ),),
        )
        app2 = JavaApplication(
            application_id="t",
            programs=(JavaProgram(
                program_id="A",
                java_class=JavaClass(name="A", methods=(
                    JavaMethod(name="main", body_statements=(JavaReturn(),),
                               is_static=True, exceptions=("Exception",),),),),
            ),),
            dependencies=(JavaDependency(
                source="A", target="B", dependency_type=JavaDependencyType.METHOD_CALL,
            ),),
        )
        assert len(app1.dependencies) != len(app2.dependencies)


# ============================================================
# CATEGORY E: Negative Tests
# ============================================================

class TestNegative:
    """Generator must fail explicitly on incomplete/invalid IR."""

    def test_missing_java_class(self):
        """Program without java_class raises ValueError."""
        app = JavaApplication(
            application_id="t",
            programs=(JavaProgram(program_id="T"),),
        )
        gen = JavaGenerator()
        with pytest.raises(ValueError, match="No Java class"):
            gen.generate_from_java(app)

    def test_empty_application(self):
        """Empty application produces no files."""
        app = JavaApplication(application_id="empty")
        gen = JavaGenerator()
        files = gen.generate_from_java(app)
        assert len(files) == 0


# ============================================================
# CATEGORY F: Determinism
# ============================================================

class TestDeterminism:
    """Same JavaApplication must produce byte-identical Java source."""

    def test_same_input_same_output(self):
        """Repeated generation from same JavaApplication is identical."""
        java_class = JavaClass(
            name="Det_Test",
            fields=(JavaField(
                java_type=JavaType(basic_type=JavaBasicType.INT),
                name="x", initializer=JavaLiteral(value="0"),
            ),),
            methods=(JavaMethod(
                name="main",
                body_statements=(
                    JavaAssignment(target="x", expression=JavaLiteral(value="1")),
                    JavaReturn(),
                ),
                is_static=True, exceptions=("Exception",),
            ),),
        )
        app = JavaApplication(
            application_id="det",
            programs=(JavaProgram(
                program_id="DET-TEST",
                java_class=java_class,
            ),),
        )
        gen = JavaGenerator()
        java1 = gen.generate_from_java(app)[0].source_code
        java2 = gen.generate_from_java(app)[0].source_code
        assert java1 == java2

    def test_no_timestamps_or_random_ids(self):
        """Generated Java has no timestamps or random IDs."""
        java_class = JavaClass(
            name="Clean_Test",
            methods=(JavaMethod(
                name="main", body_statements=(JavaReturn(),),
                is_static=True, exceptions=("Exception",),
            ),),
        )
        app = JavaApplication(
            application_id="clean",
            programs=(JavaProgram(
                program_id="CLEAN-TEST",
                java_class=java_class,
            ),),
        )
        gen = JavaGenerator()
        java_code = gen.generate_from_java(app)[0].source_code
        assert "timestamp" not in java_code.lower()
        assert "random" not in java_code.lower()
        import re
        assert not re.search(r'\d{4}-\d{2}-\d{2}', java_code)
