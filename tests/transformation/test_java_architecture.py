"""Tests for Java Application IR (Phase 7A).

Categories:
  1. JavaType creation and source rendering
  2. JavaExpression hierarchy
  3. JavaStatement hierarchy
  4. JavaField / JavaParameter / JavaMethod / JavaClass
  5. JavaFileResource / JavaDatabaseResource / JavaTransactionBoundary
  6. JavaProgram composition
  7. JavaApplication composition and validation
  8. JavaDependency graph
  9. COBOL → Java type mapping (PIC conversion)
 10. COBOL → Java statement mapping
 11. COBOL → Java program mapping
 12. COBOL → Java application mapping
 13. Negative and edge cases
 14. Determinism (frozen dataclasses)
"""

from __future__ import annotations

from engine.transformation.java_ir import (
    JavaApplication,
    JavaAssignment,
    JavaBasicType,
    JavaBinaryOp,
    JavaBlock,
    JavaCast,
    JavaClass,
    JavaComment,
    JavaConstructor,
    JavaDatabaseResource,
    JavaDependency,
    JavaDependencyType,
    JavaField,
    JavaFileAccessMode,
    JavaFileResource,
    JavaFor,
    JavaIf,
    JavaLiteral,
    JavaLocalVarDecl,
    JavaMethod,
    JavaMethodCall,
    JavaMethodCallStatement,
    JavaNewObject,
    JavaParameter,
    JavaProgram,
    JavaReturn,
    JavaSqlOperationType,
    JavaStringConcat,
    JavaSwitch,
    JavaTernary,
    JavaThrow,
    JavaTransactionBoundary,
    JavaTransactionType,
    JavaTryCatch,
    JavaType,
    JavaUnaryOp,
    JavaVariableRef,
    JavaWhile,
)

from engine.transformation.cobol_to_java_mapping import (
    map_cobol_program_to_java,
    map_cobol_programs_to_application,
    map_cobol_statement,
    map_pic_to_java_default,
    map_pic_to_java_type,
)

from engine.transformation.ir import (
    AddStatement,
    CobolProgram,
    DataItem,
    DisplayStatement,
    DivideStatement,
    FileDefinition,
    FileOrganization,
    FileAccessMode,
    GoToStatement,
    IfStatement,
    MoveStatement,
    Paragraph,
    PerformStatement,
    PicType,
    StopRunStatement,
    WriteStatement,
)


# ============================================================
# Category 1: JavaType creation and source rendering
# ============================================================

class TestJavaType:
    def test_basic_int(self):
        t = JavaType(basic_type=JavaBasicType.INT)
        assert t.is_basic
        assert not t.is_void
        assert t.to_source() == "int"

    def test_basic_long(self):
        t = JavaType(basic_type=JavaBasicType.LONG)
        assert t.to_source() == "long"

    def test_basic_double(self):
        t = JavaType(basic_type=JavaBasicType.DOUBLE)
        assert t.to_source() == "double"

    def test_basic_string(self):
        t = JavaType(basic_type=JavaBasicType.STRING)
        assert t.to_source() == "String"

    def test_basic_boolean(self):
        t = JavaType(basic_type=JavaBasicType.BOOLEAN)
        assert t.to_source() == "boolean"

    def test_basic_void(self):
        t = JavaType(basic_type=JavaBasicType.VOID)
        assert t.is_void
        assert t.to_source() == "void"

    def test_class_name(self):
        t = JavaType(class_name="List")
        assert t.to_source() == "List"

    def test_generic_type(self):
        t = JavaType(
            class_name="Map",
            generic_type_params=(
                JavaType(basic_type=JavaBasicType.STRING),
                JavaType(class_name="Object"),
            ),
        )
        assert t.to_source() == "Map<String, Object>"

    def test_array_type(self):
        t = JavaType(
            class_name="String",
            is_array=True,
            array_element_type=JavaType(basic_type=JavaBasicType.STRING),
        )
        assert t.is_array
        assert t.to_source() == "String"


# ============================================================
# Category 2: JavaExpression hierarchy
# ============================================================

