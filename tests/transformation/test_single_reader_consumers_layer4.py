"""Layer 4: the engine's source-text consumers read through the single reader, not their own column logic.

Each case puts a verb in text that is not program text (a sequence-numbered comment line, a debug ``D`` line,
a dead ``>>IF`` branch, a ``*>`` tail) and asserts the consumer does not see it.
"""

from __future__ import annotations

from engine.jcl.job_lane import program_sources
from engine.oracle.docker_adapter import DockerOracleAdapter
from engine.sql.extractor import extract_embedded_sql_blocks
from engine.sql.oracle_pg import with_banner
from engine.transformation.source_format import comment_free_lines, program_text
from engine.transformation.semantic_capability import scan_constructs
from engine.transformation.subsystem_calls import _comment_free

SEQ_COMMENT = "000100* "
HEAD = "       IDENTIFICATION DIVISION.\n"


def test_program_text_blanks_comment_debug_dead_and_tail_but_keeps_line_count():
    source = (
        "       IDENTIFICATION DIVISION.\n"
        "000100* PROGRAM-ID. COMMENTED.\n"
        "      DPROGRAM-ID. DEBUGGED.\n"
        "       >>DEFINE ON AS 1\n"
        "       >>IF ON = 0\n"
        "       PROGRAM-ID. DEAD.\n"
        "       >>END-IF\n"
        "       PROGRAM-ID. LIVE. *> PROGRAM-ID. TAIL.\n"
    )
    text = program_text(source)
    assert text.count("\n") == source.count("\n")
    assert "COMMENTED" not in text and "DEBUGGED" not in text and "DEAD" not in text and "TAIL" not in text
    assert "LIVE" in text
    assert len(comment_free_lines(source, keep_line_numbers=True)) == len(source.split("\n"))
    assert len(comment_free_lines(source)) < len(source.split("\n"))


def test_job_lane_program_sources_ignores_a_commented_program_id(tmp_path):
    (tmp_path / "ghost.cbl").write_text(HEAD + "000100* PROGRAM-ID. GHOST.\n", encoding="utf-8")
    (tmp_path / "real.cbl").write_text(HEAD + "      * PROGRAM-ID. OLDNAME.\n       PROGRAM-ID. REAL.\n", encoding="utf-8")
    assert program_sources(tmp_path) == {"REAL": tmp_path / "real.cbl"}


def test_oracle_entry_selection_ignores_commented_program_id_and_call(tmp_path):
    source = tmp_path / "p.cbl"
    source.write_text(
        HEAD + "000100* PROGRAM-ID. GHOST.\n       PROGRAM-ID. REAL.\n"
        "       PROCEDURE DIVISION.\n000200* CALL 'CMT'.\n      DCALL 'DBG'.\n           CALL 'LIVE'.\n",
        encoding="utf-8")
    assert DockerOracleAdapter._read_program_id(source) == "REAL"
    assert DockerOracleAdapter._read_static_call_targets(source) == {"LIVE"}


def test_sql_extractor_ignores_exec_sql_in_sequence_numbered_comment_and_debug_lines():
    source = (
        "000100* EXEC SQL SELECT 1 FROM GHOST END-EXEC.\n"
        "      D    EXEC SQL SELECT 2 FROM DEBUGGED END-EXEC.\n"
        "000300     EXEC SQL SELECT 3 FROM LIVE END-EXEC.\n"
    )
    assert extract_embedded_sql_blocks(source) == ["SELECT 3 FROM LIVE"]


def test_sql_extractor_cuts_a_free_format_tail_comment():
    source = ">>SOURCE FORMAT FREE\nEXEC SQL SELECT 3 FROM LIVE END-EXEC. *> EXEC SQL SELECT 4 FROM TAIL END-EXEC\n"
    assert extract_embedded_sql_blocks(source) == ["SELECT 3 FROM LIVE"]


def test_with_banner_treats_a_sequence_numbered_comment_as_the_banner():
    source = HEAD + "       DATA DIVISION.\n000100* BANNER\n       PROCEDURE DIVISION.\n"
    assert with_banner(source) == source
    bare = HEAD + "       DATA DIVISION.\n       PROCEDURE DIVISION.\n"
    assert with_banner(bare).splitlines()[2] == "      *"


def test_capability_and_subsystem_scans_see_no_comment_text():
    source = (HEAD + "       PROCEDURE DIVISION.\n000100* SORT GHOST.\n      D    SORT DEBUGGED.\n"
              "           GOBACK. *> SORT TAIL.\n")
    assert "SORT" not in _comment_free(source)
    assert "SORT" not in "".join(scan_constructs(source))
