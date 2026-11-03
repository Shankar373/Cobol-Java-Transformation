"""Comparison contract strength (Docker-free).

A run may only be VERIFIED when every observable effect of the COBOL
program matched the generated Java:

* stdout and exit status (the default contract);
* every file either execution wrote — declared or not — compared
  byte-exactly, with a file produced on only one side a MISMATCH;
* no hidden CRLF folding: normalization happens only where a workload
  declares it;
* effects no comparator observes (EXEC SQL / DLI database access, EXEC
  CICS, MQ calls) are recorded as unsupported artifacts, so the verdict is
  UNSUPPORTED instead of VERIFIED.
"""

from __future__ import annotations

import dataclasses

from datetime import datetime, timezone
from pathlib import Path

import pytest

from api.workload_contract import default_contract
from engine.candidate.adapter import CandidateExecutionResult, CompilationResult
from engine.domain.identities import (
    AdapterStatus,
    ExecutionId,
    OracleIdentity,
    VerdictState,
)
from engine.oracle.adapter import OracleExecutionResult
from engine.pipeline import PipelineConfig, VerticalSlicePipeline
from tests.comparison_doubles import Candidate as _Candidate, Oracle as _Oracle, now as _now


_PLAIN = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. MAIN.\n"
    "       PROCEDURE DIVISION.\n"
    "           DISPLAY 'HI'.\n"
    "           STOP RUN.\n"
)


def _verdict(
    tmp_path: Path,
    *,
    source: str = _PLAIN,
    oracle_stdout: bytes = b"HI\n",
    candidate_stdout: bytes = b"HI\n",
    oracle_files: dict[str, bytes] | None = None,
    candidate_files: dict[str, bytes] | None = None,
    oracle_exit: int = 0,
    candidate_exit: int = 0,
    legacy: bool = False,
):
    src = tmp_path / "MAIN.cob"
    src.write_text(source, encoding="latin-1")
    cand = tmp_path / "cand"
    cand.mkdir()
    (cand / "Main.java").write_text("class Main {}", encoding="utf-8")
    config = PipelineConfig(
        workload_id="wl-contract",
        cobol_source_path=str(src),
        java_candidate_path=str(cand),
        java_entrypoint="Main",
        workload=None if legacy else default_contract("wl-contract").workload,
        use_docker_java=True,
    )
    pipe = VerticalSlicePipeline(
        config,
        candidate_adapter=_Candidate(candidate_stdout, candidate_files, candidate_exit),
    )
    pipe._oracle_adapter = _Oracle(oracle_stdout, oracle_files, oracle_exit)
    return pipe.run()


@pytest.fixture(params=[False, True], ids=["declared-contract", "legacy-path"])
def legacy(request):
    return request.param


class TestStdoutAndExitStatus:
    def test_identical_behaviour_is_verified(self, tmp_path, legacy):
        result = _verdict(tmp_path, legacy=legacy)
        assert result.verdict.state == VerdictState.VERIFIED

    def test_exit_status_difference_fails(self, tmp_path, legacy):
        result = _verdict(tmp_path, candidate_exit=4, legacy=legacy)
        assert result.verdict.state == VerdictState.FAILED

    def test_crlf_in_stdout_is_a_difference(self, tmp_path, legacy):
        result = _verdict(tmp_path, candidate_stdout=b"HI\r\n", legacy=legacy)
        assert result.verdict.state == VerdictState.FAILED


class TestGeneratedFiles:
    def test_matching_undeclared_file_is_compared_and_verified(self, tmp_path, legacy):
        files = {"REPORT.TXT": b"TOTAL 0042\n"}
        result = _verdict(
            tmp_path, oracle_files=dict(files), candidate_files=dict(files),
            legacy=legacy,
        )
        assert result.verdict.state == VerdictState.VERIFIED
        compared = [
            c for c in result.comparison_evidence
            if c.artifact_type in ("TEXT_FILE", "FIXED_RECORD")
        ]
        assert len(compared) == 1
        assert compared[0].result == "MATCH"

    def test_differing_undeclared_file_fails(self, tmp_path, legacy):
        result = _verdict(
            tmp_path,
            oracle_files={"REPORT.TXT": b"TOTAL 0042\n"},
            candidate_files={"REPORT.TXT": b"TOTAL 42\n"},
            legacy=legacy,
        )
        assert result.verdict.state == VerdictState.FAILED

    def test_file_only_the_oracle_wrote_fails(self, tmp_path, legacy):
        result = _verdict(
            tmp_path, oracle_files={"OUT.DAT": b""}, candidate_files=None,
            legacy=legacy,
        )
        assert result.verdict.state == VerdictState.FAILED

    def test_file_only_the_candidate_wrote_fails(self, tmp_path, legacy):
        result = _verdict(
            tmp_path, oracle_files=None, candidate_files={"debug.log": b"x"},
            legacy=legacy,
        )
        assert result.verdict.state == VerdictState.FAILED

    def test_crlf_in_generated_file_is_a_difference(self, tmp_path, legacy):
        result = _verdict(
            tmp_path,
            oracle_files={"REPORT.TXT": b"A\nB\n"},
            candidate_files={"REPORT.TXT": b"A\r\nB\r\n"},
            legacy=legacy,
        )
        assert result.verdict.state == VerdictState.FAILED


