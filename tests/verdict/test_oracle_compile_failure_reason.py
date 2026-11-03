"""An oracle compile failure is named, not reported as an outage.

When cobc rejects the COBOL source there is no reference behaviour, so the
verdict stays UNAVAILABLE, but its difference says the source does not
compile instead of "Required infrastructure unavailable".
"""
from __future__ import annotations

from dataclasses import replace

from engine.domain.identities import RunId, VerdictState
from engine.verdict.derivation import derive_verdict
from tests.verdict.test_j9_mixed_states import _exec, _manifest


def _verdict(diagnostics):
    run_id = RunId(value="run-compile-fail")
    oracle = replace(
        _exec(run_id, "o1", "oracle-gnucobol", "nonzero_exit"),
        compilation_diagnostics=diagnostics,
    )
    candidate = _exec(run_id, "c1", "candidate-java", "normal")
    return derive_verdict(_manifest(run_id, [oracle], [candidate]))


def test_cobc_rejection_is_named():
    v = _verdict({"exit_code": "1", "stdout_base64": "", "stderr_base64": ""})
    assert v.state == VerdictState.UNAVAILABLE
    assert v.differences == (
        "COBOL source does not compile on the oracle (cobc exit 1); "
        "no reference behaviour exists",
    )


def test_runtime_failure_after_successful_compile_keeps_generic_reason():
    v = _verdict({"exit_code": "0", "stdout_base64": "", "stderr_base64": ""})
    assert v.state == VerdictState.UNAVAILABLE
    assert v.differences == ("Required infrastructure unavailable",)


def test_missing_diagnostics_keeps_generic_reason():
    v = _verdict(None)
    assert v.state == VerdictState.UNAVAILABLE
    assert v.differences == ("Required infrastructure unavailable",)
