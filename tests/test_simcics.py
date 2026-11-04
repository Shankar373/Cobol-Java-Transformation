"""Roadmap unit 16: SIMCICS-1 specification -- the reference model's documented behaviour.

The Java library is held equal to this model by ``tests/integration/test_simcics_conformance.py``.
Records here are 13 characters: a 4-character key and 9 of data.
"""

from __future__ import annotations

import pytest

from engine.simulators.cics import SPEC_VERSION, run_script

SETUP = (
    "FILE ACCT 4 13 open\nFILE OLD 4 13 closed\n"
    "LOAD ACCT 0001ALICE0100\nLOAD ACCT 0003CAROL0300\n"
)
SETUP_LINES = len(SETUP.splitlines())


def _trace(body: str) -> list[str]:
    return run_script(SETUP + body)[SETUP_LINES:]


def _resp(body: str) -> list[str]:
    return [line.split(" -> ")[1] for line in _trace(body)]


class TestSetup:
    def test_the_setup_lines(self):
        assert run_script(SETUP) == [
            f"FILE ACCT 4 13 open -> {SPEC_VERSION}", f"FILE OLD 4 13 closed -> {SPEC_VERSION}",
            "LOAD ACCT 0001ALICE0100 -> loaded", "LOAD ACCT 0003CAROL0300 -> loaded"]

    def test_a_loaded_record_of_the_wrong_length_is_a_setup_error(self):
        with pytest.raises(ValueError, match="record is 5 characters"):
            run_script("FILE ACCT 4 13 open\nLOAD ACCT 00ABC\n")


class TestRead:
    def test_found_not_found_and_errors(self):
        assert _resp("READ ACCT 0001\nREAD ACCT 0002\nREAD ACCT 01\nREAD NOPE 0001\nREAD OLD 0001\n") == [
            "NORMAL data=0001ALICE0100", "NOTFND", "LENGERR", "FILENOTFOUND", "NOTOPEN"]


class TestWrite:
    def test_write_duplicate_and_bad_records(self):
        assert _resp(
            "WRITE ACCT 0002 0002BOB000200\nWRITE ACCT 0002 0002BOB000200\nWRITE ACCT 0005 0005XX\n"
            "WRITE ACCT 0006 0007ERIC06000\nWRITE ACCT 06 0006ERIC06000\nREAD ACCT 0002\nREAD ACCT 0006\n") == [
            "NORMAL", "DUPREC", "LENGERR", "INVREQ", "LENGERR", "NORMAL data=0002BOB000200", "NOTFND"]


class TestUpdate:
    def test_read_update_then_rewrite_releases_the_record(self):
        assert _resp(
            "READ ACCT 0001 UPDATE\nREWRITE ACCT 0001ALICE0150\nREWRITE ACCT 0001ALICE0151\nREAD ACCT 0001\n") == [
            "NORMAL data=0001ALICE0100", "NORMAL", "INVREQ", "NORMAL data=0001ALICE0150"]

    def test_rewrite_must_keep_the_key_and_the_length(self):
        assert _resp("READ ACCT 0001 UPDATE\nREWRITE ACCT 0009ALICE0150\nREWRITE ACCT 0001ALICE\n") == [
            "NORMAL data=0001ALICE0100", "INVREQ", "LENGERR"]

    def test_delete_uses_the_held_record_or_a_key(self):
        assert _resp(
            "DELETE ACCT\nREAD ACCT 0003 UPDATE\nDELETE ACCT\nDELETE ACCT 0001\nDELETE ACCT 0009\nREAD ACCT 0003\n") == [
            "INVREQ", "NORMAL data=0003CAROL0300", "NORMAL", "NORMAL", "NOTFND", "NOTFND"]


class TestBrowse:
    def test_forward_browse_from_a_generic_position(self):
        assert _resp("STARTBR ACCT 0002 GTEQ\nREADNEXT ACCT\nREADNEXT ACCT\nENDBR ACCT\n") == [
            "NORMAL", "NORMAL data=0003CAROL0300", "ENDFILE", "NORMAL"]

    def test_backward_browse_returns_the_records_before_the_start_key(self):
        assert _resp("STARTBR ACCT 0003 EQUAL\nREADPREV ACCT\nREADPREV ACCT\nENDBR ACCT\n") == [
            "NORMAL", "NORMAL data=0001ALICE0100", "ENDFILE", "NORMAL"]

    def test_browse_errors(self):
        assert _resp(
            "READNEXT ACCT\nSTARTBR ACCT 0099 GTEQ\nSTARTBR ACCT 0002 EQUAL\nSTARTBR ACCT 0001 EQUAL\n"
            "STARTBR ACCT 0001 EQUAL\nENDBR ACCT\nENDBR ACCT\n") == [
            "INVREQ", "NOTFND", "NOTFND", "NORMAL", "INVREQ", "NORMAL", "INVREQ"]

    def test_a_browse_sees_records_written_after_it_started(self):
        assert _resp(
            "STARTBR ACCT 0001 EQUAL\nREADNEXT ACCT\nWRITE ACCT 0002 0002BOB000200\nREADNEXT ACCT\n")[-1] == (
            "NORMAL data=0002BOB000200")


class TestRecovery:
    def test_rollback_undoes_writes_rewrites_and_deletes_in_reverse(self):
        script = (
            "WRITE ACCT 0002 0002BOB000200\nREAD ACCT 0001 UPDATE\nREWRITE ACCT 0001ALICE0999\n"
            "DELETE ACCT 0003\nSYNCPOINT ROLLBACK\nREAD ACCT 0002\nREAD ACCT 0001\nREAD ACCT 0003\n")
        assert _resp(script)[4:] == [
            "NORMAL", "NOTFND", "NORMAL data=0001ALICE0100", "NORMAL data=0003CAROL0300"]

    def test_syncpoint_commits_and_releases_a_held_record(self):
        script = "READ ACCT 0001 UPDATE\nSYNCPOINT\nREWRITE ACCT 0001ALICE0150\nSYNCPOINT ROLLBACK\n"
        assert _resp(script) == ["NORMAL data=0001ALICE0100", "NORMAL", "INVREQ", "NORMAL"]


class TestTemporaryStorage:
    def test_items_are_numbered_and_read_next_or_by_number(self):
        assert _resp(
            "WRITEQ Q1 aaa\nWRITEQ Q1 bbb\nREADQ Q1 NEXT\nREADQ Q1 NEXT\nREADQ Q1 NEXT\nREADQ Q1 1\n"
            "READQ NOQ 1\nREADQ Q1 0\n") == [
            "NORMAL item=1", "NORMAL item=2", "NORMAL item=1 data=aaa", "NORMAL item=2 data=bbb", "ITEMERR",
            "NORMAL item=1 data=aaa", "QIDERR", "ITEMERR"]

    def test_deleteq_and_rollback_of_a_queue_created_in_the_unit_of_work(self):
        # rollback restores the deleted queue, then un-writes its only item: the queue is gone again
        assert _resp("WRITEQ Q1 aaa\nDELETEQ Q1\nDELETEQ Q1\nSYNCPOINT ROLLBACK\nREADQ Q1 1\n") == [
            "NORMAL item=1", "NORMAL", "QIDERR", "NORMAL", "QIDERR"]
        # a committed item survives a later rolled-back delete
        assert _resp("WRITEQ Q3 x\nSYNCPOINT\nDELETEQ Q3\nSYNCPOINT ROLLBACK\nREADQ Q3 1\n")[-1] == (
            "NORMAL item=1 data=x")


def test_an_unknown_command_is_invreq():
    assert _resp("FROB ACCT\n") == ["INVREQ"]
