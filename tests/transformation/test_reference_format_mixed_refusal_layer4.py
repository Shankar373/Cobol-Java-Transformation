"""Layer 4: a file that switches reference format is refused by name by the one-flag reference lanes.

``cobc`` is given one ``-free``/fixed flag per compilation unit, chosen from the file's *start* format.  A
mid-file switch (``>>SOURCE FORMAT`` / ``$SET SOURCEFORMAT``) cannot be represented by that flag, so the
oracle and the JCL reference lane refuse it as ``REFERENCE_FORMAT_MIXED_UNSUPPORTED`` instead of silently
compiling it under the start flag.  (Discovery's check lane reports the same situation as the verdict
``NOT_ATTEMPTED_REFERENCE_FORMAT``; that is a verdict, this is a refusal code.)
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from engine.jcl.job_lane import _compile_script
from engine.jcl.reference import ReferenceUnavailable
from engine.oracle.docker_adapter import DockerOracleAdapter
from engine.transformation.diagnostics import DiagnosticCode
from engine.transformation.source_format import detect_source_format, mixed_format_refusal

MIXED_FIXED_TO_FREE = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. MIX.\n"
    ">>SOURCE FORMAT FREE\n"
    "PROCEDURE DIVISION.\n"
    "STOP RUN.\n"
)
MIXED_FREE_TO_FIXED = MIXED_FIXED_TO_FREE.replace("       IDENTIFICATION", "IDENTIFICATION").replace(
    "FREE", "FIXED")
MIXED_MICRO_FOCUS = (
    "IDENTIFICATION DIVISION.\n"
    "PROGRAM-ID. MIX.\n"
    '$SET SOURCEFORMAT"FIXED"\n'
    "       PROCEDURE DIVISION.\n"
    "           STOP RUN.\n"
)
PLAIN_FIXED = "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. OK.\n       PROCEDURE DIVISION.\n           STOP RUN.\n"
PLAIN_FREE = ">>SOURCE FORMAT FREE\nIDENTIFICATION DIVISION.\nPROGRAM-ID. OK.\nPROCEDURE DIVISION.\nSTOP RUN.\n"


def test_the_refusal_code_exists_and_is_the_name_in_the_message():
    assert DiagnosticCode.REFERENCE_FORMAT_MIXED_UNSUPPORTED.value == "REFERENCE_FORMAT_MIXED_UNSUPPORTED"
    message = mixed_format_refusal(MIXED_FIXED_TO_FREE, "mix.cbl")
    assert message is not None
    assert message.startswith("REFERENCE_FORMAT_MIXED_UNSUPPORTED: mix.cbl:3:")
    assert "(fixed -> free)" in message


@pytest.mark.parametrize("text", [MIXED_FIXED_TO_FREE, MIXED_FREE_TO_FIXED, MIXED_MICRO_FOCUS])
def test_every_kind_of_switch_is_refused(text: str):
    assert mixed_format_refusal(text) is not None
    # The start flag alone would be chosen for it: that is what the refusal replaces.
    assert detect_source_format(text) in ("fixed", "free")


@pytest.mark.parametrize("text", [PLAIN_FIXED, PLAIN_FREE])
def test_a_single_format_file_is_not_refused_even_with_a_start_directive(text: str):
    assert mixed_format_refusal(text) is None


def test_oracle_adapter_refuses_a_mixed_module_by_name_and_accepts_the_others(tmp_path: Path):
    (tmp_path / "mix.cbl").write_text(MIXED_FIXED_TO_FREE, encoding="utf-8")
    (tmp_path / "ok.cbl").write_text(PLAIN_FIXED, encoding="utf-8")
    refusals = DockerOracleAdapter._mixed_format_refusals(tmp_path, ["ok.cbl", "mix.cbl"])
    assert len(refusals) == 1 and refusals[0].startswith("REFERENCE_FORMAT_MIXED_UNSUPPORTED: mix.cbl:3:")
    assert DockerOracleAdapter._mixed_format_refusals(tmp_path, ["ok.cbl"]) == ()
    assert DockerOracleAdapter._mixed_format_refusals(tmp_path, ["missing.cbl"]) == ()  # unreadable: not this refusal


def _plan(*programs: str) -> SimpleNamespace:
    return SimpleNamespace(steps=[SimpleNamespace(program=p, utility=None) for p in programs])


def test_job_lane_refuses_a_mixed_program_instead_of_compiling_it_under_the_start_flag(tmp_path: Path):
    (tmp_path / "MIX.cbl").write_text(MIXED_FIXED_TO_FREE, encoding="utf-8")
    (tmp_path / "OK.cbl").write_text(PLAIN_FIXED, encoding="utf-8")
    sources = {"MIX": tmp_path / "MIX.cbl", "OK": tmp_path / "OK.cbl"}
    with pytest.raises(ReferenceUnavailable) as raised:
        _compile_script(_plan("MIX", "OK"), sources, tmp_path, tmp_path)
    assert raised.value.reasons[0].startswith("REFERENCE_FORMAT_MIXED_UNSUPPORTED: MIX.cbl:3:")
    # Mutation: without the switch the same job compiles (a script is produced, no refusal).
    (tmp_path / "MIX.cbl").write_text(PLAIN_FIXED.replace("OK.", "MIX."), encoding="utf-8")
    assert _compile_script(_plan("MIX", "OK"), sources, tmp_path, tmp_path).count("cobc -x") == 2
