"""Roadmap unit 14: SIMMQ-1 specification -- the reference model's documented behaviour.

Each case is a script and the exact canonical trace the specification requires.  The Java library
is held equal to this model by ``tests/integration/test_simmq_conformance.py``.
"""

from __future__ import annotations

import pytest

from engine.simulators import IBM_VERIFIED, SIMULATOR_VERIFIED
from engine.simulators.mq import SPEC_VERSION, run_script
from engine.simulators.trace import MISMATCH, compare_traces

HEAD = "QMGR QM1 Q1,Q2,Q3\nCONN QM1\nOPEN 1 Q1 18\n"  # hconn 1, hobj 1: output + shared input


def _trace(body: str) -> list[str]:
    return run_script(HEAD + body)[3:]  # drop the three setup lines


class TestBasicFlow:
    def test_put_then_get_is_fifo_and_empty_ends_in_2033(self):
        assert _trace(
            "PUT 1 1 6161 0\nPUT 1 1 6262 0\nGET 1 1 10 0\nGET 1 1 10 0\nGET 1 1 10 0\n") == [
            "PUT 1 1 6161 0 -> 0 0", "PUT 1 1 6262 0 -> 0 0",
            "GET 1 1 10 0 -> 0 0 len=2 data=6161", "GET 1 1 10 0 -> 0 0 len=2 data=6262",
            "GET 1 1 10 0 -> 2 2033 len=0 data=-"]

    def test_the_setup_lines(self):
        assert run_script(HEAD) == [
            f"QMGR QM1 Q1,Q2,Q3 -> {SPEC_VERSION}", "CONN QM1 -> 0 0 h=1", "OPEN 1 Q1 18 -> 0 0 h=1"]

    def test_a_wait_on_an_empty_queue_is_no_message_available(self):
        assert _trace("GET 1 1 10 1\n") == ["GET 1 1 10 1 -> 2 2033 len=0 data=-"]

    def test_an_empty_message_round_trips(self):
        assert _trace("PUT 1 1 - 0\nGET 1 1 4 0\n") == [
            "PUT 1 1 - 0 -> 0 0", "GET 1 1 4 0 -> 0 0 len=0 data=-"]


class TestUnitOfWork:
    def test_a_syncpoint_put_is_invisible_to_others_until_commit(self):
        script = (
            "CONN QM1\nOPEN 2 Q1 2\nPUT 1 1 61 2\nDEPTH Q1\nGET 2 2 10 0\nCMIT 1\nDEPTH Q1\nGET 2 2 10 0\n")
        assert _trace(script) == [
            "CONN QM1 -> 0 0 h=2", "OPEN 2 Q1 2 -> 0 0 h=2", "PUT 1 1 61 2 -> 0 0",
            "DEPTH Q1 -> depth=0", "GET 2 2 10 0 -> 2 2033 len=0 data=-", "CMIT 1 -> 0 0",
            "DEPTH Q1 -> depth=1", "GET 2 2 10 0 -> 0 0 len=1 data=61"]

    def test_back_discards_provisional_puts(self):
        assert _trace("PUT 1 1 61 2\nBACK 1\nGET 1 1 10 0\n")[-1] == "GET 1 1 10 0 -> 2 2033 len=0 data=-"

    def test_back_returns_a_provisional_get_to_its_place(self):
        script = "PUT 1 1 61 0\nPUT 1 1 62 0\nGET 1 1 10 2\nBACK 1\nGET 1 1 10 0\nGET 1 1 10 0\n"
        assert _trace(script)[-2:] == [
            "GET 1 1 10 0 -> 0 0 len=1 data=61", "GET 1 1 10 0 -> 0 0 len=1 data=62"]

    def test_commit_makes_a_provisional_get_final(self):
        script = "PUT 1 1 61 0\nGET 1 1 10 2\nCMIT 1\nBACK 1\nGET 1 1 10 0\n"
        assert _trace(script)[-1] == "GET 1 1 10 0 -> 2 2033 len=0 data=-"

    def test_disconnect_commits(self):
        script = "PUT 1 1 61 2\nDISC 1\nCONN QM1\nOPEN 2 Q1 2\nGET 2 2 10 0\n"
        assert _trace(script)[-1] == "GET 2 2 10 0 -> 0 0 len=1 data=61"

    def test_a_connection_sees_its_own_uncommitted_put(self):
        assert _trace("PUT 1 1 61 2\nGET 1 1 10 0\n")[-1] == "GET 1 1 10 0 -> 0 0 len=1 data=61"