class TestJavaExpressions:
    def test_literal_string(self):
        e = JavaLiteral(value="hello", java_type=JavaType(basic_type=JavaBasicType.STRING))
        assert e.value == "hello"

    def test_literal_int(self):
        e = JavaLiteral(value="42")
        assert e.value == "42"

    def test_variable_ref(self):
        e = JavaVariableRef(name="myVar")
        assert e.name == "myVar"

    def test_binary_op(self):
        e = JavaBinaryOp(
            left=JavaVariableRef(name="a"),
            operator="+",
            right=JavaVariableRef(name="b"),
        )
        assert e.operator == "+"

    def test_unary_op(self):
        e = JavaUnaryOp(
            operator="!",
            operand=JavaVariableRef(name="flag"),
        )
        assert e.operator == "!"

    def test_method_call_static(self):
        e = JavaMethodCall(
            class_name="Math",
            method_name="abs",
            arguments=(JavaVariableRef(name="x"),),
            is_static=True,
        )
        assert e.is_static
        assert e.class_name == "Math"

    def test_method_call_instance(self):
        e = JavaMethodCall(
            object_ref=JavaVariableRef(name="list"),
            method_name="size",
            arguments=(),
        )
        assert e.object_ref is not None

    def test_new_object(self):
        e = JavaNewObject(class_name="ArrayList", arguments=())
        assert e.class_name == "ArrayList"

    def test_ternary(self):
        e = JavaTernary(
            condition=JavaVariableRef(name="x"),
            true_expr=JavaLiteral(value="1"),
            false_expr=JavaLiteral(value="0"),
        )
        assert e.condition is not None

    def test_string_concat(self):
        e = JavaStringConcat(parts=(
            JavaLiteral(value="Hello "),
            JavaVariableRef(name="name"),
        ))
        assert len(e.parts) == 2

    def test_cast(self):
        e = JavaCast(
            target_type=JavaType(basic_type=JavaBasicType.INT),
            expression=JavaVariableRef(name="obj"),
        )
        assert e.target_type.to_source() == "int"


# ============================================================
# Category 3: JavaStatement hierarchy
# ============================================================

class TestJavaStatements:
    def test_assignment(self):
        s = JavaAssignment(target="x", expression=JavaLiteral(value="5"))
        assert s.target == "x"

    def test_local_var_decl(self):
        s = JavaLocalVarDecl(
            java_type=JavaType(basic_type=JavaBasicType.INT),
            name="count",
            initializer=JavaLiteral(value="0"),
        )
        assert s.name == "count"

    def test_method_call_statement(self):
        s = JavaMethodCallStatement(
            call=JavaMethodCall(method_name="doSomething", arguments=())
        )
        assert s.call.method_name == "doSomething"

    def test_if_statement(self):
        s = JavaIf(
            condition=JavaVariableRef(name="flag"),
            then_body=(JavaAssignment(target="x", expression=JavaLiteral(value="1")),),
        )
        assert len(s.then_body) == 1
        assert len(s.else_body) == 0

    def test_if_else(self):
        s = JavaIf(
            condition=JavaVariableRef(name="flag"),
            then_body=(JavaAssignment(target="x", expression=JavaLiteral(value="1")),),
            else_body=(JavaAssignment(target="x", expression=JavaLiteral(value="2")),),
        )
        assert len(s.else_body) == 1

    def test_while_loop(self):
        s = JavaWhile(
            condition=JavaBinaryOp(
                left=JavaVariableRef(name="i"),
                operator="<",
                right=JavaLiteral(value="10"),
            ),
            body=(JavaAssignment(
                target="i",
                expression=JavaBinaryOp(
                    left=JavaVariableRef(name="i"),
                    operator="+",
                    right=JavaLiteral(value="1"),
                ),
            ),),
        )
        assert len(s.body) == 1

    def test_for_loop(self):
        s = JavaFor(
            init=JavaAssignment(target="i", expression=JavaLiteral(value="0")),
            condition=JavaBinaryOp(
                left=JavaVariableRef(name="i"),
                operator="<",
                right=JavaLiteral(value="10"),
            ),
            update=JavaAssignment(
                target="i",
                expression=JavaBinaryOp(
                    left=JavaVariableRef(name="i"),
                    operator="+",
                    right=JavaLiteral(value="1"),
                ),
            ),
            body=(),
        )
        assert s.init is not None
        assert s.update is not None

    def test_try_catch(self):
        s = JavaTryCatch(
            try_body=(JavaThrow(),),
            catch_type="IOException",
            catch_var="e",
            catch_body=(JavaComment(text="handled"),),
        )
        assert s.catch_type == "IOException"

    def test_return(self):
        s = JavaReturn(expression=JavaLiteral(value="42"))
        assert s.expression is not None

    def test_return_void(self):
        s = JavaReturn()
        assert s.expression is None

    def test_throw(self):
        s = JavaThrow(exception_class="RuntimeException", message="error")
        assert s.exception_class == "RuntimeException"

    def test_block(self):
        s = JavaBlock(statements=(
            JavaAssignment(target="x", expression=JavaLiteral(value="1")),
            JavaAssignment(target="y", expression=JavaLiteral(value="2")),
        ))
        assert len(s.statements) == 2

    def test_comment(self):
        s = JavaComment(text="this is a comment")
        assert s.text == "this is a comment"

    def test_switch(self):
        s = JavaSwitch(
            expression=JavaVariableRef(name="x"),
            cases=(
                (JavaLiteral(value="1"), (JavaComment(text="case 1"),)),
                (JavaLiteral(value="2"), (JavaComment(text="case 2"),)),
            ),
            default_body=(JavaComment(text="default"),),
        )
        assert len(s.cases) == 2


