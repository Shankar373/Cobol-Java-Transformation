"""Focused regression tests for Numeric P0 N1+N2: decimal PIC parsing/type and input conversion."""

from pathlib import Path

from engine.transformation.cobol_parser import CobolParser
from engine.transformation.cobol_to_java_mapping import (
    _map_cobol_expression_to_java,
    map_cobol_expr_to_java,
    map_cobol_program_to_java,
    map_cobol_statement,
    map_pic_to_java_type,
)
from engine.transformation.ir import DataItem, InputRecordMapping, Literal, PicType, ReadStatement
from engine.transformation.java_generator import JavaGenerator
from engine.transformation.java_ir import (
    JavaApplication,
    JavaAssignment,
    JavaBasicType,
    JavaClass,
    JavaField,
    JavaFileAccessMode,
    JavaFileResource,
    JavaIf,
    JavaLiteral,
    JavaProgram,
    JavaType,
)


def _find_double_parse(assignments):
    for assignment in assignments:
        if not isinstance(assignment, JavaAssignment):
            continue
        expression = assignment.expression
        if (
            getattr(expression, "class_name", "") == "Double"
            and expression.method_name == "parseDouble"
        ):
            return assignment
    return None


def test_decimal_pic_maps_to_double():
    item = DataItem(
        name="WS-AMOUNT",
        pic_type=PicType.NUMERIC,
        pic_length=5,
        decimal_places=2,
    )

    java_type = map_pic_to_java_type(item)

    assert java_type.basic_type == JavaBasicType.DOUBLE


def test_real_comp3_fixture_preserves_decimal_metadata_and_java_type():
    source = Path("fixtures/workload-comp3/cobol/MAIN.cob").read_text(encoding="utf-8")
    program = CobolParser().parse(source)

    expected = {
        "WS-PACKED-1": (7, 2, "12345.67"),
        "WS-PACKED-2": (7, 2, "-987.65"),
        "WS-PACKED-3": (6, 2, "100.00"),
        "WS-RESULT": (9, 2, "0"),
    }
    for name, (width, decimals, value) in expected.items():
        item = next(item for item in program.working_storage if item.name == name)
        assert item.pic_length == width
        assert item.decimal_places == decimals
        assert item.value == value
        assert map_pic_to_java_type(item).basic_type == JavaBasicType.DOUBLE

    java_program = map_cobol_program_to_java(program)
    fields = {field.name: field for field in java_program.java_class.fields}
    assert all(
        fields[name.replace("-", "_")].java_type.basic_type == JavaBasicType.DOUBLE
        for name in expected
    )


def test_file_section_decimal_pic_preserves_metadata_and_read_uses_double_parse():
    cobol = """
>>SOURCE FORMAT FREE
IDENTIFICATION DIVISION.
PROGRAM-ID. DECIMAL-READ.
ENVIRONMENT DIVISION.
INPUT-OUTPUT SECTION.
FILE-CONTROL.
    SELECT INPUT-FILE ASSIGN TO "/tmp/input.dat"
        ORGANIZATION IS LINE SEQUENTIAL.
DATA DIVISION.
FILE SECTION.
FD INPUT-FILE.
01 INPUT-REC.
   05 INPUT-AMOUNT PIC S9(5)V99 COMP-3.
WORKING-STORAGE SECTION.
01 WS-AMOUNT PIC S9(5)V99 COMP-3 VALUE 0.
PROCEDURE DIVISION.
MAIN.
    STOP RUN.
"""

    program = CobolParser().parse(cobol)
    record_amount = next(
        item
        for fd in program.file_definitions
        for item in fd.record_items
        if item.name == "INPUT-AMOUNT"
    )
    assert record_amount.pic_length == 7
    assert record_amount.decimal_places == 2

    read_stmt = ReadStatement(
        file_name="INPUT-FILE",
        record_name="INPUT-REC",
        read_next=True,
        into_field="WS-AMOUNT",
    )
    mapped = map_cobol_statement(read_stmt, program)
    read_if = next(stmt for stmt in mapped if isinstance(stmt, JavaIf))
    assignments = [stmt for stmt in read_if.then_body if isinstance(stmt, JavaAssignment)]
    assert _find_double_parse(assignments) is not None


def test_ir_file_input_converts_decimal_record_field_with_double_parse():
    java_program = JavaProgram(
        program_id="DECIMAL-INPUT",
        java_class=JavaClass(
            name="Decimal_Input",
            fields=(
                JavaField(
                    name="WS_AMOUNT",
                    java_type=JavaType(basic_type=JavaBasicType.DOUBLE),
                ),
                JavaField(
                    name="WS_COUNT",
                    java_type=JavaType(basic_type=JavaBasicType.INT),
                ),
            ),
        ),
        file_resources=(
            JavaFileResource(
                name="INPUT-FILE",
                path="/tmp/input.dat",
                access_mode=JavaFileAccessMode.READ,
            ),
        ),
        generation_mode="file_io",
    )
    application = JavaApplication(
        application_id="DECIMAL-INPUT",
        programs=(java_program,),
    )

    source = JavaGenerator().generate_from_java(application)[0].source_code

    assert "Double.parseDouble(rec[0].trim())" in source
    assert "Integer.parseInt(rec[1].trim())" in source


