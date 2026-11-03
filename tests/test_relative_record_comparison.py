"""RELATIVE files are compared by their records (Phase 3).

GnuCOBOL 3.1.2 writes one slot per RRN — an 8-byte little-endian record
size and the whole record area, RRN ``n`` at ``(n - 1) * (8 + length)``;
size 0 marks an empty or DELETEd slot.  The generated Java runtime used to
keep RELATIVE records in memory only, so the oracle's image was always
INCONCLUSIVE and every program writing a RELATIVE file was PARTIAL.  It
now persists ``<file>.rel`` after every change, and the pipeline compares
(RRN, record) pairs byte-exactly; an image whose slot layout is not
unambiguous (e.g. every record deleted) stays INCONCLUSIVE.  The Java
runtime also reports WRITE onto an occupied RRN as ``22`` like GnuCOBOL
(it overwrote the record before).

Test data (``tests/data/relative``) was produced by GnuCOBOL 3.1.2 from
``RELPROBE.cob``: ``GAP.DAT`` (writes at RRN 2/5/7, 5 deleted then
rewritten, 7 rewritten), ``SEQ.DAT`` (sequential-access writes),
``NONE.DAT`` (its only record deleted).  ``RELREAD.cob`` is GnuCOBOL's own
READ NEXT of ``GAP.DAT``; the Docker test regenerates both and compares.
"""

from __future__ import annotations

import os
import shutil
import struct
import subprocess
from pathlib import Path

import pytest

from engine.comparators.indexed_records import (
    UnreadableImage,
    canonical_relative_records,
    emulated_relative_records,
    gnucobol_relative_records,
)
from engine.domain.identities import VerdictState
from engine.evidence.integrity import EvidenceIntegrityValidator, ValidatedEvidenceManifest
from engine.transformation.producer import TransformationProducer
from tests.record_pipeline_support import _SOURCE, _file_results, _run

DATA = Path(__file__).parent / "data" / "relative"
ORACLE_IMAGE = "gnucobol-ocesql:latest"
GAP_RECORDS = [(2, b"TWO   "), (5, b"AGAIN "), (7, b"SEVEN7")]

#: GnuCOBOL's READ NEXT of GAP.DAT (RELREAD.cob), pinned.
GAP_READ_NEXT = "0002|TWO   |\n0005|AGAIN |\n0007|SEVEN7|\n"


def _image(name: str) -> bytes:
    return (DATA / name).read_bytes()


def _slots(records: dict[int, bytes], length: int, deleted: dict[int, bytes] = {}) -> bytes:
    last = max([*records, *deleted])
    out = bytearray()
    for rrn in range(1, last + 1):
        if rrn in records:
            out += struct.pack("<Q", length) + records[rrn]
        else:
            out += struct.pack("<Q", 0) + deleted.get(rrn, bytes(length))
    return bytes(out)


def _emulation(records: list[tuple[int, bytes]]) -> bytes:
    return b"R\n" + b"".join(b"%d\x01%s\n" % (rrn, data) for rrn, data in records)


class TestGnuCobolReader:
    def test_gaps_deletes_and_rewrites_match_gnucobol_read_next(self) -> None:
        records = gnucobol_relative_records(_image("GAP.DAT"))
        assert records == GAP_RECORDS
        shown = "".join(f"{rrn:04d}|{data.decode()}|\n" for rrn, data in records)
        assert shown == GAP_READ_NEXT

    def test_sequential_access_writes(self) -> None:
        assert gnucobol_relative_records(_image("SEQ.DAT")) == [(1, b"AAAA"), (2, b"BB  ")]

    def test_empty_file_has_no_records(self) -> None:
        assert gnucobol_relative_records(b"") == []

    def test_deleted_slot_bytes_are_not_records(self) -> None:
        image = _slots({2: b"LIVE"}, 4, deleted={1: b"GONE"})
        assert gnucobol_relative_records(image) == [(2, b"LIVE")]

    def test_no_live_slot_is_refused(self) -> None:
        with pytest.raises(UnreadableImage, match="no RELATIVE slot layout"):
            gnucobol_relative_records(_image("NONE.DAT"))

    @pytest.mark.parametrize(
        "image",
        [
            _image("GAP.DAT")[:-1],                                   # truncated
            struct.pack("<Q", 6) + b"ABCDEF" + struct.pack("<Q", 5) + b"ABCDEF",  # mixed sizes
            b"\x01" * 40,                                             # not slots
        ],
    )
    def test_malformed_image_is_refused(self, image: bytes) -> None:
        with pytest.raises(UnreadableImage):
            gnucobol_relative_records(image)

    def test_ambiguous_layout_is_refused(self) -> None:
        # 48 bytes that read both as 16-byte slots (record length 8: sizes
        # 0, 8, 0 at offsets 0/16/32) and as 24-byte slots (record length
        # 16: sizes 0, 16 at offsets 0/24).  Neither reading can be trusted.
        image = bytearray(48)
        struct.pack_into("<Q", image, 16, 8)
        struct.pack_into("<Q", image, 24, 16)
        with pytest.raises(UnreadableImage, match="several"):
            gnucobol_relative_records(bytes(image))