# ============================================================
# Category 4: JavaField / JavaParameter / JavaMethod / JavaClass
# ============================================================

class TestJavaClassMembers:
    def test_field(self):
        f = JavaField(
            java_type=JavaType(basic_type=JavaBasicType.INT),
            name="count",
            initializer=JavaLiteral(value="0"),
            is_static=True,
        )
        assert f.name == "count"
        assert f.is_static

    def test_parameter(self):
        p = JavaParameter(
            java_type=JavaType(basic_type=JavaBasicType.STRING),
            name="input",
        )
        assert p.name == "input"

    def test_method(self):
        m = JavaMethod(
            name="process",
            return_type=JavaType(basic_type=JavaBasicType.VOID),
            parameters=(JavaParameter(
                java_type=JavaType(basic_type=JavaBasicType.STRING),
                name="data",
            ),),
            body_statements=(JavaReturn(),),
            is_static=True,
        )
        assert m.name == "process"
        assert len(m.parameters) == 1

    def test_constructor(self):
        c = JavaConstructor(
            class_name="MyClass",
            parameters=(),
            body_statements=(),
        )
        assert c.class_name == "MyClass"

    def test_class_basic(self):
        cls = JavaClass(
            name="MyClass",
            fields=(JavaField(
                java_type=JavaType(basic_type=JavaBasicType.INT),
                name="x",
            ),),
            methods=(JavaMethod(name="getX"),),
        )
        assert cls.name == "MyClass"
        assert len(cls.fields) == 1
        assert len(cls.methods) == 1

    def test_class_inheritance(self):
        cls = JavaClass(
            name="SubClass",
            extends="BaseClass",
            implements=("Serializable", "Comparable"),
        )
        assert cls.extends == "BaseClass"
        assert cls.implements == ("Serializable", "Comparable")

    def test_class_inner(self):
        inner = JavaClass(name="Inner")
        outer = JavaClass(name="Outer", inner_classes=(inner,))
        assert len(outer.inner_classes) == 1


# ============================================================
# Category 5: Resources
# ============================================================

class TestResources:
    def test_file_resource_read(self):
        r = JavaFileResource(
            name="INPUT-FILE",
            path="/data/input.dat",
            access_mode=JavaFileAccessMode.READ,
        )
        assert r.access_mode == JavaFileAccessMode.READ

    def test_file_resource_write(self):
        r = JavaFileResource(
            name="OUTPUT-FILE",
            path="/data/output.dat",
            access_mode=JavaFileAccessMode.WRITE,
        )
        assert r.access_mode == JavaFileAccessMode.WRITE

    def test_database_resource(self):
        r = JavaDatabaseResource(
            name="EMPLOYEE",
            operation=JavaSqlOperationType.SELECT,
            columns=("ID", "NAME", "SALARY"),
        )
        assert r.operation == JavaSqlOperationType.SELECT
        assert len(r.columns) == 3

    def test_transaction_boundary(self):
        t = JavaTransactionBoundary(
            name="TRANS01",
            transaction_type=JavaTransactionType.CICS_TRANSACTION,
        )
        assert t.transaction_type == JavaTransactionType.CICS_TRANSACTION


