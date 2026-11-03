"""Audit V16: the oracle's compile and run have separate time budgets.

``cobc`` and the program ran under one ``timeout_seconds`` budget, so a slow
compile was charged to the program and could turn a correct reference into
a timeout. The compile now has its own budget (``compile_timeout_seconds``)
and only the program is held to ``timeout_seconds``, by an in-container
watchdog that keeps the program in the foreground (stdin stays attached for
ACCEPT) and leaves a marker file, so a timeout is never inferred from an exit
code the program could produce itself (124, 137).
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from engine.domain.identities import RunId
from engine.oracle.adapter import OracleAdapterConfig
from engine.oracle.docker_adapter import (
    DockerOracleAdapter,
    oracle_outer_timeout,
    oracle_shell_command,
)


# ---------------------------------------------------------------------------
# The command (no Docker)
# ---------------------------------------------------------------------------

def _command(compile_s: int = 120, run_s: int = 7) -> str:
    return oracle_shell_command(
        compile_dir="/src", compile_flags="-free ", compile_units="MAIN.cob",
        compile_seconds=compile_s, run_seconds=run_s,
    )


def test_compile_has_its_own_budget():
    command = _command(compile_s=95)
    assert "timeout -s KILL 95 cobc -x -free MAIN.cob" in command
    assert "compile_timeout" in command  # marker for a compile that ran out


def test_program_runs_in_the_foreground_under_a_watchdog():
    command = _command(run_s=7)
    assert "sleep 7" in command
    assert "/workspace/compilation/run_timeout" in command
    assert command.rstrip().endswith("exec /tmp/oracle_prog")
    # The program itself is never wrapped in `timeout` (its exit code stays
    # its own) and never sent to the background (stdin stays attached).
    assert "timeout -s KILL 7" not in command
    assert "/tmp/oracle_prog &" not in command


def test_outer_timeout_covers_both_budgets():
    assert oracle_outer_timeout(compile_seconds=120, run_seconds=30) >= 150


def test_config_default_compile_budget():
    config = OracleAdapterConfig(oracle_id="o", image_digest="", compiler_version="v")
    assert config.compile_timeout_seconds == 120
    assert config.timeout_seconds == 30


# ---------------------------------------------------------------------------
# Behaviour on the oracle image (Docker lane)
# ---------------------------------------------------------------------------

def _adapter(run_seconds: int) -> DockerOracleAdapter:
    if os.environ.get("RUN_DOCKER_TESTS") != "1":
        pytest.skip("Docker lane test: set RUN_DOCKER_TESTS=1 to run it")
    return DockerOracleAdapter(OracleAdapterConfig(
        oracle_id="gnucobol-3.1.2", image_digest="", compiler_version="3.1.2.0",
        timeout_seconds=run_seconds,
    ))


def _program(tmp_path: Path, body: str, data: str = "") -> str:
    source = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. TMO.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01 WS-N PIC 9(4) VALUE 0.\n"
        "       01 WS-X PIC X(10).\n"
        f"{data}"
        "       PROCEDURE DIVISION.\n"
        f"{body}"
        "           STOP RUN.\n"
    )
    (tmp_path / "TMO.cob").write_text(source, encoding="utf-8")
    return str(tmp_path)


def test_endless_program_times_out_on_the_run_budget(tmp_path):
    adapter = _adapter(run_seconds=3)
    src = _program(tmp_path, (
        "           PERFORM UNTIL WS-N > 9999\n"
        "               MOVE 1 TO WS-N\n"
        "           END-PERFORM\n"
    ))
    started = time.monotonic()
    outcome = adapter.execute(RunId(value="run-v16-loop"), src)
    assert outcome.termination_status == "timeout"
    assert outcome.exit_code is None
    assert time.monotonic() - started < 90


@pytest.mark.parametrize("code", [124, 137])
def test_own_exit_codes_are_not_mistaken_for_a_timeout(tmp_path, code):
    adapter = _adapter(run_seconds=30)
    src = _program(tmp_path, f"           MOVE {code} TO RETURN-CODE\n")
    outcome = adapter.execute(RunId(value=f"run-v16-rc{code}"), src)
    assert outcome.exit_code == code
    assert outcome.termination_status == "return_code"


def test_stdin_still_reaches_accept(tmp_path):
    adapter = _adapter(run_seconds=30)
    src = _program(tmp_path, (
        "           ACCEPT WS-X\n"
        "           DISPLAY \"GOT \" WS-X\n"
    ))
    outcome = adapter.execute(RunId(value="run-v16-stdin"), src, input_data=b"HELLO\n")
    assert outcome.exit_code == 0, outcome.stderr.decode(errors="replace")
    assert outcome.stdout == b"GOT HELLO     \n"
