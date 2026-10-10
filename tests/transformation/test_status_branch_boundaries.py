"""Nested outcomes do not define the enclosing flag's status mapping."""
from engine.transformation.cobol_parser import CobolParser


def test_status_mapping_does_not_search_across_nested_operations():
    mappings = CobolParser()._extract_status_codes([
        "IF INPUT-STATE = 'R'",
        "MOVE 'REJECTED' TO RESULT-STATE",
        "ELSE",
        "IF MATCH-FOUND = 'Y'",
        "ADD MATCH-AMOUNT TO TOTAL-AMOUNT",
        "IF MATCH-AMOUNT = INPUT-AMOUNT",
        "MOVE 'PAID_IN_FULL' TO RESULT-STATE",
        "END-IF",
        "END-IF",
        "END-IF",
    ])
    assert [(item.field_name, item.code, item.label) for item in mappings] == [
        ("INPUT-STATE", "R", "REJECTED"),
    ]