class TestEmulationReader:
    def test_records_by_rrn(self) -> None:
        assert emulated_relative_records(_emulation(GAP_RECORDS)) == GAP_RECORDS

    def test_no_records(self) -> None:
        assert emulated_relative_records(b"R\n") == []

    @pytest.mark.parametrize(
        "image",
        [b"", b"K4\n", b"R\n2\x01A\n1\x01B\n", b"R\n0\x01A\n", b"R\nX\x01A\n",
         b"R\n2A\n", b"R\n2\x01A"],
    )
    def test_malformed_emulation_is_refused(self, image: bytes) -> None:
        with pytest.raises(UnreadableImage):
            emulated_relative_records(image)

    def test_canonical_form_carries_the_rrn(self) -> None:
        assert canonical_relative_records([(7, b"A\x00")]) == b"7\t4100\tA.\n"


# ---------------------------------------------------------------------------
# Pipeline: what the verdict says
# ---------------------------------------------------------------------------

_RELATIVE_SOURCE = _SOURCE.replace(
    "ORGANIZATION IS INDEXED\n               RECORD KEY IS IDX-KEY.",
    "ORGANIZATION IS RELATIVE.",
)


def _relative_run(tmp_path: Path, candidate_records, oracle_image=None):
    return _run(
        tmp_path,
        {"workspace/IDX.DAT": oracle_image if oracle_image is not None else _image("GAP.DAT")},
        {"workspace/IDX.DAT.rel": _emulation(candidate_records)},
        _RELATIVE_SOURCE,
    )


class TestPipeline:
    def test_equal_records_verify(self, tmp_path: Path) -> None:
        result = _relative_run(tmp_path, GAP_RECORDS)
        assert _file_results(result) == {"workspace/IDX.DAT#records": "MATCH"}
        assert result.verdict.state == VerdictState.VERIFIED
        validated = EvidenceIntegrityValidator().validate(result.evidence_manifest)
        assert isinstance(validated, ValidatedEvidenceManifest)

    @pytest.mark.parametrize(
        "records",
        [
            [(2, b"TWO   "), (5, b"AGAIN!"), (7, b"SEVEN7")],   # content
            [(2, b"TWO   "), (6, b"AGAIN "), (7, b"SEVEN7")],   # wrong RRN
            [(2, b"TWO   "), (7, b"SEVEN7")],                   # missing
            [*GAP_RECORDS, (9, b"EXTRA ")],                     # extra
            [(2, b"TWO   "), (5, b"SEVEN7"), (7, b"AGAIN ")],   # swapped
        ],
    )
    def test_different_records_fail(self, tmp_path: Path, records) -> None:
        result = _relative_run(tmp_path, records)
        assert _file_results(result) == {"workspace/IDX.DAT#records": "MISMATCH"}
        assert result.verdict.state == VerdictState.FAILED

    def test_unreadable_oracle_image_stays_inconclusive(self, tmp_path: Path) -> None:
        result = _relative_run(tmp_path, [], oracle_image=_image("NONE.DAT"))
        assert set(_file_results(result).values()) == {"INCONCLUSIVE"}
        assert result.verdict.state == VerdictState.PARTIAL

    def test_indexed_emulation_for_a_relative_file_stays_inconclusive(self, tmp_path: Path) -> None:
        result = _run(
            tmp_path,
            {"workspace/IDX.DAT": _image("GAP.DAT")},
            {"workspace/IDX.DAT.idx": b"K4\n"},
            _RELATIVE_SOURCE,
        )
        assert set(_file_results(result).values()) == {"INCONCLUSIVE"}
        assert result.verdict.state == VerdictState.PARTIAL


# ---------------------------------------------------------------------------
# The generated Java runtime (needs a JDK)
# ---------------------------------------------------------------------------

