"""Phase 7B.3 — Generic Spring Boot Service Implementation Generation tests.

Tests that service method implementations are generated correctly from
structured Java IR, without COBOL source scanning or domain-specific branching.

Covers:
1. Service method construction
2. Assignment generation
3. Expression generation
4. Condition generation (IF/ELSE)
5. Nested IF
6. Arithmetic
7. Variable declarations
8. Method calls
9. Returns
10. Dependency injection
11. Domain-neutral generation
12. Lexical false positives
13. Mutation matrix
14. Negative tests
15. Determinism
16. Generator isolation
17. Java generator independence
18. Backward compatibility
"""

from __future__ import annotations

import ast
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from engine.transformation.java_ir import (
    JavaApplication,
    JavaAssignment,
    JavaBasicType,
    JavaBinaryOp,
    JavaClass,
    JavaComment,
    JavaDatabaseResource,
    JavaDependency,
    JavaDependencyType,
    JavaField,
    JavaFileResource,
    JavaIf,
    JavaLiteral,
    JavaLocalVarDecl,
    JavaMethod,
    JavaMethodCall,
    JavaMethodCallStatement,
    JavaParameter,
    JavaProgram,
    JavaReturn,
    JavaStatement,
    JavaStringConcat,
    JavaThrow,
    JavaTransactionBoundary,
    JavaType,
    JavaUnaryOp,
    JavaVariableRef,
)
from engine.transformation.java_to_spring_mapping import (
    map_java_application_to_spring_boot,
)
from engine.transformation.spring_boot_generator import (
    SpringBootGenerator,
    compute_project_hash,
)
from engine.transformation.spring_boot_ir import (
    SpringBootApplication,
)


# ============================================================
# Helpers
# ============================================================

def _make_class(
    name: str = "TestClass",
    methods: tuple[JavaMethod, ...] = (),
    fields: tuple[JavaField, ...] = (),
) -> JavaClass:
    return JavaClass(name=name, methods=methods, fields=fields)


def _make_method(
    name: str = "process",
    return_type: JavaType | None = None,
    params: tuple[JavaParameter, ...] = (),
    body: tuple[JavaStatement, ...] = (),
    is_static: bool = False,
) -> JavaMethod:
    if return_type is None:
        return_type = JavaType(basic_type=JavaBasicType.VOID)
    # Accept (JavaType, name) tuples and convert to JavaParameter
    converted_params = []
    for p in params:
        if isinstance(p, JavaParameter):
            converted_params.append(p)
        elif isinstance(p, tuple) and len(p) == 2:
            converted_params.append(JavaParameter(java_type=p[0], name=p[1]))
        else:
            converted_params.append(p)
    return JavaMethod(
        name=name,
        return_type=return_type,
        parameters=tuple(converted_params),
        body_statements=body,
        is_static=is_static,
    )