# ============================================================
# Category 6: JavaProgram composition
# ============================================================

class TestJavaProgram:
    def test_program_basic(self):
        p = JavaProgram(
            program_id="MYPROG",
            java_class=JavaClass(name="Myprog"),
        )
        assert p.program_id == "MYPROG"
        assert p.java_class is not None

    def test_program_with_file_resources(self):
        p = JavaProgram(
            program_id="MYPROG",
            file_resources=(
                JavaFileResource(name="IN", access_mode=JavaFileAccessMode.READ),
                JavaFileResource(name="OUT", access_mode=JavaFileAccessMode.WRITE),
            ),
        )
        assert len(p.file_resources) == 2

    def test_program_status_domains(self):
        p = JavaProgram(
            program_id="MYPROG",
            has_file_status=True,
            has_sqlcode=True,
            has_cics_resp=True,
        )
        assert p.has_file_status
        assert p.has_sqlcode
        assert p.has_cics_resp


# ============================================================
# Category 7: JavaApplication composition and validation
# ============================================================

class TestJavaApplication:
    def test_application_basic(self):
        app = JavaApplication(application_id="TEST")
        assert app.application_id == "TEST"
        assert len(app.programs) == 0

    def test_application_with_programs(self):
        p1 = JavaProgram(program_id="P1", java_class=JavaClass(name="P1"))
        p2 = JavaProgram(program_id="P2", java_class=JavaClass(name="P2"))
        app = JavaApplication(
            application_id="MULTI",
            programs=(p1, p2),
        )
        assert len(app.programs) == 2

    def test_get_program(self):
        p1 = JavaProgram(program_id="P1", java_class=JavaClass(name="P1"))
        app = JavaApplication(application_id="TEST", programs=(p1,))
        assert app.get_program("P1") is not None
        assert app.get_program("P999") is None

    def test_get_dependencies(self):
        deps = (
            JavaDependency(source="A", target="B", dependency_type=JavaDependencyType.METHOD_CALL),
            JavaDependency(source="A", target="C", dependency_type=JavaDependencyType.DATABASE),
        )
        app = JavaApplication(application_id="TEST", dependencies=deps)
        result = app.get_dependencies("A")
        assert len(result) == 2
        assert all(d.source == "A" for d in result)

    def test_get_callers(self):
        deps = (
            JavaDependency(source="A", target="B", dependency_type=JavaDependencyType.METHOD_CALL),
            JavaDependency(source="C", target="B", dependency_type=JavaDependencyType.METHOD_CALL),
        )
        app = JavaApplication(application_id="TEST", dependencies=deps)
        callers = app.get_callers("B")
        assert "A" in callers
        assert "C" in callers

    def test_get_callees(self):
        deps = (
            JavaDependency(source="A", target="B", dependency_type=JavaDependencyType.METHOD_CALL),
            JavaDependency(source="A", target="C", dependency_type=JavaDependencyType.METHOD_CALL),
        )
        app = JavaApplication(application_id="TEST", dependencies=deps)
        callees = app.get_callees("A")
        assert "B" in callees
        assert "C" in callees

    def test_get_all_file_resources(self):
        shared = (JavaFileResource(name="SHARED"),)
        prog = JavaProgram(
            program_id="P1",
            file_resources=(JavaFileResource(name="LOCAL"),),
        )
        app = JavaApplication(
            application_id="TEST",
            programs=(prog,),
            shared_file_resources=shared,
        )
        all_files = app.get_all_file_resources()
        names = [f.name for f in all_files]
        assert "SHARED" in names
        assert "LOCAL" in names

    def test_get_all_database_resources(self):
        shared = (JavaDatabaseResource(name="SHARED_DB"),)
        prog = JavaProgram(
            program_id="P1",
            database_resources=(JavaDatabaseResource(name="LOCAL_DB"),),
        )
        app = JavaApplication(
            application_id="TEST",
            programs=(prog,),
            shared_database_resources=shared,
        )
        all_dbs = app.get_all_database_resources()
        names = [r.name for r in all_dbs]
        assert "SHARED_DB" in names
        assert "LOCAL_DB" in names

    def test_validate_clean(self):
        p = JavaProgram(program_id="P1", java_class=JavaClass(name="P1"))
        app = JavaApplication(application_id="TEST", programs=(p,))
        errors = app.validate()
        assert errors == []

    def test_validate_duplicate_program_id(self):
        p1 = JavaProgram(program_id="P1", java_class=JavaClass(name="P1"))
        p2 = JavaProgram(program_id="P1", java_class=JavaClass(name="P1b"))
        app = JavaApplication(application_id="TEST", programs=(p1, p2))
        errors = app.validate()
        assert any("Duplicate" in e for e in errors)

    def test_validate_unresolved_dependency(self):
        deps = (
            JavaDependency(source="A", target="MISSING", dependency_type=JavaDependencyType.METHOD_CALL),
        )
        app = JavaApplication(application_id="TEST", dependencies=deps)
        errors = app.validate()
        assert any("Unresolved" in e for e in errors)

    def test_validate_program_without_class(self):
        p = JavaProgram(program_id="P1")
        app = JavaApplication(application_id="TEST", programs=(p,))
        errors = app.validate()
        assert any("no Java class" in e for e in errors)