class TestGetOptions:
    def test_truncation_fails_without_the_option_and_keeps_the_message(self):
        assert _trace("PUT 1 1 68656c6c6f 0\nGET 1 1 2 0\nGET 1 1 10 0\n")[1:] == [
            "GET 1 1 2 0 -> 2 2080 len=5 data=6865", "GET 1 1 10 0 -> 0 0 len=5 data=68656c6c6f"]

    def test_accepted_truncation_is_a_warning_and_consumes_the_message(self):
        assert _trace("PUT 1 1 68656c6c6f 0\nGET 1 1 2 64\nGET 1 1 10 0\n")[1:] == [
            "GET 1 1 2 64 -> 1 2079 len=5 data=6865", "GET 1 1 10 0 -> 2 2033 len=0 data=-"]

    def test_browse_walks_without_removing(self):
        script = ("OPEN 1 Q2 24\nPUT 1 2 61 0\nPUT 1 2 62 0\nGET 1 2 10 16\nGET 1 2 10 32\n"
                  "GET 1 2 10 32\nGET 1 2 10 16\nDEPTH Q2\n")
        assert _trace(script)[3:] == [
            "GET 1 2 10 16 -> 0 0 len=1 data=61", "GET 1 2 10 32 -> 0 0 len=1 data=62",
            "GET 1 2 10 32 -> 2 2033 len=0 data=-", "GET 1 2 10 16 -> 0 0 len=1 data=61",
            "DEPTH Q2 -> depth=2"]

    @pytest.mark.parametrize("options", [128, 2 | 4, 16 | 32, 16 | 2])
    def test_bad_get_options_fail_with_2046(self, options):
        assert _trace(f"GET 1 1 10 {options}\n") == [f"GET 1 1 10 {options} -> 2 2046 len=0 data=-"]


class TestOpenAndHandles:
    def test_unknown_queue_bad_connection_and_bad_object_handle(self):
        assert _trace("OPEN 1 NOPE 2\nOPEN 9 Q1 2\nGET 9 1 5 0\nGET 1 9 5 0\nCLOSE 1 9\n") == [
            "OPEN 1 NOPE 2 -> 2 2085 h=0", "OPEN 9 Q1 2 -> 2 2018 h=0", "GET 9 1 5 0 -> 2 2018 len=0 data=-",
            "GET 1 9 5 0 -> 2 2019 len=0 data=-", "CLOSE 1 9 -> 2 2019"]

    def test_a_queue_manager_name_must_match(self):
        assert run_script("QMGR QM1 Q1\nCONN OTHER\nCONN\n")[1:] == [
            "CONN OTHER -> 2 2058 h=0", "CONN -> 0 0 h=1"]

    def test_exclusive_input_excludes_other_input_until_closed(self):
        script = ("CONN QM1\nOPEN 2 Q2 4\nOPEN 1 Q2 2\nOPEN 1 Q2 4\nCLOSE 2 2\nOPEN 1 Q2 4\n")
        assert _trace(script)[1:] == [
            "OPEN 2 Q2 4 -> 0 0 h=2", "OPEN 1 Q2 2 -> 2 2042 h=0", "OPEN 1 Q2 4 -> 2 2042 h=0",
            "CLOSE 2 2 -> 0 0", "OPEN 1 Q2 4 -> 0 0 h=3"]

    @pytest.mark.parametrize("options", [0, 1, 2 | 4, 64])
    def test_bad_open_options_fail_with_2046(self, options):
        assert _trace(f"OPEN 1 Q2 {options}\n") == [f"OPEN 1 Q2 {options} -> 2 2046 h=0"]

    def test_the_open_mode_limits_the_calls(self):
        script = "OPEN 1 Q3 16\nOPEN 1 Q3 2\nGET 1 2 5 0\nPUT 1 3 61 0\nGET 1 2 5 16\n"
        assert _trace(script)[2:] == [
            "GET 1 2 5 0 -> 2 2037 len=0 data=-", "PUT 1 3 61 0 -> 2 2039", "GET 1 2 5 16 -> 2 2036 len=0 data=-"]


class TestQueueLimits:
    def test_inhibits_and_depth_limit(self):
        script = ("SETQ Q1 2 0 0\nPUT 1 1 61 0\nPUT 1 1 62 0\nPUT 1 1 63 0\nSETQ Q1 2 1 1\nPUT 1 1 64 0\n"
                  "GET 1 1 5 0\nSETQ Q1 2 0 0\nGET 1 1 5 0\n")
        assert _trace(script) == [
            "SETQ Q1 2 0 0 -> ok", "PUT 1 1 61 0 -> 0 0", "PUT 1 1 62 0 -> 0 0", "PUT 1 1 63 0 -> 2 2053",
            "SETQ Q1 2 1 1 -> ok", "PUT 1 1 64 0 -> 2 2051", "GET 1 1 5 0 -> 2 2016 len=0 data=-",
            "SETQ Q1 2 0 0 -> ok", "GET 1 1 5 0 -> 0 0 len=1 data=61"]


class TestTraceAndVerdict:
    def test_equal_traces_are_simulator_verified_and_never_ibm_verified(self):
        trace = _trace("PUT 1 1 61 0\n")
        diff = compare_traces(trace, list(trace))
        assert diff.equal and diff.verdict == SIMULATOR_VERIFIED != IBM_VERIFIED

    def test_the_first_divergence_is_located(self):
        diff = compare_traces(["a", "b", "c"], ["a", "x", "c"])
        assert (diff.equal, diff.index, diff.left, diff.right, diff.verdict) == (False, 1, "b", "x", MISMATCH)

    def test_a_shorter_trace_is_a_mismatch(self):
        diff = compare_traces(["a", "b"], ["a"])
        assert not diff.equal and diff.right == "<end of trace>" and diff.verdict == MISMATCH

    def test_an_empty_trace_never_verifies(self):
        assert compare_traces([], []).verdict == MISMATCH

    def test_a_script_must_start_with_qmgr(self):
        with pytest.raises(ValueError, match="starts with QMGR"):
            run_script("CONN QM1\n")