def _make_program(
    program_id: str = "TESTPGM",
    java_class: JavaClass | None = None,
    file_resources: tuple[JavaFileResource, ...] = (),
    database_resources: tuple[JavaDatabaseResource, ...] = (),
    transaction_boundaries: tuple[JavaTransactionBoundary, ...] = (),
) -> JavaProgram:
    if java_class is None:
        java_class = _make_class()
    return JavaProgram(
        program_id=program_id,
        java_class=java_class,
        file_resources=file_resources,
        database_resources=database_resources,
        transaction_boundaries=transaction_boundaries,
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


# ============================================================
# CATEGORY A: Service Method Construction
# ============================================================

class TestServiceMethodConstruction:

    def test_service_has_methods(self):
        method = _make_method(
            name="processData",
            body=(JavaAssignment(target="result", expression=JavaLiteral(value="42")),),
        )
        cls = _make_class(methods=(method,))
        prog = _make_program(java_class=cls)
        app = _make_application(programs=(prog,))
        files = _generate(app)
        svc = _find_java(files, "Testpgm")
        assert svc is not None
        assert "processData" in svc.source_code
        assert "result = 42;" in svc.source_code

    def test_service_multiple_methods(self):
        m1 = _make_method(name="alpha", body=(JavaReturn(expression=JavaLiteral(value="1")),))
        m2 = _make_method(name="beta", body=(JavaReturn(expression=JavaLiteral(value="2")),))
        cls = _make_class(methods=(m1, m2))
        prog = _make_program(java_class=cls)
        app = _make_application(programs=(prog,))
        files = _generate(app)
        svc = _find_java(files, "Testpgm")
        assert "alpha" in svc.source_code
        assert "beta" in svc.source_code

    def test_main_method_skipped(self):
        main = _make_method(name="main", body=(JavaComment(text="skip"),))
        proc = _make_method(name="process", body=(JavaComment(text="keep"),))
        cls = _make_class(methods=(main, proc))
        prog = _make_program(java_class=cls)
        app = _make_application(programs=(prog,))
        files = _generate(app)
        svc = _find_java(files, "Testpgm")
        assert "process" in svc.source_code
        lines = svc.source_code.split("\n")
        method_defs = [l for l in lines if "public void main(" in l]
        assert len(method_defs) == 0

    def test_method_return_type_preserved(self):
        method = _make_method(
            name="calculate",
            return_type=JavaType(basic_type=JavaBasicType.INT),
            body=(JavaReturn(expression=JavaLiteral(value="0")),),
        )
        cls = _make_class(methods=(method,))
        prog = _make_program(java_class=cls)
        app = _make_application(programs=(prog,))
        files = _generate(app)
        svc = _find_java(files, "Testpgm")
        assert "public int calculate(" in svc.source_code

    def test_method_parameters_preserved(self):
        params = (
            (JavaType(basic_type=JavaBasicType.INT), "x"),
            (JavaType(basic_type=JavaBasicType.STRING), "y"),
        )
        method = _make_method(name="process", params=params, body=())
        cls = _make_class(methods=(method,))
        prog = _make_program(java_class=cls)
        app = _make_application(programs=(prog,))
        files = _generate(app)
        svc = _find_java(files, "Testpgm")
        assert "int x" in svc.source_code
        assert "String y" in svc.source_code


# ============================================================
# CATEGORY B: Assignment Generation
# ============================================================

class TestAssignmentGeneration:

    def test_simple_assignment(self):
        stmt = JavaAssignment(target="x", expression=JavaLiteral(value="10"))
        method = _make_method(body=(stmt,))
        cls = _make_class(methods=(method,))
        prog = _make_program(java_class=cls)
        app = _make_application(programs=(prog,))
        files = _generate(app)
        svc = _find_java(files, "Testpgm")
        assert "x = 10;" in svc.source_code

    def test_variable_ref_assignment(self):
        stmt = JavaAssignment(
            target="y",
            expression=JavaVariableRef(name="x"),
        )
        method = _make_method(body=(stmt,))
        cls = _make_class(methods=(method,))
        prog = _make_program(java_class=cls)
        app = _make_application(programs=(prog,))
        files = _generate(app)
        svc = _find_java(files, "Testpgm")
        assert "y = x;" in svc.source_code

    def test_typed_declaration_assignment(self):
        stmt = JavaAssignment(
            target="count",
            expression=JavaLiteral(value="0"),
            java_type=JavaType(basic_type=JavaBasicType.INT),
        )
        method = _make_method(body=(stmt,))
        cls = _make_class(methods=(method,))
        prog = _make_program(java_class=cls)
        app = _make_application(programs=(prog,))
        files = _generate(app)
        svc = _find_java(files, "Testpgm")
        assert "int count" in svc.source_code

    def test_string_concat_assignment(self):
        stmt = JavaAssignment(
            target="output",
            expression=JavaStringConcat(parts=(
                JavaVariableRef(name="firstName"),
                JavaLiteral(value=" "),
                JavaVariableRef(name="lastName"),
            )),
        )
        method = _make_method(body=(stmt,))
        cls = _make_class(methods=(method,))
        prog = _make_program(java_class=cls)
        app = _make_application(programs=(prog,))
        files = _generate(app)
        svc = _find_java(files, "Testpgm")
        assert "firstName" in svc.source_code
        assert "lastName" in svc.source_code


# ============================================================
# CATEGORY C: Expression Generation
# ============================================================

class TestExpressionGeneration:

    def test_literal_integer(self):
        method = _make_method(body=(
            JavaAssignment(target="x", expression=JavaLiteral(value="42")),
        ))
        cls = _make_class(methods=(method,))
        prog = _make_program(java_class=cls)
        app = _make_application(programs=(prog,))
        files = _generate(app)
        svc = _find_java(files, "Testpgm")
        assert "42" in svc.source_code

    def test_binary_operation(self):
        expr = JavaBinaryOp(
            left=JavaVariableRef(name="a"),
            operator="+",
            right=JavaVariableRef(name="b"),
        )
        method = _make_method(body=(
            JavaAssignment(target="result", expression=expr),
        ))
        cls = _make_class(methods=(method,))
        prog = _make_program(java_class=cls)
        app = _make_application(programs=(prog,))
        files = _generate(app)
        svc = _find_java(files, "Testpgm")
        assert "(a + b)" in svc.source_code

    def test_unary_operation(self):
        expr = JavaUnaryOp(operator="!", operand=JavaVariableRef(name="flag"))
        method = _make_method(body=(
            JavaAssignment(target="result", expression=expr),
        ))
        cls = _make_class(methods=(method,))
        prog = _make_program(java_class=cls)
        app = _make_application(programs=(prog,))
        files = _generate(app)
        svc = _find_java(files, "Testpgm")
        assert "(!flag)" in svc.source_code

    def test_nested_binary_operations(self):
        expr = JavaBinaryOp(
            left=JavaBinaryOp(
                left=JavaVariableRef(name="a"),
                operator="+",
                right=JavaVariableRef(name="b"),
            ),
            operator="*",
            right=JavaVariableRef(name="c"),
        )
        method = _make_method(body=(
            JavaAssignment(target="result", expression=expr),
        ))
        cls = _make_class(methods=(method,))
        prog = _make_program(java_class=cls)
        app = _make_application(programs=(prog,))
        files = _generate(app)
        svc = _find_java(files, "Testpgm")
        assert "((a + b) * c)" in svc.source_code


# ============================================================
# CATEGORY D: Condition Generation
# ============================================================

class TestConditionGeneration:

    def test_simple_if(self):
        stmt = JavaIf(
            condition=JavaBinaryOp(
                left=JavaVariableRef(name="x"),
                operator=">",
                right=JavaLiteral(value="0"),
            ),
            then_body=(JavaAssignment(target="result", expression=JavaLiteral(value="positive")),),
        )
        method = _make_method(body=(stmt,))
        cls = _make_class(methods=(method,))
        prog = _make_program(java_class=cls)
        app = _make_application(programs=(prog,))
        files = _generate(app)
        svc = _find_java(files, "Testpgm")
        assert "if (" in svc.source_code
        assert 'result = "positive"' in svc.source_code

    def test_if_else(self):
        stmt = JavaIf(
            condition=JavaBinaryOp(
                left=JavaVariableRef(name="x"),
                operator="==",
                right=JavaLiteral(value="0"),
            ),
            then_body=(JavaAssignment(target="result", expression=JavaLiteral(value="zero")),),
            else_body=(JavaAssignment(target="result", expression=JavaLiteral(value="nonzero")),),
        )
        method = _make_method(body=(stmt,))
        cls = _make_class(methods=(method,))
        prog = _make_program(java_class=cls)
        app = _make_application(programs=(prog,))
        files = _generate(app)
        svc = _find_java(files, "Testpgm")
        assert "if (" in svc.source_code
        assert "} else {" in svc.source_code
        assert 'result = "zero"' in svc.source_code
        assert 'result = "nonzero"' in svc.source_code

    def test_multiple_conditions(self):
        stmt = JavaIf(
            condition=JavaBinaryOp(
                left=JavaBinaryOp(
                    left=JavaVariableRef(name="a"),
                    operator=">",
                    right=JavaLiteral(value="0"),
                ),
                operator="&&",
                right=JavaBinaryOp(
                    left=JavaVariableRef(name="b"),
                    operator="<",
                    right=JavaLiteral(value="100"),
                ),
            ),
            then_body=(JavaAssignment(target="ok", expression=JavaLiteral(value="true")),),
        )
        method = _make_method(body=(stmt,))
        cls = _make_class(methods=(method,))
        prog = _make_program(java_class=cls)
        app = _make_application(programs=(prog,))
        files = _generate(app)
        svc = _find_java(files, "Testpgm")
        assert "&&" in svc.source_code


# ============================================================
# CATEGORY E: Nested IF
# ============================================================

class TestNestedIf:

    def test_nested_if_preserved(self):
        inner_if = JavaIf(
            condition=JavaBinaryOp(
                left=JavaVariableRef(name="b"),
                operator="==",
                right=JavaLiteral(value="1"),
            ),
            then_body=(JavaAssignment(target="result", expression=JavaLiteral(value="inner-true")),),
            else_body=(JavaAssignment(target="result", expression=JavaLiteral(value="inner-false")),),
        )
        outer_if = JavaIf(
            condition=JavaBinaryOp(
                left=JavaVariableRef(name="a"),
                operator="==",
                right=JavaLiteral(value="1"),
            ),
            then_body=(inner_if,),
            else_body=(JavaAssignment(target="result", expression=JavaLiteral(value="outer-false")),),
        )
        method = _make_method(body=(outer_if,))
        cls = _make_class(methods=(method,))
        prog = _make_program(java_class=cls)
        app = _make_application(programs=(prog,))
        files = _generate(app)
        svc = _find_java(files, "Testpgm")
        assert "if (" in svc.source_code
        assert 'result = "inner-true"' in svc.source_code
        assert 'result = "inner-false"' in svc.source_code
        assert 'result = "outer-false"' in svc.source_code

    def test_triple_nested_if(self):
        level3 = JavaIf(
            condition=JavaVariableRef(name="c"),
            then_body=(JavaAssignment(target="depth", expression=JavaLiteral(value="3")),),
        )
        level2 = JavaIf(
            condition=JavaVariableRef(name="b"),
            then_body=(level3,),
        )
        level1 = JavaIf(
            condition=JavaVariableRef(name="a"),
            then_body=(level2,),
        )
        method = _make_method(body=(level1,))
        cls = _make_class(methods=(method,))
        prog = _make_program(java_class=cls)
        app = _make_application(programs=(prog,))
        files = _generate(app)
        svc = _find_java(files, "Testpgm")
        assert "if (a)" in svc.source_code
        assert "if (b)" in svc.source_code
        assert "if (c)" in svc.source_code
        assert "depth = 3;" in svc.source_code


# ============================================================
# CATEGORY F: Arithmetic Generation
# ============================================================

class TestArithmeticGeneration:

    def test_addition(self):
        expr = JavaBinaryOp(
            left=JavaVariableRef(name="total"),
            operator="+",
            right=JavaVariableRef(name="amount"),
        )
        method = _make_method(body=(
            JavaAssignment(target="total", expression=expr),
        ))
        cls = _make_class(methods=(method,))
        prog = _make_program(java_class=cls)
        app = _make_application(programs=(prog,))
        files = _generate(app)
        svc = _find_java(files, "Testpgm")
        assert "(total + amount)" in svc.source_code

    def test_subtraction(self):
        expr = JavaBinaryOp(
            left=JavaVariableRef(name="balance"),
            operator="-",
            right=JavaVariableRef(name="debit"),
        )
        method = _make_method(body=(
            JavaAssignment(target="balance", expression=expr),
        ))
        cls = _make_class(methods=(method,))
        prog = _make_program(java_class=cls)
        app = _make_application(programs=(prog,))
        files = _generate(app)
        svc = _find_java(files, "Testpgm")
        assert "(balance - debit)" in svc.source_code

    def test_multiplication(self):
        expr = JavaBinaryOp(
            left=JavaVariableRef(name="qty"),
            operator="*",
            right=JavaVariableRef(name="price"),
        )
        method = _make_method(body=(
            JavaAssignment(target="total", expression=expr),
        ))
        cls = _make_class(methods=(method,))
        prog = _make_program(java_class=cls)
        app = _make_application(programs=(prog,))
        files = _generate(app)
        svc = _find_java(files, "Testpgm")
        assert "(qty * price)" in svc.source_code

    def test_division(self):
        expr = JavaBinaryOp(
            left=JavaVariableRef(name="sum"),
            operator="/",
            right=JavaVariableRef(name="count"),
        )
        method = _make_method(body=(
            JavaAssignment(target="avg", expression=expr),
        ))
        cls = _make_class(methods=(method,))
        prog = _make_program(java_class=cls)
        app = _make_application(programs=(prog,))
        files = _generate(app)
        svc = _find_java(files, "Testpgm")
        assert "(sum / count)" in svc.source_code


# ============================================================
# CATEGORY G: Variable Declarations
# ============================================================

class TestVariableDeclarations:

    def test_int_declaration(self):
        stmt = JavaLocalVarDecl(
            java_type=JavaType(basic_type=JavaBasicType.INT),
            name="counter",
            initializer=JavaLiteral(value="0"),
        )
        method = _make_method(body=(stmt,))
        cls = _make_class(methods=(method,))
        prog = _make_program(java_class=cls)
        app = _make_application(programs=(prog,))
        files = _generate(app)
        svc = _find_java(files, "Testpgm")
        assert "int counter" in svc.source_code

    def test_string_declaration(self):
        stmt = JavaLocalVarDecl(
            java_type=JavaType(basic_type=JavaBasicType.STRING),
            name="name",
        )
        method = _make_method(body=(stmt,))
        cls = _make_class(methods=(method,))
        prog = _make_program(java_class=cls)
        app = _make_application(programs=(prog,))
        files = _generate(app)
        svc = _find_java(files, "Testpgm")
        assert "String name;" in svc.source_code


# ============================================================
# CATEGORY H: Method Calls
# ============================================================

class TestMethodCalls:

    def test_instance_method_call(self):
        call = JavaMethodCall(
            object_ref=JavaVariableRef(name="repository"),
            method_name="findById",
            arguments=(JavaVariableRef(name="id"),),
        )
        method = _make_method(body=(JavaMethodCallStatement(call=call),))
        cls = _make_class(methods=(method,))
        prog = _make_program(java_class=cls)
        app = _make_application(programs=(prog,))
        files = _generate(app)
        svc = _find_java(files, "Testpgm")
        assert "repository.findById(id)" in svc.source_code

    def test_static_method_call(self):
        call = JavaMethodCall(
            method_name="valueOf",
            arguments=(JavaLiteral(value="42"),),
            is_static=True,
            class_name="Integer",
        )
        method = _make_method(body=(JavaMethodCallStatement(call=call),))
        cls = _make_class(methods=(method,))
        prog = _make_program(java_class=cls)
        app = _make_application(programs=(prog,))
        files = _generate(app)
        svc = _find_java(files, "Testpgm")
        assert "Integer.valueOf(42)" in svc.source_code

    def test_method_call_as_expression(self):
        call = JavaMethodCall(
            object_ref=JavaVariableRef(name="service"),
            method_name="compute",
            arguments=(),
        )
        method = _make_method(body=(
            JavaAssignment(target="result", expression=call),
        ))
        cls = _make_class(methods=(method,))
        prog = _make_program(java_class=cls)
        app = _make_application(programs=(prog,))
        files = _generate(app)
        svc = _find_java(files, "Testpgm")
        assert "result = service.compute()" in svc.source_code


# ============================================================
# CATEGORY I: Return Semantics
# ============================================================

class TestReturnSemantics:

    def test_return_value(self):
        method = _make_method(
            name="getValue",
            return_type=JavaType(basic_type=JavaBasicType.INT),
            body=(JavaReturn(expression=JavaLiteral(value="42")),),
        )
        cls = _make_class(methods=(method,))
        prog = _make_program(java_class=cls)
        app = _make_application(programs=(prog,))
        files = _generate(app)
        svc = _find_java(files, "Testpgm")
        assert "return 42;" in svc.source_code

    def test_return_void(self):
        method = _make_method(
            name="doWork",
            return_type=JavaType(basic_type=JavaBasicType.VOID),
            body=(JavaReturn(),),
        )
        cls = _make_class(methods=(method,))
        prog = _make_program(java_class=cls)
        app = _make_application(programs=(prog,))
        files = _generate(app)
        svc = _find_java(files, "Testpgm")
        assert "return;" in svc.source_code


# ============================================================
# CATEGORY J: Dependency Injection
# ============================================================

class TestDependencyInjection:

    def test_constructor_injection(self):
        prog_a = _make_program(program_id="PGM-A")
        prog_b = _make_program(program_id="PGM-B")
        deps = (JavaDependency(
            source="PGM-A", target="PGM-B",
            dependency_type=JavaDependencyType.METHOD_CALL,
        ),)
        app = _make_application(
            application_id="DI-TEST",
            programs=(prog_a, prog_b),
            dependencies=deps,
        )
        files = _generate(app)
        svc_a = _find_java(files, "PgmA")
        assert svc_a is not None
        assert "private final PgmB pgmB" in svc_a.source_code
        assert "public PgmA(PgmB pgmB)" in svc_a.source_code
        assert "this.pgmB = pgmB" in svc_a.source_code

    def test_no_dependency_no_constructor_params(self):
        prog = _make_program(program_id="SOLO")
        app = _make_application(programs=(prog,))
        files = _generate(app)
        svc = _find_java(files, "Solo")
        assert "public Solo()" in svc.source_code

    def test_multiple_dependencies(self):
        prog_a = _make_program(program_id="A")
        prog_b = _make_program(program_id="B")
        prog_c = _make_program(program_id="C")
        deps = (
            JavaDependency(source="A", target="B", dependency_type=JavaDependencyType.METHOD_CALL),
            JavaDependency(source="A", target="C", dependency_type=JavaDependencyType.METHOD_CALL),
        )
        app = _make_application(programs=(prog_a, prog_b, prog_c), dependencies=deps)
        files = _generate(app)
        svc = _find_java(files, "A")
        assert "private final B b" in svc.source_code
        assert "private final C c" in svc.source_code
        assert "public A(B b, C c)" in svc.source_code


# ============================================================
# CATEGORY K: Domain-Neutral Generation
# ============================================================

class TestDomainNeutralGeneration:

    def _make_app(self, app_id, prog_id, field_names):
        fields = tuple(
            JavaField(
                java_type=JavaType(basic_type=JavaBasicType.STRING),
                name=fn,
                is_static=False,
            )
            for fn in field_names
        )
        cls = _make_class(fields=fields)
        prog = _make_program(program_id=prog_id, java_class=cls)
        return _make_application(application_id=app_id, programs=(prog,))

    def test_alpha_application(self):
        app = self._make_app("ALPHA-APP", "ALPHA-PGM", ["code", "result", "value"])
        files = _generate(app)
        svc = _find_java(files, "AlphaPgm")
        assert svc is not None
        assert "@Service" in svc.source_code

    def test_beta_application(self):
        app = self._make_app("BETA-APP", "BETA-PGM", ["key", "output", "quantity"])
        files = _generate(app)
        svc = _find_java(files, "BetaPgm")
        assert svc is not None
        assert "@Service" in svc.source_code

    def test_gamma_application(self):
        app = self._make_app("GAMMA-APP", "GAMMA-PGM", ["input", "state", "count"])
        files = _generate(app)
        svc = _find_java(files, "GammaPgm")
        assert svc is not None
        assert "@Service" in svc.source_code

    def test_structural_equivalence(self):
        apps = [
            self._make_app("A-APP", "A-PGM", ["x", "y"]),
            self._make_app("B-APP", "B-PGM", ["p", "q"]),
            self._make_app("C-APP", "C-PGM", ["m", "n"]),
        ]
        counts = []
        for app in apps:
            files = _generate(app)
            counts.append(len(files))
        assert counts[0] == counts[1] == counts[2]


# ============================================================
# CATEGORY L: Lexical False Positives
# ============================================================

class TestLexicalFalsePositives:

    def test_claim_keyword_no_special_behavior(self):
        method = _make_method(
            name="processClaim",
            body=(JavaAssignment(target="claimResult", expression=JavaLiteral(value="OK")),),
        )
        cls = _make_class(
            name="ClaimService",
            methods=(method,),
            fields=(JavaField(
                java_type=JavaType(basic_type=JavaBasicType.STRING),
                name="claimStatus",
                is_static=False,
            ),),
        )
        prog = _make_program(program_id="CLAIM-PGM", java_class=cls)
        app = _make_application(programs=(prog,))
        files = _generate(app)
        svc = _find_java(files, "ClaimPgm")
        assert svc is not None
        assert 'claimResult = "OK"' in svc.source_code

    def test_payment_keyword_no_special_behavior(self):
        method = _make_method(
            name="processPayment",
            body=(JavaAssignment(target="paymentStatus", expression=JavaLiteral(value="DONE")),),
        )
        cls = _make_class(name="PaymentService", methods=(method,))
        prog = _make_program(program_id="PAYMENT-PGM", java_class=cls)
        app = _make_application(programs=(prog,))
        files = _generate(app)
        svc = _find_java(files, "PaymentPgm")
        assert svc is not None

    def test_order_keyword_no_special_behavior(self):
        method = _make_method(
            name="processOrder",
            body=(JavaAssignment(target="orderStatus", expression=JavaLiteral(value="OK")),),
        )
        cls = _make_class(name="OrderService", methods=(method,))
        prog = _make_program(program_id="ORDER-PGM", java_class=cls)
        app = _make_application(programs=(prog,))
        files = _generate(app)
        svc = _find_java(files, "OrderPgm")
        assert svc is not None


# ============================================================
# CATEGORY M: Mutation Matrix
# ============================================================

class TestMutationMatrix:

    def _base_app(self):
        method = _make_method(
            name="process",
            body=(
                JavaAssignment(target="x", expression=JavaLiteral(value="1")),
                JavaIf(
                    condition=JavaBinaryOp(
                        left=JavaVariableRef(name="x"),
                        operator="==",
                        right=JavaLiteral(value="1"),
                    ),
                    then_body=(JavaAssignment(target="y", expression=JavaLiteral(value="yes")),),
                ),
            ),
        )
        cls = _make_class(methods=(method,))
        prog = _make_program(java_class=cls)
        return _make_application(programs=(prog,))

    def _base_hash(self):
        files = _generate(self._base_app())
        return compute_project_hash(files)

    def test_change_literal(self):
        base_hash = self._base_hash()
        method = _make_method(
            name="process",
            body=(
                JavaAssignment(target="x", expression=JavaLiteral(value="999")),
                JavaIf(
                    condition=JavaBinaryOp(
                        left=JavaVariableRef(name="x"),
                        operator="==",
                        right=JavaLiteral(value="1"),
                    ),
                    then_body=(JavaAssignment(target="y", expression=JavaLiteral(value="yes")),),
                ),
            ),
        )
        cls = _make_class(methods=(method,))
        prog = _make_program(java_class=cls)
        app = _make_application(programs=(prog,))
        files = _generate(app)
        assert compute_project_hash(files) != base_hash

    def test_change_operator(self):
        base_hash = self._base_hash()
        method = _make_method(
            name="process",
            body=(
                JavaAssignment(target="x", expression=JavaLiteral(value="1")),
                JavaIf(
                    condition=JavaBinaryOp(
                        left=JavaVariableRef(name="x"),
                        operator="!=",
                        right=JavaLiteral(value="1"),
                    ),
                    then_body=(JavaAssignment(target="y", expression=JavaLiteral(value="yes")),),
                ),
            ),
        )
        cls = _make_class(methods=(method,))
        prog = _make_program(java_class=cls)
        app = _make_application(programs=(prog,))
        files = _generate(app)
        assert compute_project_hash(files) != base_hash

    def test_add_else(self):
        base_hash = self._base_hash()
        method = _make_method(
            name="process",
            body=(
                JavaAssignment(target="x", expression=JavaLiteral(value="1")),
                JavaIf(
                    condition=JavaBinaryOp(
                        left=JavaVariableRef(name="x"),
                        operator="==",
                        right=JavaLiteral(value="1"),
                    ),
                    then_body=(JavaAssignment(target="y", expression=JavaLiteral(value="yes")),),
                    else_body=(JavaAssignment(target="y", expression=JavaLiteral(value="no")),),
                ),
            ),
        )
        cls = _make_class(methods=(method,))
        prog = _make_program(java_class=cls)
        app = _make_application(programs=(prog,))
        files = _generate(app)
        assert compute_project_hash(files) != base_hash

    def test_add_method(self):
        base_hash = self._base_hash()
        method1 = _make_method(
            name="process",
            body=(
                JavaAssignment(target="x", expression=JavaLiteral(value="1")),
                JavaIf(
                    condition=JavaBinaryOp(
                        left=JavaVariableRef(name="x"),
                        operator="==",
                        right=JavaLiteral(value="1"),
                    ),
                    then_body=(JavaAssignment(target="y", expression=JavaLiteral(value="yes")),),
                ),
            ),
        )
        method2 = _make_method(
            name="extra",
            body=(JavaReturn(expression=JavaLiteral(value="42")),),
        )
        cls = _make_class(methods=(method1, method2))
        prog = _make_program(java_class=cls)
        app = _make_application(programs=(prog,))
        files = _generate(app)
        assert compute_project_hash(files) != base_hash

    def test_change_condition_operand(self):
        base_hash = self._base_hash()
        method = _make_method(
            name="process",
            body=(
                JavaAssignment(target="x", expression=JavaLiteral(value="1")),
                JavaIf(
                    condition=JavaBinaryOp(
                        left=JavaVariableRef(name="x"),
                        operator="==",
                        right=JavaLiteral(value="2"),
                    ),
                    then_body=(JavaAssignment(target="y", expression=JavaLiteral(value="yes")),),
                ),
            ),
        )
        cls = _make_class(methods=(method,))
        prog = _make_program(java_class=cls)
        app = _make_application(programs=(prog,))
        files = _generate(app)
        assert compute_project_hash(files) != base_hash


# ============================================================
# CATEGORY N: Negative Tests
# ============================================================

class TestNegativeTests:

    def test_missing_method_body_generates_empty(self):
        method = _make_method(name="empty", body=())
        cls = _make_class(methods=(method,))
        prog = _make_program(java_class=cls)
        app = _make_application(programs=(prog,))
        files = _generate(app)
        svc = _find_java(files, "Testpgm")
        assert "public void empty()" in svc.source_code

    def test_throw_statement(self):
        stmt = JavaThrow(exception_class="RuntimeException", message="not found")
        method = _make_method(body=(stmt,))
        cls = _make_class(methods=(method,))
        prog = _make_program(java_class=cls)
        app = _make_application(programs=(prog,))
        files = _generate(app)
        svc = _find_java(files, "Testpgm")
        assert 'throw new RuntimeException("not found")' in svc.source_code

    def test_empty_application_generates_minimal_project(self):
        app = _make_application(application_id="EMPTY", programs=())
        files = _generate(app)
        pom = _find_java(files, "pom.xml")
        assert pom is not None
        assert "spring-boot-starter-parent" in pom.source_code


# ============================================================
# CATEGORY O: Determinism
# ============================================================

class TestDeterminism:

    def test_same_input_same_files(self):
        method = _make_method(
            name="process",
            body=(JavaAssignment(target="x", expression=JavaLiteral(value="1")),),
        )
        cls = _make_class(methods=(method,))
        prog = _make_program(java_class=cls)
        app = _make_application(programs=(prog,))
        files1 = _generate(app)
        files2 = _generate(app)
        assert len(files1) == len(files2)
        for f1, f2 in zip(files1, files2):
            assert f1.path == f2.path
            assert f1.source_code == f2.source_code

    def test_same_input_same_hash(self):
        method = _make_method(
            name="process",
            body=(JavaAssignment(target="x", expression=JavaLiteral(value="1")),),
        )
        cls = _make_class(methods=(method,))
        prog = _make_program(java_class=cls)
        app = _make_application(programs=(prog,))
        hash1 = compute_project_hash(_generate(app))
        hash2 = compute_project_hash(_generate(app))
        assert hash1 == hash2


# ============================================================
# CATEGORY P: Generator Isolation
# ============================================================

class TestGeneratorIsolation:

    def test_spring_boot_generator_no_cobol_imports(self):
        with open("engine/transformation/spring_boot_generator.py") as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and ("cobol" in node.module.lower()
                                    or "parser" in node.module.lower()):
                    assert False, f"COBOL import found: {node.module}"

    def test_mapper_no_cobol_imports(self):
        with open("engine/transformation/java_to_spring_mapping.py") as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and ("cobol" in node.module.lower()
                                    or "parser" in node.module.lower()):
                    assert False, f"COBOL import found: {node.module}"

    def test_spring_boot_ir_no_cobol_imports(self):
        with open("engine/transformation/spring_boot_ir.py") as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and ("cobol" in node.module.lower()
                                    or "parser" in node.module.lower()):
                    assert False, f"COBOL import found: {node.module}"


# ============================================================
# CATEGORY Q: Java Generator Independence
# ============================================================

class TestJavaGeneratorIndependence:

    def test_java_generator_still_works(self):
        from engine.transformation.java_generator import JavaGenerator
        method = _make_method(
            name="process",
            body=(JavaAssignment(target="x", expression=JavaLiteral(value="1")),),
        )
        cls = _make_class(methods=(method,))
        prog = _make_program(java_class=cls)
        app = _make_application(programs=(prog,))
        gen = JavaGenerator()
        files = gen.generate_from_java(app)
        assert len(files) >= 1
        java_files = [f for f in files if f.filename.endswith(".java")]
        assert len(java_files) >= 1


# ============================================================
# CATEGORY R: Backward Compatibility
# ============================================================

class TestBackwardCompatibility:

    def test_empty_service_methods(self):
        """Service with no methods still generates correctly."""
        cls = _make_class()
        prog = _make_program(java_class=cls)
        app = _make_application(programs=(prog,))
        files = _generate(app)
        svc = _find_java(files, "Testpgm")
        assert svc is not None
        assert "@Service" in svc.source_code
        assert "public Testpgm()" in svc.source_code

    def test_service_with_only_main_skipped(self):
        """Service where only method is main gets empty body."""
        main = _make_method(name="main", body=())
        cls = _make_class(methods=(main,))
        prog = _make_program(java_class=cls)
        app = _make_application(programs=(prog,))
        files = _generate(app)
        svc = _find_java(files, "Testpgm")
        assert svc is not None
        assert "public Testpgm()" in svc.source_code
        lines = svc.source_code.split("\n")
        method_defs = [l for l in lines if "public void main(" in l]
        assert len(method_defs) == 0

    def test_transactional_preserved(self):
        """Transactional annotation preserved with methods."""
        method = _make_method(
            name="work",
            body=(JavaAssignment(target="x", expression=JavaLiteral(value="1")),),
        )
        cls = _make_class(methods=(method,))
        prog = _make_program(
            java_class=cls,
            transaction_boundaries=(JavaTransactionBoundary(name="TX1"),),
        )
        app = _make_application(programs=(prog,))
        files = _generate(app)
        svc = _find_java(files, "Testpgm")
        assert "@Transactional" in svc.source_code
        assert "work" in svc.source_code