# ============================================================
# Category 8: JavaDependency graph
# ============================================================

class TestJavaDependency:
    def test_method_call_dependency(self):
        d = JavaDependency(
            source="A",
            target="B",
            dependency_type=JavaDependencyType.METHOD_CALL,
        )
        assert d.dependency_type == JavaDependencyType.METHOD_CALL

    def test_database_dependency(self):
        d = JavaDependency(
            source="A",
            target="EMPLOYEE",
            dependency_type=JavaDependencyType.DATABASE,
        )
        assert d.dependency_type == JavaDependencyType.DATABASE

    def test_file_dependency(self):
        d = JavaDependency(
            source="A",
            target="INPUT_FILE",
            dependency_type=JavaDependencyType.FILE,
        )
        assert d.dependency_type == JavaDependencyType.FILE

    def test_transaction_dependency(self):
        d = JavaDependency(
            source="A",
            target="CICS_TRANS",
            dependency_type=JavaDependencyType.TRANSACTION,
        )
        assert d.dependency_type == JavaDependencyType.TRANSACTION


# ============================================================
# Category 9: COBOL → Java type mapping
# ============================================================

class TestPicMapping:
    def test_pic_9_4_to_int(self):
        item = DataItem(name="WS-COUNT", pic_type=PicType.NUMERIC, pic_length=4)
        t = map_pic_to_java_type(item)
        assert t.basic_type == JavaBasicType.INT

    def test_pic_9_12_to_long(self):
        item = DataItem(name="WS-BIG", pic_type=PicType.NUMERIC, pic_length=12)
        t = map_pic_to_java_type(item)
        assert t.basic_type == JavaBasicType.LONG

    def test_pic_x_to_string(self):
        item = DataItem(name="WS-NAME", pic_type=PicType.ALPHANUMERIC, pic_length=20)
        t = map_pic_to_java_type(item)
        assert t.basic_type == JavaBasicType.STRING

    def test_group_item_to_string(self):
        item = DataItem(name="WS-GROUP", pic_type=PicType.ALPHANUMERIC, children=(
            DataItem(name="WS-GROUP-FILLER", pic_type=PicType.ALPHANUMERIC, pic_length=10),
        ))
        t = map_pic_to_java_type(item)
        assert t.basic_type == JavaBasicType.STRING

    def test_default_numeric(self):
        item = DataItem(name="WS-COUNT", pic_type=PicType.NUMERIC, pic_length=4)
        d = map_pic_to_java_default(item)
        assert d == "0"

    def test_default_numeric_with_value(self):
        item = DataItem(name="WS-COUNT", pic_type=PicType.NUMERIC, pic_length=4, value="'100'")
        d = map_pic_to_java_default(item)
        assert d == "100"

    def test_default_alphanumeric(self):
        item = DataItem(name="WS-NAME", pic_type=PicType.ALPHANUMERIC, pic_length=20)
        d = map_pic_to_java_default(item)
        assert d == '""'

    def test_default_alphanumeric_with_value(self):
        item = DataItem(name="WS-NAME", pic_type=PicType.ALPHANUMERIC, pic_length=20, value="'HELLO'")
        d = map_pic_to_java_default(item)
        assert d == '"HELLO"'


# ============================================================
# Category 10: COBOL → Java statement mapping
# ============================================================

