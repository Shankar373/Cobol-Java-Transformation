"""DISPLAY labels resolve width from the displayed data item, not the label.

The generated program reads ``/workspace/input`` (its ASSIGN paths), so it is
compiled here and its DISPLAY lowering checked; the runtime output of the
claims program is pinned against GnuCOBOL in
tests/integration/test_claims_statement_lowering_oracle.py. (The former
summary-field metadata belonged to the removed decision template, audit T5.)
"""
from pathlib import Path
import subprocess

import pytest

from engine.transformation.cobol_parser import CobolParser
from engine.transformation.java_generator import JavaGenerator


@pytest.mark.parametrize("width", [2, 4, 7])
def test_summary_alias_keeps_numeric_pic_width(tmp_path, width):
    source = Path("fixtures/workload-claims/cobol/CLAIMS.cob").read_text()
    source = source.replace("WS-CLAIM-COUNT", "RECORD-COUNTER")
    source = source.replace("RECORD-COUNTER        PIC 9(2)", f"RECORD-COUNTER        PIC 9({width})")
    program = CobolParser().parse(source)
    generated = JavaGenerator().generate(program)[0]
    java = generated.source_code
    assert f'"TOTAL_CLAIMS=" + String.format("%0{width}d", RECORD_COUNTER)' in java
    assert '"TOTAL_CLAIM_AMT=" + String.format("%06d", WS_TOTAL_CLAIMS)' in java
    path = tmp_path / generated.filename
    path.write_text(java, encoding="utf-8")
    built = subprocess.run(["javac", "-encoding", "UTF-8", str(path)], capture_output=True)
    assert built.returncode == 0, built.stderr
