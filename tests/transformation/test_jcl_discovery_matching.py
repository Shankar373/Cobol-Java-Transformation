"""BL-063: one discovery rule shared by every JCL consumer, decode failures diagnosed.

Phase 5 §76 probes 1-5/12/14 (`%TEMP%\\opencode\\phase5\\probe_p5_r1.py`,
`probe_p5_r2.py`) proved the JCL lane's file-selection logic was
duplicated and divergent:

- the consumer's unsupported scan used ``rglob("*.jcl")`` only, so
  ``.jcllib``/extensionless members were never scanned — unsupported
  constructs in them went undetected under status FULL (PROBE1/2);
- sources were keyed by **basename**, so colliding basenames silently
  overwrote each other and one member's text never entered the scan
  pool (PROBE12, §54 silent-loss class);
- a non-UTF8 member crashed ``modernize_jcl_workload`` with
  ``UnicodeDecodeError`` while ``JclDiscovery`` silently dropped the
  same file (PROBE4);
- the API presence gate used its own ``rglob("*.jcl")`` and reported
  ``NOT_PRESENT`` for ``.jcllib``-only trees while the consumer said
  ``FULL`` (PROBE5);
- on Linux (case-sensitive glob) uppercase suffixes would be missed
  entirely (PROBE14, static finding).

Expected behavior: a single shared member matcher (case-insensitive
``.jcl``/``.jcllib``/extensionless) used by discovery, the consumer
scan, and the API presence gate; per-member path keys so no member can
overwrite another; decode failures diagnosed fail-closed, never
escaping and never silently dropped.
"""

from __future__ import annotations

from pathlib import Path

from engine.transformation.jcl_consumer import modernize_jcl_workload
from engine.transformation.jcl_discovery import find_jcl_members, is_jcl_member

UNSUPPORTED_BODY = "//STEP01 EXEC PGM=A\n//IF A=1\n//STEP02 EXEC PGM=B\n//ENDIF\n"

JCLLIB_TREE = """\
//MEMB JOB CLASS=A
//STEP01 EXEC PGM=A
//IF A=1
//STEP02 EXEC PGM=B
//ENDIF
"""


class TestSharedMemberMatcher:
    def test_uppercase_suffix_is_a_jcl_member(self) -> None:
        assert is_jcl_member(Path("UPPER.JCL")) is True

    def test_jcllib_and_plain_jcl_members_are_recognized(self) -> None:
        assert is_jcl_member(Path("prog.jcllib")) is True
        assert is_jcl_member(Path("prog.jcl")) is True

    def test_extensionless_member_with_jcl_content_is_recognized(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "member").write_text("//A JOB CLASS=A\n", encoding="utf-8")
        assert is_jcl_member(tmp_path / "member") is True

    def test_extensionless_file_without_jcl_content_is_not_a_member(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "makefile").write_text("all:\n\tnope\n", encoding="utf-8")
        assert is_jcl_member(tmp_path / "makefile") is False

    def test_unrelated_files_are_not_members(self) -> None:
        assert is_jcl_member(Path("readme.txt")) is False
        assert is_jcl_member(Path("data.dat")) is False
        assert is_jcl_member(Path(".hidden")) is False


class TestUnsupportedScanCoversEveryMember:
    def test_jcllib_member_with_unsupported_construct_is_diagnosed(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "member.jcllib").write_text(JCLLIB_TREE, encoding="utf-8")
        result = modernize_jcl_workload(tmp_path, application_id="bl063")
        assert result.status != "FULL", "unscanned member reported FULL"
        assert any("IF" in (d.message or "") for d in result.diagnostics)

    def test_extensionless_member_with_unsupported_construct_is_diagnosed(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "member").write_text(JCLLIB_TREE, encoding="utf-8")
        result = modernize_jcl_workload(tmp_path, application_id="bl063")
        assert result.status != "FULL", "unscanned member reported FULL"
        assert any("IF" in (d.message or "") for d in result.diagnostics)

    def test_shared_finder_sees_every_member_kind(self, tmp_path: Path) -> None:
        (tmp_path / "a.jcl").write_text("//A JOB CLASS=A\n", encoding="utf-8")
        (tmp_path / "b.jcllib").write_text("//B JOB CLASS=A\n", encoding="utf-8")
        (tmp_path / "c").write_text("//C JOB CLASS=A\n", encoding="utf-8")
        (tmp_path / "UPPER.JCL").write_text("//U JOB CLASS=A\n", encoding="utf-8")
        (tmp_path / "notes.txt").write_text("ignore me", encoding="utf-8")
        names = sorted(p.name for p in find_jcl_members(tmp_path))
        assert names == ["UPPER.JCL", "a.jcl", "b.jcllib", "c"]

    def test_basename_collision_does_not_lose_the_unsupported_member(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "a").mkdir()
        (tmp_path / "b").mkdir()
        (tmp_path / "a" / "dup.jcl").write_text(JCLLIB_TREE, encoding="utf-8")
        (tmp_path / "b" / "dup.jcl").write_text(
            "//CLEAN JOB CLASS=A\n//S1 EXEC PGM=A\n", encoding="utf-8"
        )
        result = modernize_jcl_workload(tmp_path, application_id="bl063")
        assert result.status != "FULL", "colliding member silently lost"
        assert any("IF" in (d.message or "") for d in result.diagnostics)

    def test_clean_single_member_tree_stays_full(self, tmp_path: Path) -> None:
        (tmp_path / "ok.jcl").write_text(
            "//OKJOB JOB CLASS=A\n//S1 EXEC PGM=A\n", encoding="utf-8"
        )
        result = modernize_jcl_workload(tmp_path, application_id="bl063")
        assert result.status == "FULL"


class TestDecodeFailuresAreDiagnosedNotEscaped:
    def test_non_utf8_member_is_diagnosed_instead_of_crashing(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "latin.jcl").write_bytes(
            b"//LJOB JOB CLASS=A\n//* caf\xe9\n//S1 EXEC PGM=A\n"
        )
        result = modernize_jcl_workload(tmp_path, application_id="bl063")
        assert result.status != "FULL"
        assert any(
            d.code.value == "JCL_SOURCE_DECODE_FAILED" for d in result.diagnostics
        )

    def test_decodable_member_still_modernizes_next_to_a_bad_one(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "bad.jcl").write_bytes(b"//X JOB\n\xff\xfe broken\n")
        (tmp_path / "good.jcl").write_text(
            "//GOODJOB JOB CLASS=A\n//S1 EXEC PGM=A\n", encoding="utf-8"
        )
        result = modernize_jcl_workload(tmp_path, application_id="bl063")
        assert any(job.name == "GOODJOB" for job in result.profile.application.jobs)


class TestApiPresenceGateMatchesTheConsumer:
    def test_jcllib_only_tree_is_present_for_the_api_gate(
        self, tmp_path: Path
    ) -> None:
        from api.service import _jcl_status_for_source

        (tmp_path / "member.jcllib").write_text(JCLLIB_TREE, encoding="utf-8")
        status = _jcl_status_for_source(tmp_path)
        assert status != "NOT_PRESENT", "presence gate blind to .jcllib members"

    def test_tree_without_any_jcl_member_is_absent_for_both(
        self, tmp_path: Path
    ) -> None:
        from api.service import _jcl_status_for_source

        (tmp_path / "notes.txt").write_text("no jcl here", encoding="utf-8")
        assert _jcl_status_for_source(tmp_path) == "NOT_PRESENT"