class TestStatementMapping:
    def test_move_to_assignment(self):
        stmt = MoveStatement(target="WS-COUNT", source="100")
        java_stmts = map_cobol_statement(stmt)
        assert len(java_stmts) == 1
        assert isinstance(java_stmts[0], JavaAssignment)
        assert java_stmts[0].target == "WS_COUNT"

    def test_add_to_compound_assignment(self):
        stmt = AddStatement(target="WS-TOTAL", source="WS-AMT")
        java_stmts = map_cobol_statement(stmt)
        assert len(java_stmts) == 1
        assert isinstance(java_stmts[0], JavaAssignment)
        assert java_stmts[0].target == "WS_TOTAL"

    def test_display_to_println(self):
        stmt = DisplayStatement(parts=['"HELLO"'], destination="STDOUT")
        java_stmts = map_cobol_statement(stmt)
        assert len(java_stmts) == 1

    def test_display_stderr(self):
        stmt = DisplayStatement(parts=['"ERROR"'], destination="STDERR")
        java_stmts = map_cobol_statement(stmt)
        assert len(java_stmts) == 1

    def test_if_to_java_if(self):
        stmt = IfStatement(
            condition="WS-COUNT > 0",
            then_body=(MoveStatement(target="WS-FLAG", source="'Y'"),),
        )
        java_stmts = map_cobol_statement(stmt)
        assert len(java_stmts) == 1
        assert isinstance(java_stmts[0], JavaIf)

    def test_if_else(self):
        stmt = IfStatement(
            condition="WS-COUNT > 0",
            then_body=(MoveStatement(target="WS-FLAG", source="'Y'"),),
            else_body=(MoveStatement(target="WS-FLAG", source="'N'"),),
        )
        java_stmts = map_cobol_statement(stmt)
        assert len(java_stmts) == 1
        assert isinstance(java_stmts[0], JavaIf)
        assert len(java_stmts[0].else_body) > 0

    def test_perform_to_method_call(self):
        stmt = PerformStatement(paragraph_name="PROCESS-DATA")
        java_stmts = map_cobol_statement(stmt)
        assert len(java_stmts) == 1
        assert isinstance(java_stmts[0], JavaMethodCallStatement)
        assert java_stmts[0].call.method_name == "PROCESS_DATA"

    def test_stop_run_to_return(self):
        stmt = StopRunStatement()
        java_stmts = map_cobol_statement(stmt)
        assert len(java_stmts) == 1
        assert isinstance(java_stmts[0], JavaReturn)

    def test_goto_to_comment(self):
        stmt = GoToStatement(target="EXIT-POINT")
        java_stmts = map_cobol_statement(stmt)
        assert len(java_stmts) == 1
        assert isinstance(java_stmts[0], JavaComment)

    def test_write_produces_real_statement(self):
        """WriteStatement maps to a real Java statement (not a comment).

        A WRITE to a stdout-bound file produces System.out.println.
        The from_field name is used as the argument.
        """
        stmt = WriteStatement(record_name="OUT-REC", file_name="OUTFILE", from_field="WS-DATA")
        java_stmts = map_cobol_statement(stmt)
        assert len(java_stmts) == 1
        # WRITE now generates real code, not a placeholder comment
        assert not isinstance(java_stmts[0], JavaComment), (
            "WRITE must not silently become a comment; it must emit real Java"
        )
        assert isinstance(java_stmts[0], JavaMethodCallStatement), (
            f"Expected JavaMethodCallStatement (println), got: {type(java_stmts[0])}"
        )


    def test_display_with_variable(self):
        stmt = DisplayStatement(parts=["WS-COUNT"], destination="STDOUT")
        java_stmts = map_cobol_statement(stmt)
        assert len(java_stmts) == 1
        assert isinstance(java_stmts[0], JavaMethodCallStatement)

    def test_divide(self):
        stmt = DivideStatement(target="WS-RESULT", source="WS-A", divisor="WS-B")
        java_stmts = map_cobol_statement(stmt)
        assert len(java_stmts) == 1
        assert isinstance(java_stmts[0], JavaAssignment)
        assert java_stmts[0].target == "WS_RESULT"

    def test_move_literal_string(self):
        stmt = MoveStatement(target="WS-NAME", source="'HELLO WORLD'")
        java_stmts = map_cobol_statement(stmt)
        assert len(java_stmts) == 1
        a = java_stmts[0]
        assert isinstance(a, JavaAssignment)
        assert a.target == "WS_NAME"