_SQL = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. MAIN.\n"
    "       DATA DIVISION.\n"
    "       WORKING-STORAGE SECTION.\n"
    "           EXEC SQL INCLUDE SQLCA END-EXEC.\n"
    "       PROCEDURE DIVISION.\n"
    "           EXEC SQL\n"
    "               UPDATE ACCOUNT SET BALANCE = 0\n"
    "           END-EXEC.\n"
    "           DISPLAY 'HI'.\n"
    "           STOP RUN.\n"
)


class TestUnobservedEffects:
    @pytest.mark.parametrize(
        ("statement", "artifact_type"),
        [
            ("EXEC SQL\n               UPDATE ACCOUNT SET BALANCE = 0\n           END-EXEC.", "DATABASE_STATE"),
            ("EXEC SQL COMMIT END-EXEC.", "DATABASE_STATE"),
            ("EXEC DLI GU USING PCB(1) END-EXEC.", "DATABASE_STATE"),
            ("CALL 'CBLTDLI' USING WS-FN.", "DATABASE_STATE"),
            ("EXEC CICS RETURN END-EXEC.", "TRANSACTION_EFFECTS"),
            ("CALL 'MQPUT' USING WS-HCONN.", "MESSAGE_QUEUE_EFFECTS"),
        ],
    )
    def test_unobservable_effect_blocks_verified(
        self, tmp_path, legacy, statement, artifact_type
    ):
        source = _PLAIN.replace(
            "           DISPLAY 'HI'.\n",
            f"           {statement}\n           DISPLAY 'HI'.\n",
        )
        result = _verdict(tmp_path, source=source, legacy=legacy)

        assert result.verdict.state == VerdictState.UNSUPPORTED
        types = {a.artifact.artifact_type for a in result.artifact_evidence}
        assert artifact_type in types

    def test_declarative_sql_alone_is_not_an_effect(self, tmp_path, legacy):
        source = _PLAIN.replace(
            "       PROCEDURE DIVISION.\n",
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "           EXEC SQL INCLUDE SQLCA END-EXEC.\n"
            "       PROCEDURE DIVISION.\n",
        )
        result = _verdict(tmp_path, source=source, legacy=legacy)
        assert result.verdict.state == VerdictState.VERIFIED

    def test_commented_out_sql_is_not_an_effect(self, tmp_path, legacy):
        source = _PLAIN.replace(
            "           DISPLAY 'HI'.\n",
            "      *    EXEC SQL DELETE FROM ACCOUNT END-EXEC.\n"
            "           DISPLAY 'HI'. *> EXEC SQL COMMIT END-EXEC\n",
        )
        result = _verdict(tmp_path, source=source, legacy=legacy)
        assert result.verdict.state == VerdictState.VERIFIED

    def test_unsupported_effect_evidence_passes_integrity(self, tmp_path, legacy):
        from engine.evidence.integrity import (
            EvidenceIntegrityValidator,
            ValidatedEvidenceManifest,
        )

        result = _verdict(tmp_path, source=_SQL, legacy=legacy)
        outcome = EvidenceIntegrityValidator().validate(result.evidence_manifest)
        assert isinstance(outcome, ValidatedEvidenceManifest), outcome


class TestStderrIsAlwaysCompared:
    """Audit V1: candidate stderr was compared only when the COBOL source
    itself wrote to stderr, so a candidate's stack trace or warning there -
    with matching stdout and exit status - still reached VERIFIED."""

    class _NoisyCandidate(_Candidate):
        def execute(self, run_id, compiled_path, manifest, input_data=None, input_files=None):
            result = super().execute(run_id, compiled_path, manifest, input_data, input_files)
            return dataclasses.replace(result, stderr=b"WARNING: retrying lookup\n")

    def test_candidate_stderr_the_cobol_never_writes_is_a_difference(self, tmp_path, legacy):
        src = tmp_path / "MAIN.cob"
        src.write_text(_PLAIN, encoding="latin-1")
        cand = tmp_path / "cand"
        cand.mkdir()
        (cand / "Main.java").write_text("class Main {}", encoding="utf-8")
        pipe = VerticalSlicePipeline(
            PipelineConfig(
                workload_id="wl-contract",
                cobol_source_path=str(src),
                java_candidate_path=str(cand),
                java_entrypoint="Main",
                workload=None if legacy else default_contract("wl-contract").workload,
                use_docker_java=True,
            ),
            candidate_adapter=self._NoisyCandidate(b"HI\n", None, 0),
        )
        pipe._oracle_adapter = _Oracle(b"HI\n", None, 0)
        result = pipe.run()

        by_type = {c.artifact_type: c.result for c in result.evidence_manifest.comparison_evidence}
        assert by_type.get("STDERR") == "MISMATCH", by_type
        assert result.verdict.state == VerdictState.FAILED
