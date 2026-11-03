"""STRING output metadata survives physical line wrapping."""
from pathlib import Path

import pytest
from engine.transformation.cobol_parser import CobolParser


@pytest.mark.parametrize("wrapped", [False, True])
def test_each_string_record_keeps_its_own_format(wrapped):
    lines = []
    for field, record in (("FIRST-FIELD", "FIRST-REC"), ("SECOND-FIELD", "SECOND-REC")):
        if wrapped:
            lines.extend([f"STRING {field} DELIMITED BY SIZE", '" " DELIMITED BY SIZE',
                          f"INTO {record}", "END-STRING."])
        else:
            lines.append(f'STRING {field} DELIMITED BY SIZE " " DELIMITED BY SIZE INTO {record} END-STRING.')
    formats = CobolParser()._extract_output_formats(lines)
    assert [item.record_format.record_name for item in formats] == ["FIRST-REC", "SECOND-REC"]
    assert [[field.field_name for field in item.record_format.fields] for item in formats] == [
        ["FIRST-FIELD", '" "'], ["SECOND-FIELD", '" "'],
    ]


def test_actual_claims_source_preserves_both_output_records():
    program = CobolParser().parse(Path("fixtures/workload-claims/cobol/CLAIMS.cob").read_text())
    assert [item.record_format.record_name for item in program.output_formats] == ["REPORT-REC", "SETTLE-REC"]
    for item in program.output_formats:
        assert "WS-CR-CLAIM-ID" in [field.field_name for field in item.record_format.fields]
        assert "WS-SETTLEMENT-STATUS" in [field.field_name for field in item.record_format.fields]