def _run_java(source: str, tmp_path: Path) -> subprocess.CompletedProcess:
    if not (shutil.which("javac") and shutil.which("java")):
        if os.environ.get("RUN_DOCKER_TESTS") == "1":
            pytest.fail("javac/java not on PATH: the Docker lane requires a JDK")
        pytest.skip("javac/java not on PATH")
    result = TransformationProducer().transform(source, "PROBE")
    assert result.success is True, result.errors
    for generated in result.generated_files:
        (tmp_path / generated.filename).write_text(generated.source_code, encoding="utf-8")
    compiled = subprocess.run(
        ["javac", "-nowarn", "-d", str(tmp_path),
         *[str(tmp_path / g.filename) for g in result.generated_files]],
        capture_output=True, timeout=120,
    )
    assert compiled.returncode == 0, compiled.stderr.decode(errors="replace")
    return subprocess.run(
        ["java", "-Dline.separator=\n", "-cp", str(tmp_path),
         result.generated_files[0].class_name],
        capture_output=True, timeout=60, cwd=tmp_path,
    )


_DUPLICATE_WRITE = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. DUP.\n"
    "       ENVIRONMENT DIVISION.\n"
    "       INPUT-OUTPUT SECTION.\n"
    "       FILE-CONTROL.\n"
    '           SELECT R-FILE ASSIGN TO "DUP.DAT"\n'
    "               ORGANIZATION IS RELATIVE\n"
    "               RELATIVE KEY IS WS-RRN\n"
    "               ACCESS MODE IS RANDOM\n"
    "               FILE STATUS IS WS-ST.\n"
    "       DATA DIVISION.\n"
    "       FILE SECTION.\n"
    "       FD  R-FILE.\n"
    "       01  R-REC                PIC X(4).\n"
    "       WORKING-STORAGE SECTION.\n"
    "       01  WS-RRN               PIC 9(4).\n"
    "       01  WS-ST                PIC XX.\n"
    "       PROCEDURE DIVISION.\n"
    "       MAIN-LOGIC.\n"
    "           OPEN OUTPUT R-FILE\n"
    "           MOVE 3 TO WS-RRN\n"
    "           MOVE 'AAAA' TO R-REC\n"
    "           WRITE R-REC INVALID KEY DISPLAY 'INV1'\n"
    "           END-WRITE\n"
    "           DISPLAY 'W1 ' WS-ST\n"
    "           MOVE 'BBBB' TO R-REC\n"
    "           WRITE R-REC INVALID KEY DISPLAY 'INV2'\n"
    "           END-WRITE\n"
    "           DISPLAY 'W2 ' WS-ST\n"
    "           CLOSE R-FILE\n"
    "           STOP RUN.\n"
)
#: GnuCOBOL 3.1.2: the second WRITE is INVALID KEY (22) and keeps AAAA.
_DUPLICATE_STDOUT = "W1 00\nINV2\nW2 22\n"


def _missing_files(select_word: str = "SELECT") -> str:
    return (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. MISS.\n"
        "       ENVIRONMENT DIVISION.\n"
        "       INPUT-OUTPUT SECTION.\n"
        "       FILE-CONTROL.\n"
        f'           {select_word} R-FILE ASSIGN TO "NOREL.DAT"\n'
        "               ORGANIZATION IS RELATIVE\n"
        "               RELATIVE KEY IS WS-RRN\n"
        "               ACCESS MODE IS DYNAMIC\n"
        "               FILE STATUS IS WS-ST.\n"
        '           SELECT I-FILE ASSIGN TO "NOIDX.DAT"\n'
        "               ORGANIZATION IS INDEXED\n"
        "               RECORD KEY IS I-KEY\n"
        "               ACCESS MODE IS DYNAMIC\n"
        "               FILE STATUS IS WS-ST.\n"
        '           SELECT S-FILE ASSIGN TO "NOSEQ.TXT"\n'
        "               ORGANIZATION IS LINE SEQUENTIAL\n"
        "               FILE STATUS IS WS-ST.\n"
        "       DATA DIVISION.\n"
        "       FILE SECTION.\n"
        "       FD  R-FILE.\n"
        "       01  R-REC                PIC X(4).\n"
        "       FD  I-FILE.\n"
        "       01  I-REC.\n"
        "           05  I-KEY            PIC X(4).\n"
        "       FD  S-FILE.\n"
        "       01  S-REC                PIC X(4).\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01  WS-RRN               PIC 9(4).\n"
        "       01  WS-ST                PIC XX.\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-LOGIC.\n"
        "           OPEN INPUT R-FILE\n"
        "           DISPLAY 'REL INPUT ' WS-ST\n"
        "           OPEN I-O R-FILE\n"
        "           DISPLAY 'REL I-O ' WS-ST\n"
        "           OPEN INPUT I-FILE\n"
        "           DISPLAY 'IDX INPUT ' WS-ST\n"
        "           OPEN I-O I-FILE\n"
        "           DISPLAY 'IDX I-O ' WS-ST\n"
        "           OPEN INPUT S-FILE\n"
        "           DISPLAY 'SEQ INPUT ' WS-ST\n"
        "           OPEN EXTEND S-FILE\n"
        "           DISPLAY 'SEQ EXTEND ' WS-ST\n"
        "           STOP RUN.\n"
    )