# ============================================================
# Category 11: COBOL → Java program mapping
# ============================================================

class TestProgramMapping:
    def test_program_to_java(self):
        program = CobolProgram(
            program_id="TEST-PROG",
            working_storage=(
                DataItem(name="WS-COUNT", pic_type=PicType.NUMERIC, pic_length=4, value="'0'"),
                DataItem(name="WS-NAME", pic_type=PicType.ALPHANUMERIC, pic_length=20),
            ),
            paragraphs=(
                Paragraph(name="MAIN-PARA", statements=(
                    MoveStatement(target="WS-COUNT", source="1"),
                    StopRunStatement(),
                ),),
            ),
            file_definitions=(
                FileDefinition(
                    name="INPUT-FILE",
                    container_path="/data/input.dat",
                    record_name="INPUT-REC",
                    organization=FileOrganization.SEQUENTIAL,
                    access_mode=FileAccessMode.SEQUENTIAL,
                ),
            ),
        )
        java_prog = map_cobol_program_to_java(program)

        assert java_prog.program_id == "TEST-PROG"
        assert java_prog.cobol_program_id == "TEST-PROG"
        assert java_prog.java_class is not None
        assert java_prog.java_class.name == "Test_Prog"
        assert len(java_prog.java_class.fields) == 2
        assert len(java_prog.java_class.methods) >= 2  # MAIN_PARA + main

    def test_program_file_resources(self):
        program = CobolProgram(
            program_id="FILE-PROG",
            file_definitions=(
                FileDefinition(
                    name="INFILE",
                    container_path="/data/in.dat",
                    record_name="INFILE-REC",
                    organization=FileOrganization.SEQUENTIAL,
                    access_mode=FileAccessMode.SEQUENTIAL,
                ),
            ),
        )
        java_prog = map_cobol_program_to_java(program)
        assert len(java_prog.file_resources) == 1
        assert java_prog.file_resources[0].name == "INFILE"

    def test_program_with_empty_paragraphs(self):
        program = CobolProgram(program_id="EMPTY")
        java_prog = map_cobol_program_to_java(program)
        assert java_prog.java_class is not None
        assert len(java_prog.java_class.methods) >= 1  # at least main


# ============================================================
# Category 12: COBOL → Java application mapping
# ============================================================

class TestApplicationMapping:
    def test_single_program_app(self):
        prog = CobolProgram(
            program_id="SINGLE",
            paragraphs=(Paragraph(name="MAIN", statements=(StopRunStatement(),)),),
        )
        app = map_cobol_programs_to_application((prog,))
        assert app.application_id == "generated"
        assert len(app.programs) == 1
        assert app.programs[0].program_id == "SINGLE"

    def test_multi_program_app(self):
        p1 = CobolProgram(
            program_id="PROG-A",
            paragraphs=(Paragraph(name="MAIN", statements=(StopRunStatement(),)),),
        )
        p2 = CobolProgram(
            program_id="PROG-B",
            paragraphs=(Paragraph(name="MAIN", statements=(StopRunStatement(),)),),
        )
        app = map_cobol_programs_to_application((p1, p2), application_id="MULTI")
        assert app.application_id == "MULTI"
        assert len(app.programs) == 2

    def test_application_dependencies(self):
        p1 = CobolProgram(
            program_id="PROG-A",
            called_programs=("PROG-B",),
        )
        p2 = CobolProgram(program_id="PROG-B")
        app = map_cobol_programs_to_application((p1, p2))
        assert len(app.dependencies) == 1
        assert app.dependencies[0].source == "PROG-A"
        assert app.dependencies[0].target == "PROG-B"

    def test_application_shared_files(self):
        p1 = CobolProgram(
            program_id="PROG-A",
            file_definitions=(
                FileDefinition(
                    name="SHARED-FILE",
                    container_path="/data/shared.dat",
                    record_name="SHARED-REC",
                    organization=FileOrganization.SEQUENTIAL,
                    access_mode=FileAccessMode.SEQUENTIAL,
                ),
            ),
        )
        p2 = CobolProgram(
            program_id="PROG-B",
            file_definitions=(
                FileDefinition(
                    name="SHARED-FILE",
                    container_path="/data/shared.dat",
                    record_name="SHARED-REC",
                    organization=FileOrganization.SEQUENTIAL,
                    access_mode=FileAccessMode.SEQUENTIAL,
                ),
            ),
        )
        app = map_cobol_programs_to_application((p1, p2))
        all_files = app.get_all_file_resources()
        names = [f.name for f in all_files]
        assert names.count("SHARED-FILE") == 1  # deduplicated


