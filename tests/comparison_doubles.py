"""Oracle and candidate doubles for pipeline-level comparison tests.

Shared by the comparison-contract tests (audit CI-F8): they used to be
private classes of ``test_comparison_contract_strength`` that other test
modules imported.
"""

from __future__ import annotations

from datetime import datetime, timezone

from engine.candidate.adapter import CandidateExecutionResult, CompilationResult
from engine.domain.identities import AdapterStatus, ExecutionId, OracleIdentity
from engine.oracle.adapter import OracleExecutionResult


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Oracle:
    def __init__(self, stdout: bytes, files: dict[str, bytes] | None, exit_code: int):
        self._stdout, self._files, self._exit = stdout, files, exit_code

    def get_identity(self):
        return OracleIdentity(
            oracle_id="test-oracle",
            image_digest="sha256:" + "a" * 64,
            compiler_version="3.1.2.0",
        )

    def execute(self, run_id, source_path, input_data=None, input_files=None):
        return OracleExecutionResult(
            execution_id=ExecutionId(value=f"oracle-{run_id.value}"),
            run_id=run_id,
            oracle_id="test-oracle",
            status=AdapterStatus.SUCCEEDED,
            exit_code=self._exit,
            stdout=self._stdout,
            stderr=b"",
            start_time=now(),
            end_time=now(),
            termination_status="normal",
            timeout_applied=False,
            generated_files=self._files,
        )


class Candidate:
    def __init__(self, stdout: bytes, files: dict[str, bytes] | None, exit_code: int):
        self._stdout, self._files, self._exit = stdout, files, exit_code

    def compile(self, candidate_path, manifest):
        return CompilationResult(success=True, class_files={"Main.class": b"\xca\xfe"})

    def execute(self, run_id, compiled_path, manifest, input_data=None, input_files=None):
        return CandidateExecutionResult(
            execution_id=ExecutionId(value=f"candidate-{run_id.value}"),
            run_id=run_id,
            status=AdapterStatus.SUCCEEDED,
            exit_code=self._exit,
            stdout=self._stdout,
            stderr=b"",
            start_time=now(),
            end_time=now(),
            termination_status="normal",
            timeout_applied=False,
            generated_files=self._files,
        )
