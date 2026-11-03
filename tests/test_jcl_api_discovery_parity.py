"""BL-063 API parity: the presence gate uses the same member rule as the consumer.

Split out of ``tests/transformation/test_jcl_discovery_matching.py``:
the capability-truth gate is deliberately dependency-free (pytest only,
no ``requirements.lock``), while ``api.service`` needs the runtime stack
(pydantic). These two parity tests keep their full-deps home here — the
backend CI job runs the whole ``tests`` tree, so the parity stays
enforced exactly as before. Do not add this file to the capability gate
list in ``ci.yml``.
"""

from __future__ import annotations

from pathlib import Path

from api.service import _jcl_status_for_source

JCLLIB_TREE = """\
//MEMB JOB CLASS=A
//STEP01 EXEC PGM=A
//IF A=1
//STEP02 EXEC PGM=B
//ENDIF
"""


class TestApiPresenceGateMatchesTheConsumer:
    def test_jcllib_only_tree_is_present_for_the_api_gate(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "member.jcllib").write_text(JCLLIB_TREE, encoding="utf-8")
        status = _jcl_status_for_source(tmp_path)
        assert status != "NOT_PRESENT", "presence gate blind to .jcllib members"

    def test_tree_without_any_jcl_member_is_absent_for_both(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "notes.txt").write_text("no jcl here", encoding="utf-8")
        assert _jcl_status_for_source(tmp_path) == "NOT_PRESENT"
