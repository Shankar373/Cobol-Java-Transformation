"""Focused regression tests for decimal PIC type preservation (Numeric P0 N1)."""

from engine.transformation.cobol_parser import CobolParser
from engine.transformation.cobol_to_java_mapping import (
    map_cobol_program_to_java,
    map_pic_to_java_type,
)
from engine.transformation.ir import DataItem, PicType
from engine.transformation.java_generator import JavaGenerator
from engine.transformation.java_ir import JavaApplication, JavaBasicType


def test_decimal_pic_maps_to_double():
    item = DataItem(
        name="WS-AMOUNT",
        pic_type=PicType.NUMERIC,
        pic_length=5,
        decimal_places=2,
    )

    java_type = map_pic_to_java_type(item)

    assert java_type.basic_type == JavaBasicType.DOUBLE


def test_decimal_pic_preserves_decimal_metadata_and_generates_double_field():
    cobol = """>>SOURCE FORMAT FREE
IDENTIFICATION DIVISION.
PROGRAM-ID. DECIMAL-N1.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-AMOUNT PIC S9(5)V99 COMP-3 VALUE 12345.67.
01 WS-RATE   PIC 9(3)V9 COMP-3 VALUE 12.3.
PROCEDURE DIVISION.
MAIN.
    DISPLAY WS-AMOUNT.
    DISPLAY WS-RATE.
    STOP RUN.
"""

    program = CobolParser().parse(cobol)

    amount = next(item for item in program.working_storage if item.name == "WS-AMOUNT")
    rate = next(item for item in program.working_storage if item.name == "WS-RATE")

    assert amount.decimal_places == 2
    assert rate.decimal_places == 1

    java_program = map_cobol_program_to_java(program)
    fields = {field.name: field for field in java_program.java_class.fields}

    assert fields["WS_AMOUNT"].java_type.basic_type == JavaBasicType.DOUBLE
    assert fields["WS_RATE"].java_type.basic_type == JavaBasicType.DOUBLE

    application = JavaApplication(
        application_id="DECIMAL-N1",
        programs=(java_program,),
    )
    source = JavaGenerator().generate_from_java(application)[0].source_code

    assert "static double WS_AMOUNT = 12345.67;" in source
    assert "static double WS_RATE = 12.3;" in source
