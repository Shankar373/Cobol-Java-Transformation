"""BL-041: file_io generation must render every main-body statement.

The file_io template path previously kept only statements carrying
``.text`` (comments) or ``.expression`` (assignments/returns) and silently
dropped every other statement type — local declarations, method calls
(CALL), IF blocks, and loops — with no diagnostic (house invariant
violation: never drop executable statements).

These tests prove the silent drop first (red), then pin the fix:
render all statement types the generator can express, and fail closed
with ``MISSING_REQUIRED_SEMANTIC`` naming any statement type with no
renderable mapping. Comment-into-loop-body and assignment-into-main-body
placement is preserved as regression coverage.
"""

import pytest

from engine.transformation.java_generator import JavaGenerator
from engine.transformation.java_ir import (
    JavaApplication,
    JavaAssignment,
    JavaBasicType,
    JavaBinaryOp,
    JavaClass,
    JavaComment,
    JavaField,
    JavaFileAccessMode,
    JavaFileResource,
    JavaIf,
    JavaLiteral,
    JavaLocalVarDecl,
    JavaMethod,
    JavaMethodCall,
    JavaMethodCallStatement,
    JavaProgram,
    JavaReturn,
    JavaThrow,
    JavaType,
    JavaVariableRef,
    JavaWhile,
)


def _generate_source(*main_statements: object) -> str:
    """Generate file_io mode source for a main method with the given body."""
    java_class = JavaClass(
        name="FILEPROG",
        fields=(
            JavaField(java_type=JavaType(basic_type=JavaBasicType.INT), name="WS_COUNT"),
            JavaField(java_type=JavaType(basic_type=JavaBasicType.STRING), name="WS_NAME"),
        ),
        methods=(
            JavaMethod(name="main", body_statements=tuple(main_statements)),
        ),
    )
    program = JavaProgram(
        program_id="FILEPROG",
        java_class=java_class,
        file_resources=(
            JavaFileResource(
                name="INPUT-FILE",
                path="/data/input.txt",
                access_mode=JavaFileAccessMode.READ,
            ),
        ),
        generation_mode="file_io",
    )
    application = JavaApplication(application_id="TEST-APP", programs=(program,))
    files = JavaGenerator().generate_from_java(application)
    assert len(files) == 1
    return files[0].source_code


def test_file_io_main_body_renders_local_variable_declaration():
    """A JavaLocalVarDecl in main must appear in the emitted program."""
    decl = JavaLocalVarDecl(
        java_type=JavaType(basic_type=JavaBasicType.INT),
        name="localTotal",
        initializer=JavaLiteral(value="42"),
    )

    source = _generate_source(decl)

    assert "int localTotal = 42;" in source


def test_file_io_main_body_renders_method_call_statement():
    """A CALL mapped to JavaMethodCallStatement must not vanish."""
    call = JavaMethodCallStatement(
        call=JavaMethodCall(
            method_name="auditStep",
            is_static=True,
            class_name="AuditLog",
            arguments=(JavaLiteral(value="REC-READ"),),
        )
    )

    source = _generate_source(call)

    assert 'AuditLog.auditStep("REC-READ");' in source


def test_file_io_main_body_renders_if_statement_with_nested_assignment():
    """IF blocks (and their nested statements) must be emitted."""
    if_stmt = JavaIf(
        condition=JavaBinaryOp(
            left=JavaVariableRef(name="WS_COUNT"),
            operator=">",
            right=JavaLiteral(value="0"),
        ),
        then_body=(
            JavaAssignment(target="WS_COUNT", expression=JavaLiteral(value="1")),
        ),
    )

    source = _generate_source(if_stmt)

    assert "if (WS_COUNT > 0) {" in source
    assert "WS_COUNT = 1;" in source


def test_file_io_main_body_renders_while_loop():
    """Loops (PERFORM VARYING / inline PERFORM UNTIL) must be emitted."""
    loop = JavaWhile(
        condition=JavaBinaryOp(
            left=JavaVariableRef(name="WS_COUNT"),
            operator="<",
            right=JavaLiteral(value="9"),
        ),
        body=(
            JavaAssignment(target="WS_COUNT", expression=JavaLiteral(value="2")),
        ),
    )

    source = _generate_source(loop)

    assert "while (" in source
    assert "WS_COUNT = 2;" in source


def test_file_io_main_body_renders_return_statement_regression():
    """JavaReturn was already rendered (it carries .expression) — keep it."""
    source = _generate_source(JavaReturn())

    assert "return;" in source


def test_file_io_keeps_comments_in_record_loop_and_assignments_in_main_body():
    """Placement regression: comments -> record loop, assignments -> main body."""
    source = _generate_source(
        JavaComment(text="per record step"),
        JavaAssignment(target="WS_COUNT", expression=JavaLiteral(value="1")),
    )

    assert "// per record step" in source
    assert "WS_COUNT = 1;" in source
    # comment sits inside the record loop; the assignment follows the loop
    assert source.index("// per record step") > source.index("for (String[] rec : records)")
    assert source.index("WS_COUNT = 1;") > source.index("// per record step")


def test_file_io_main_body_fails_closed_with_type_name_for_unmapped_statement():
    """A statement type with no mapping must raise, naming the type."""
    with pytest.raises(ValueError, match="MISSING_REQUIRED_SEMANTIC.*JavaThrow"):
        _generate_source(
            JavaThrow(exception_class="IllegalStateException", message="bad record")
        )
