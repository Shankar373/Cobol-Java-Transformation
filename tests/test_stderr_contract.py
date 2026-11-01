"""A program that writes to standard error is compared on stderr (Docker-free).

The default contract compares stdout and exit status.  When the COBOL
source itself writes to the error device (``DISPLAY ... UPON STDERR`` /
``SYSERR``, or a SPECIAL-NAMES mnemonic for it), stderr is part of the
program's behaviour, so the declared-contract pipeline adds an exact STDERR
comparison: Java that drops or alters those lines can no longer be VERIFIED.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from api.workload_contract import default_contract
from engine.domain.identities import VerdictState
from engine.pipeline import PipelineConfig, VerticalSlicePipeline
from tests.test_comparison_contract_strength import _Candidate, _Oracle

_UPON_STDERR = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. MAIN.\n"
    "       PROCEDURE DIVISION.\n"
    "           DISPLAY 'HI'.\n"
    "           DISPLAY 'WARN' UPON STDERR.\n"
    "           STOP RUN.\n"
)
_SYSERR_MNEMONIC = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. MAIN.\n"
    "       ENVIRONMENT DIVISION.\n"
    "       CONFIGURATION SECTION.\n"
    "       SPECIAL-NAMES.\n"
    "           SYSERR IS ERR-OUT.\n"
    "       PROCEDURE DIVISION.\n"
    "           DISPLAY 'HI'.\n"
    "           DISPLAY 'WARN' UPON ERR-OUT.\n"
    "           STOP RUN.\n"
)
_STDOUT_ONLY = _UPON_STDERR.replace("           DISPLAY 'WARN' UPON STDERR.\n", "")


class _StderrOracle(_Oracle):
    def __init__(self, stderr: bytes):
        super().__init__(b"HI\n", None, 0)
        self._stderr = stderr

    def execute(self, *args, **kwargs):
        return replace(super().execute(*args, **kwargs), stderr=self._stderr)


class _StderrCandidate(_Candidate):
    def __init__(self, stderr: bytes):
        super().__init__(b"HI\n", None, 0)
        self._stderr = stderr

    def execute(self, *args, **kwargs):
        return replace(super().execute(*args, **kwargs), stderr=self._stderr)


def _run(tmp_path: Path, source: str, oracle_err: bytes, candidate_err: bytes):
    src = tmp_path / "MAIN.cob"
    src.write_text(source, encoding="latin-1")
    cand = tmp_path / "cand"
    cand.mkdir()
    (cand / "Main.java").write_text("class Main {}", encoding="utf-8")
    pipe = VerticalSlicePipeline(
        PipelineConfig(
            workload_id="wl-stderr",
            cobol_source_path=str(src),
            java_candidate_path=str(cand),
            java_entrypoint="Main",
            workload=default_contract("wl-stderr").workload,
        ),
        candidate_adapter=_StderrCandidate(candidate_err),
    )
    pipe._oracle_adapter = _StderrOracle(oracle_err)
    return pipe.run()


def _stderr_results(result) -> list[str]:
    return [c.result for c in result.comparison_evidence if c.artifact_type == "STDERR"]


def test_dropped_stderr_line_is_a_mismatch(tmp_path):
    result = _run(tmp_path, _UPON_STDERR, b"WARN\n", b"")
    assert _stderr_results(result) == ["MISMATCH"]
    assert result.verdict.state == VerdictState.FAILED


def test_matching_stderr_is_verified(tmp_path):
    result = _run(tmp_path, _UPON_STDERR, b"WARN\n", b"WARN\n")
    assert _stderr_results(result) == ["MATCH"]
    assert result.verdict.state == VerdictState.VERIFIED


def test_syserr_mnemonic_counts_as_stderr_write(tmp_path):
    result = _run(tmp_path, _SYSERR_MNEMONIC, b"WARN\n", b"")
    assert _stderr_results(result) == ["MISMATCH"]
    assert result.verdict.state == VerdictState.FAILED


def test_program_without_stderr_writes_keeps_default_contract(tmp_path):
    result = _run(tmp_path, _STDOUT_ONLY, b"", b"")
    assert _stderr_results(result) == []
    assert result.verdict.state == VerdictState.VERIFIED