def test_ir_decision_input_assignment_converts_decimal_field_with_double_parse():
    generator = JavaGenerator()
    java_program = JavaProgram(
        program_id="DECIMAL-DECISION",
        java_class=JavaClass(
            name="Decimal_Decision",
            fields=(
                JavaField(
                    name="WS_AMOUNT",
                    java_type=JavaType(basic_type=JavaBasicType.DOUBLE),
                ),
            ),
        ),
        input_record_fields=("WS_AMOUNT",),
    )
    source = generator._generate_field_assignments_from_ir(
        java_program, java_program.java_class
    )

    assert "Double.parseDouble(rec[0].trim())" in source


def test_decimal_expression_literals_map_to_double():
    for value in ("3.14", "-0.25"):
        java_expr = map_cobol_expr_to_java(value)
        assert java_expr.java_type.basic_type == JavaBasicType.DOUBLE


def test_structured_decimal_literal_maps_to_double():
    java_expr = _map_cobol_expression_to_java(
        Literal(value="12.50", is_numeric=True)
    )
    assert java_expr.java_type.basic_type == JavaBasicType.DOUBLE


def test_decimal_literal_type_is_preserved_through_active_file_io_generation():
    java_program = JavaProgram(
        program_id="DECIMAL-GENERATION",
        java_class=JavaClass(
            name="Decimal_Generation",
            fields=(
                JavaField(
                    name="WS_AMOUNT",
                    java_type=JavaType(basic_type=JavaBasicType.DOUBLE),
                    initializer=JavaLiteral(value="12.50"),
                ),
            ),
        ),
        file_resources=(
            JavaFileResource(
                name="INPUT-FILE",
                path="/tmp/input.dat",
                access_mode=JavaFileAccessMode.READ,
            ),
        ),
        generation_mode="file_io",
    )

    source = JavaGenerator().generate_from_java(
        JavaApplication(application_id="DECIMAL-GENERATION", programs=(java_program,))
    )[0].source_code

    assert "static double WS_AMOUNT = 12.50;" in source
    assert "WS_AMOUNT = Double.parseDouble(rec[0].trim());" in source


def test_signed_integer_pic_is_still_parsed_without_decimal_places():
    cobol = """
>>SOURCE FORMAT FREE
IDENTIFICATION DIVISION.
PROGRAM-ID. SIGNED-INT.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-COUNT PIC S9(4) COMP-3 VALUE -12.
PROCEDURE DIVISION.
MAIN.
    STOP RUN.
"""
    item = CobolParser().parse(cobol).working_storage[0]
    assert item.pic_type == PicType.NUMERIC
    assert item.pic_length == 4
    assert item.decimal_places == 0
    assert map_pic_to_java_type(item).basic_type == JavaBasicType.INT
    
def test_file_section_decimal_mapping_is_used_by_generic_file_io_generator():
    cobol = """\
>>SOURCE FORMAT FREE
IDENTIFICATION DIVISION.
PROGRAM-ID. FILE-DECIMAL.
ENVIRONMENT DIVISION.
INPUT-OUTPUT SECTION.
FILE-CONTROL.
    SELECT INPUT-FILE ASSIGN TO "/tmp/input.dat"
        ORGANIZATION IS LINE SEQUENTIAL.
DATA DIVISION.
FILE SECTION.
FD INPUT-FILE.
01 INPUT-REC.
   05 INPUT-AMOUNT PIC S9(5)V99 COMP-3.
   05 INPUT-LONG PIC S9(10) COMP-3.
WORKING-STORAGE SECTION.
01 WS-DUMMY PIC X VALUE SPACE.
PROCEDURE DIVISION.
MAIN.
    STOP RUN.
"""
    generator = JavaGenerator()
    program = CobolParser().parse(cobol)
    mapping = InputRecordMapping(
        record_name="INPUT-REC",
        file_name="INPUT-FILE",
        delimiter="|",
        fields=("INPUT-AMOUNT", "INPUT-LONG"),
    )
    declarations = generator._gen_io_variable_declarations(program, (mapping,))
    parsing = generator._gen_unstring_parsing_java(mapping, program)
    assert "static double INPUT_AMOUNT = 0;" in declarations
    assert "static long INPUT_LONG = 0;" in declarations
    assert "INPUT_AMOUNT = Double.parseDouble(rec[0].trim());" in parsing
    assert "INPUT_LONG = Long.parseLong(rec[1].trim());" in parsing
