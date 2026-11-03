"""Pipeline helpers for the indexed/relative record-comparison tests.

Shared by both (audit CI-F8): they used to live in
``test_indexed_record_comparison`` and be imported from the relative test.
"""

from __future__ import annotations

from pathlib import Path

from api.workload_contract import default_contract
from engine.pipeline import PipelineConfig, VerticalSlicePipeline
from tests.comparison_doubles import Candidate, Oracle

_SOURCE = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. MAIN.\n"
    "       ENVIRONMENT DIVISION.\n"
    "       INPUT-OUTPUT SECTION.\n"
    "       FILE-CONTROL.\n"
    '           SELECT IDX-FILE ASSIGN TO "IDX.DAT"\n'
    "               ORGANIZATION IS INDEXED\n"
    "               RECORD KEY IS IDX-KEY.\n"
    "       PROCEDURE DIVISION.\n"
    "           DISPLAY 'HI'.\n"
    "           STOP RUN.\n"
)
_RECORDS = [b"K002REC-TWO-UPDATED---- ", b"K003RECORD-THREE-DATA---"]


def _run(tmp_path: Path, oracle_files, candidate_files, source: str = _SOURCE):
    src = tmp_path / "MAIN.cob"
    src.write_text(source, encoding="latin-1")
    cand = tmp_path / "cand"
    cand.mkdir()
    (cand / "Main.java").write_text("class Main {}", encoding="utf-8")
    pipe = VerticalSlicePipeline(
        PipelineConfig(
            workload_id="wl-idx",
            cobol_source_path=str(src),
            java_candidate_path=str(cand),
            java_entrypoint="Main",
            workload=default_contract("wl-idx").workload,
        ),
        candidate_adapter=Candidate(b"HI\n", candidate_files, 0),
    )
    pipe._oracle_adapter = Oracle(b"HI\n", oracle_files, 0)
    return pipe.run()


def _file_results(result) -> dict[str, str]:
    return {
        c.comparison_id.split(":", 1)[1].rsplit("-run-", 1)[0]: c.result
        for c in result.comparison_evidence
        if ":" in c.comparison_id and c.artifact_type == "TEXT_FILE"
    }