#: GnuCOBOL 3.1.2: opening a file that does not exist is status 35 for
#: every organization (the Java runtime said 00, or 23 for sequential).
_MISSING_STDOUT = (
    "REL INPUT 35\nREL I-O 35\nIDX INPUT 35\nIDX I-O 35\n"
    "SEQ INPUT 35\nSEQ EXTEND 35\n"
)


def test_java_runtime_reports_missing_files_like_gnucobol(tmp_path: Path) -> None:
    run = _run_java(_missing_files(), tmp_path)
    assert run.returncode == 0, run.stderr.decode(errors="replace")
    assert run.stdout.decode() == _MISSING_STDOUT


def test_optional_file_fails_closed() -> None:
    result = TransformationProducer().transform(_missing_files("SELECT OPTIONAL"), "PROBE")
    assert result.success is False
    assert any("SELECT OPTIONAL R-FILE" in e for e in result.errors), result.errors


def test_java_runtime_persists_relative_records(tmp_path: Path) -> None:
    run = _run_java(_DUPLICATE_WRITE, tmp_path)
    assert run.returncode == 0, run.stderr.decode(errors="replace")
    assert run.stdout.decode() == _DUPLICATE_STDOUT
    image = (tmp_path / "DUP.DAT.rel").read_bytes()
    assert emulated_relative_records(image) == [(3, b"AAAA")]


# ---------------------------------------------------------------------------
# Docker lane: the oracle itself
# ---------------------------------------------------------------------------

def _gnucobol(script: str, tmp_path: Path, sources: dict[str, str]) -> subprocess.CompletedProcess:
    if os.environ.get("RUN_DOCKER_TESTS") != "1":
        pytest.skip("Docker lane test: set RUN_DOCKER_TESTS=1 to run it")
    for name, text in sources.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    os.chmod(tmp_path, 0o777)
    run = subprocess.run(
        ["docker", "run", "--rm", "--network", "none", "-v", f"{tmp_path}:/src",
         ORACLE_IMAGE, "sh", "-c", f"cd /tmp && cp /src/*.cob . && {script}"],
        capture_output=True, timeout=300,
    )
    assert run.returncode == 0, run.stderr.decode(errors="replace")
    return run


def test_reader_matches_gnucobol_on_a_fresh_image(tmp_path: Path) -> None:
    run = _gnucobol(
        "cobc -x RELPROBE.cob && cobc -x RELREAD.cob && ./RELPROBE > /dev/null"
        " && cp GAP.DAT /src/ && chmod a+r /src/GAP.DAT && ./RELREAD",
        tmp_path,
        {name: (DATA / name).read_text() for name in ("RELPROBE.cob", "RELREAD.cob")},
    )
    assert run.stdout.decode() == GAP_READ_NEXT
    assert (tmp_path / "GAP.DAT").read_bytes() == _image("GAP.DAT")
    assert gnucobol_relative_records((tmp_path / "GAP.DAT").read_bytes()) == GAP_RECORDS


def test_duplicate_write_pin(tmp_path: Path) -> None:
    run = _gnucobol("cobc -x DUP.cob && ./DUP", tmp_path, {"DUP.cob": _DUPLICATE_WRITE})
    assert run.stdout.decode() == _DUPLICATE_STDOUT


def test_missing_file_pin(tmp_path: Path) -> None:
    run = _gnucobol("cobc -x MISS.cob && ./MISS", tmp_path, {"MISS.cob": _missing_files()})
    assert run.stdout.decode() == _MISSING_STDOUT