# ============================================================
# Category 13: Negative and edge cases
# ============================================================

class TestNegativeCases:
    def test_empty_application(self):
        app = JavaApplication(application_id="EMPTY")
        assert len(app.programs) == 0
        errors = app.validate()
        assert errors == []

    def test_program_no_working_storage(self):
        prog = CobolProgram(program_id="NO-WS")
        java_prog = map_cobol_program_to_java(prog)
        assert len(java_prog.java_class.fields) == 0

    def test_program_no_paragraphs(self):
        prog = CobolProgram(program_id="NO-PARA")
        java_prog = map_cobol_program_to_java(prog)
        assert len(java_prog.java_class.methods) >= 1  # main method

    def test_application_no_dependencies(self):
        prog = CobolProgram(program_id="SOLO")
        app = map_cobol_programs_to_application((prog,))
        assert len(app.dependencies) == 0

    def test_get_program_missing(self):
        app = JavaApplication(application_id="TEST")
        assert app.get_program("MISSING") is None

    def test_get_dependencies_empty(self):
        app = JavaApplication(application_id="TEST")
        assert app.get_dependencies("ANY") == []

    def test_get_callers_empty(self):
        app = JavaApplication(application_id="TEST")
        assert app.get_callers("ANY") == []

    def test_get_callees_empty(self):
        app = JavaApplication(application_id="TEST")
        assert app.get_callees("ANY") == []


# ============================================================
# Category 14: Determinism (frozen dataclasses)
# ============================================================

class TestDeterminism:
    def test_type_frozen(self):
        t1 = JavaType(basic_type=JavaBasicType.INT)
        t2 = JavaType(basic_type=JavaBasicType.INT)
        assert t1 == t2
        assert hash(t1) == hash(t2)

    def test_literal_frozen(self):
        e1 = JavaLiteral(value="42")
        e2 = JavaLiteral(value="42")
        assert e1 == e2
        assert hash(e1) == hash(e2)

    def test_statement_frozen(self):
        s1 = JavaAssignment(target="x", expression=JavaLiteral(value="1"))
        s2 = JavaAssignment(target="x", expression=JavaLiteral(value="1"))
        assert s1 == s2

    def test_field_frozen(self):
        f1 = JavaField(
            java_type=JavaType(basic_type=JavaBasicType.INT),
            name="x",
        )
        f2 = JavaField(
            java_type=JavaType(basic_type=JavaBasicType.INT),
            name="x",
        )
        assert f1 == f2

    def test_file_resource_frozen(self):
        r1 = JavaFileResource(name="FILE1", access_mode=JavaFileAccessMode.READ)
        r2 = JavaFileResource(name="FILE1", access_mode=JavaFileAccessMode.READ)
        assert r1 == r2

    def test_dependency_frozen(self):
        d1 = JavaDependency(source="A", target="B", dependency_type=JavaDependencyType.METHOD_CALL)
        d2 = JavaDependency(source="A", target="B", dependency_type=JavaDependencyType.METHOD_CALL)
        assert d1 == d2

    def test_application_frozen(self):
        app1 = JavaApplication(application_id="TEST")
        app2 = JavaApplication(application_id="TEST")
        assert app1 == app2

    def test_hashability_of_types(self):
        """Verify all IR types can be hashed (for use in sets/dicts)."""
        types_to_hash = [
            JavaType(basic_type=JavaBasicType.INT),
            JavaLiteral(value="x"),
            JavaVariableRef(name="x"),
            JavaField(java_type=JavaType(basic_type=JavaBasicType.INT), name="x"),
            JavaFileResource(name="F"),
            JavaDatabaseResource(name="T"),
            JavaTransactionBoundary(name="T"),
            JavaDependency(source="A", target="B", dependency_type=JavaDependencyType.METHOD_CALL),
        ]
        for t in types_to_hash:
            _ = hash(t)  # should not raise
