"""Roadmap unit 15: SIMDLI-1 specification -- the reference model's documented behaviour.

The Java library is held equal to this model by ``tests/integration/test_simdli_conformance.py``.
"""

from __future__ import annotations

import pytest

from engine.simulators.dli import SPEC_VERSION, run_script

DBD = "DBD COMPANY::2:10 DEPT:COMPANY:2:8 EMP:DEPT:3:12 PROJ:DEPT:2:6\n"
LOAD = (
    "ISRT COMPANY ACMECORP01\n"
    "ISRT COMPANY(=AC)/DEPT D2LEGAL1\n"
    "ISRT COMPANY(=AC)/DEPT D1SALES1\n"
    "ISRT COMPANY(=AC)/DEPT(=D1)/PROJ P1ALPH\n"
    "ISRT COMPANY(=AC)/DEPT(=D1)/PROJ A1BETA\n"
    "ISRT COMPANY(=AC)/DEPT(=D1)/EMP E02JONES0002\n"
    "ISRT COMPANY(=AC)/DEPT(=D1)/EMP E01SMITH0001\n"
)
LOAD_LINES = len(LOAD.splitlines())


def _trace(body: str) -> list[str]:
    return run_script(DBD + LOAD + body)[1 + LOAD_LINES:]


def _statuses(body: str) -> list[str]:
    return [line.split(" -> ")[1] for line in _trace(body)]


class TestLoadAndSequence:
    def test_the_dbd_line_reports_the_spec_version(self):
        assert run_script(DBD)[0].endswith(f"-> {SPEC_VERSION}")

    def test_an_insert_leaves_the_inserted_segment_current(self):
        # DL/I: the position after ISRT is the inserted segment, so GN continues after it
        assert _statuses("GN\n") == ["OK seg=EMP data=E02JONES0002"]  # the last insert was EMP E01

    def test_a_full_scan_is_hierarchical_children_by_type_then_key(self):
        # EMP precedes PROJ (DBD order) even though key A1 sorts before E01
        scan = _trace("GU COMPANY(=AC)\nGN\nGN\nGN\nGN\nGN\nGN\nGN\n")
        assert [line.split(" -> ")[1] for line in scan] == [
            "OK seg=COMPANY data=ACMECORP01", "OK seg=DEPT data=D1SALES1", "OK seg=EMP data=E01SMITH0001",
            "OK seg=EMP data=E02JONES0002", "OK seg=PROJ data=A1BETA", "OK seg=PROJ data=P1ALPH",
            "OK seg=DEPT data=D2LEGAL1", "GB"]

    def test_gn_with_a_segment_type_skips_the_others(self):
        assert _statuses("GU COMPANY(=AC)\nGN EMP\nGN EMP\nGN EMP\n")[1:] == [
            "OK seg=EMP data=E01SMITH0001", "OK seg=EMP data=E02JONES0002", "GB"]

    def test_insert_errors(self):
        errors = _statuses(
            "ISRT COMPANY(=AC)/DEPT(=D1)/EMP E01SMITH0001\n"   # duplicate key
            "ISRT COMPANY(=ZZ)/DEPT D3XXXXXX\n"                 # parent not found
            "ISRT COMPANY(=AC)/DEPT D3SHORT\n"                  # wrong data length
            "ISRT COMPANY(=AC)/EMP E03XXXXXXXXX\n"              # EMP is not a child of COMPANY
            "ISRT COMPANY/DEPT D3XXXXXX\n"                      # a parent on the path is unqualified
            "ISRT NOPE X\n")                                    # unknown segment type
        assert errors == ["II", "GE", "AK", "AK", "AK", "AK"]


class TestGetUnique:
    def test_a_qualified_path_finds_the_segment_and_a_miss_is_ge(self):
        assert _statuses("GU COMPANY(=AC)/DEPT(=D1)/EMP(=E02)\nGU COMPANY(=AC)/DEPT(=D9)\n") == [
            "OK seg=EMP data=E02JONES0002", "GE"]

    def test_unqualified_ssas_take_the_first_segment(self):
        assert _statuses("GU COMPANY/DEPT\n") == ["OK seg=DEPT data=D1SALES1"]

    @pytest.mark.parametrize("ssas", ["GU\n", "GU DEPT\n", "GU COMPANY/EMP\n", "GU NOPE\n", "GU COMPANY(=\n"])
    def test_a_bad_path_is_ak(self, ssas):
        assert _statuses(ssas) == ["AK"]


class TestGetNextWithinParent:
    def test_gnp_stays_inside_the_parent_and_ends_with_ge(self):
        assert _statuses("GU COMPANY(=AC)/DEPT(=D1)\nGNP\nGNP\nGNP\nGNP\nGNP\n") == [
            "OK seg=DEPT data=D1SALES1", "OK seg=EMP data=E01SMITH0001", "OK seg=EMP data=E02JONES0002",
            "OK seg=PROJ data=A1BETA", "OK seg=PROJ data=P1ALPH", "GE"]

    def test_gnp_with_a_type_and_without_a_parent(self):
        assert _statuses("GNP\n") == ["GP"]
        assert _statuses("GU COMPANY(=AC)/DEPT(=D1)\nGNP PROJ\n")[1] == "OK seg=PROJ data=A1BETA"

    def test_a_gnp_does_not_move_the_parent(self):
        status = _statuses("GU COMPANY(=AC)/DEPT(=D1)\nGNP\nGNP\nGNP\nGNP\nGNP\n")
        assert status[-2:] == ["OK seg=PROJ data=P1ALPH", "GE"]  # bounded by DEPT D1, not the last child


class TestReplaceAndDelete:
    def test_repl_replaces_data_but_not_the_key(self):
        assert _statuses(
            "GU COMPANY(=AC)/DEPT(=D1)/EMP(=E01)\nREPL E01SMITH0099\nREPL E09SMITH0099\nREPL SHORT\n") == [
            "OK seg=EMP data=E01SMITH0001", "OK seg=EMP data=E01SMITH0099", "DA", "AK"]

    def test_repl_and_dlet_need_a_current_segment(self):
        assert run_script(DBD + "REPL E01SMITH0099\nDLET\n")[1:] == [
            "REPL E01SMITH0099 -> DJ", "DLET -> DJ"]

    def test_dlet_removes_the_segment_and_its_dependents_and_gn_continues(self):
        assert _statuses(
            "GU COMPANY(=AC)/DEPT(=D1)\nDLET\nDLET\nGU COMPANY(=AC)/DEPT(=D1)\nGN\nGN\n") == [
            "OK seg=DEPT data=D1SALES1", "OK", "DJ", "GE", "OK seg=DEPT data=D2LEGAL1", "GB"]

    def test_dlet_after_a_gn_removes_that_segment_and_the_next_gn_follows_the_hole(self):
        status = _statuses("GU COMPANY(=AC)\nGN EMP\nDLET\nGN EMP\n")
        assert status[1:] == ["OK seg=EMP data=E01SMITH0001", "OK", "OK seg=EMP data=E02JONES0002"]

    def test_an_unknown_function_is_ad(self):
        assert _statuses("FOO\n") == ["AD"]


def test_a_script_must_start_with_dbd():
    with pytest.raises(ValueError, match="starts with DBD"):
        run_script("GN\n")


def test_the_first_segment_type_must_be_the_root():
    with pytest.raises(ValueError, match="root"):
        run_script("DBD A:B:1:2\n")
