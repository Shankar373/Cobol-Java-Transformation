"""INDEXED files are compared by their records (Phase 3).

GnuCOBOL stores an INDEXED file as a Berkeley DB B-tree and the generated
Java runtime as its own emulation (``<file>.idx``): the two images can never
be byte-identical, so both used to be INCONCLUSIVE and every program writing
an INDEXED file was PARTIAL at best.  The pipeline now reads the logical
records from each image — the oracle's straight from the Berkeley DB pages,
with no use of the COBOL parser or the generated runtime — and compares
them byte-exactly in key order.  An image the reader does not certify
(overflow or duplicate items, encryption, an unknown page type, anything
malformed) keeps the old INCONCLUSIVE result; RELATIVE files are unchanged.

Test data (``tests/data/indexed_bdb``) was produced by GnuCOBOL 3.1.2:
``MANY.DAT`` by ``MANY.cob`` (400 writes in descending key order, every 7th
deleted, every 5th rewritten — a multi-level tree), whose own sequential
read is ``MANY.expected``; ``BIG.DAT`` by ``BIG.cob`` (6,000-byte records,
stored as overflow items); ``IDXFILE.DAT`` / ``DELETE.DAT`` by the
``workload-indexed-file`` / ``workload-delete`` fixtures.  The Docker test
regenerates ``MANY.DAT`` and checks the reader against GnuCOBOL again.
"""

from __future__ import annotations

import os
import struct
import subprocess
from pathlib import Path

import pytest

from api.workload_contract import default_contract
from engine.comparators.indexed_records import (
    UnreadableImage,
    bdb_btree_records,
    canonical_records,
    emulated_index_records,
)
from engine.domain.identities import VerdictState
from engine.evidence.integrity import EvidenceIntegrityValidator, ValidatedEvidenceManifest
from engine.pipeline import PipelineConfig, VerticalSlicePipeline
from tests.test_comparison_contract_strength import _Candidate, _Oracle

DATA = Path(__file__).parent / "data" / "indexed_bdb"
ORACLE_IMAGE = "gnucobol-ocesql:latest"


def _image(name: str) -> bytes:
    return (DATA / name).read_bytes()


def _emulation(records: list[bytes], key_length: int = 4) -> bytes:
    lines = [f"K{key_length}\n"]
    for record in records:
        text = record.decode("ascii")
        lines.append(f"{text[:key_length]}\x01{text[key_length:]}\n")
    return "".join(lines).encode("utf-8")


class TestBerkeleyDbReader:
    def test_multi_level_tree_matches_gnucobol_sequential_read(self) -> None:
        expected = [line.encode() for line in (DATA / "MANY.expected").read_text().splitlines()]
        assert bdb_btree_records(_image("MANY.DAT")) == expected
        assert len(expected) == 343  # 400 written, 57 deleted

    def test_rewrite_and_delete_are_reflected(self) -> None:
        assert bdb_btree_records(_image("IDXFILE.DAT")) == [
            b"K002REC-TWO-UPDATED---- ", b"K003RECORD-THREE-DATA---",
        ]
        assert bdb_btree_records(_image("DELETE.DAT")) == [b"K002RECORD-TWO-KEEP---- "]

    def test_overflow_items_are_refused(self) -> None:
        with pytest.raises(UnreadableImage, match="overflow"):
            bdb_btree_records(_image("BIG.DAT"))

    @pytest.mark.parametrize(
        ("offset", "value", "message"),
        [
            (12, b"\x00\x00\x00\x00", "Berkeley DB"),     # magic
            (16, b"\x08\x00\x00\x00", "version"),        # format version
            (24, b"\x01", "encrypted"),                  # encryption algorithm
            (25, b"\x05", "metadata"),                   # page 0 type
            (4096 + 25, b"\x07", "type"),                # root page type
            (4096 + 8, b"\x09\x00\x00\x00", "header"),  # root page number
        ],
    )
    def test_anything_unexpected_is_refused(self, offset, value, message) -> None:
        image = bytearray(_image("IDXFILE.DAT"))
        image[offset:offset + len(value)] = value
        with pytest.raises(UnreadableImage, match=message):
            bdb_btree_records(bytes(image))

    def test_truncated_image_is_refused(self) -> None:
        with pytest.raises(UnreadableImage):
            bdb_btree_records(_image("IDXFILE.DAT")[:5000])

    def test_item_offset_outside_the_page_is_refused(self) -> None:
        image = bytearray(_image("IDXFILE.DAT"))
        struct.pack_into("<H", image, 4096 + 26, 4095)
        with pytest.raises(UnreadableImage, match="outside"):
            bdb_btree_records(bytes(image))


class TestEmulationReader:
    def test_records_are_key_plus_data(self) -> None:
        records = [b"K001ALPHA", b"K002BETA "]
        assert emulated_index_records(_emulation(records)) == records

    @pytest.mark.parametrize("image", [b"", b"X4\nK001\x01A\n", b"K4\nK01\x01A\n", b"K4\nK001A\n", b"K4\nK001\x01A"])
    def test_malformed_emulation_is_refused(self, image: bytes) -> None:
        with pytest.raises(UnreadableImage):
            emulated_index_records(image)

    def test_canonical_form_is_byte_exact_and_readable(self) -> None:
        assert canonical_records([b"K1\x00A"]) == b"4b310041\tK1.A\n"


# ---------------------------------------------------------------------------
# Pipeline: what the verdict says
# ---------------------------------------------------------------------------

_SOURCE = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. MAIN.\n"
    "       ENVIRONMENT DIVISION.\n"
    "       INPUT-OUTPUT SECTION.\n"
    "       FILE-CONTROL.\n"
    '           SELECT IDX-FILE ASSIGN TO "IDX.DAT"\n'
    "               ORGANIZATION IS INDEXED\n"
    "               RECORD KEY IS IDX-KEY.\n"
    "       PROCEDURE DIVISION.\n"
    "           DISPLAY 'HI'.\n"
    "           STOP RUN.\n"
)
_RECORDS = [b"K002REC-TWO-UPDATED---- ", b"K003RECORD-THREE-DATA---"]


def _run(tmp_path: Path, oracle_files, candidate_files, source: str = _SOURCE):
    src = tmp_path / "MAIN.cob"
    src.write_text(source, encoding="latin-1")
    cand = tmp_path / "cand"
    cand.mkdir()
    (cand / "Main.java").write_text("class Main {}", encoding="utf-8")
    pipe = VerticalSlicePipeline(
        PipelineConfig(
            workload_id="wl-idx",
            cobol_source_path=str(src),
            java_candidate_path=str(cand),
            java_entrypoint="Main",
            workload=default_contract("wl-idx").workload,
        ),
        candidate_adapter=_Candidate(b"HI\n", candidate_files, 0),
    )
    pipe._oracle_adapter = _Oracle(b"HI\n", oracle_files, 0)
    return pipe.run()


def _file_results(result) -> dict[str, str]:
    return {
        c.comparison_id.split(":", 1)[1].rsplit("-run-", 1)[0]: c.result
        for c in result.comparison_evidence
        if ":" in c.comparison_id and c.artifact_type == "TEXT_FILE"
    }


class TestPipeline:
    def test_equal_records_verify(self, tmp_path: Path) -> None:
        result = _run(
            tmp_path,
            {"workspace/IDX.DAT": _image("IDXFILE.DAT")},
            {"workspace/IDX.DAT.idx": _emulation(_RECORDS)},
        )
        assert _file_results(result) == {"workspace/IDX.DAT#records": "MATCH"}
        assert result.verdict.state == VerdictState.VERIFIED
        validated = EvidenceIntegrityValidator().validate(result.evidence_manifest)
        assert isinstance(validated, ValidatedEvidenceManifest)

    @pytest.mark.parametrize(
        "records",
        [
            [b"K002REC-TWO-UPDATED---X ", b"K003RECORD-THREE-DATA---"],  # content
            [b"K002REC-TWO-UPDATED---- "],                               # missing
            [*_RECORDS, b"K004EXTRA-------------- "],                    # extra
            [b"K003RECORD-THREE-DATA---", b"K002REC-TWO-UPDATED---- "],  # order
        ],
    )
    def test_different_records_fail(self, tmp_path: Path, records) -> None:
        result = _run(
            tmp_path,
            {"workspace/IDX.DAT": _image("IDXFILE.DAT")},
            {"workspace/IDX.DAT.idx": _emulation(records)},
        )
        assert _file_results(result) == {"workspace/IDX.DAT#records": "MISMATCH"}
        assert result.verdict.state == VerdictState.FAILED

    def test_unreadable_oracle_image_stays_inconclusive(self, tmp_path: Path) -> None:
        result = _run(
            tmp_path,
            {"workspace/IDX.DAT": _image("BIG.DAT")},
            {"workspace/IDX.DAT.idx": _emulation(_RECORDS)},
        )
        assert set(_file_results(result).values()) == {"INCONCLUSIVE"}
        assert result.verdict.state == VerdictState.PARTIAL

    def test_relative_file_stays_inconclusive(self, tmp_path: Path) -> None:
        source = _SOURCE.replace(
            "ORGANIZATION IS INDEXED\n               RECORD KEY IS IDX-KEY.",
            "ORGANIZATION IS RELATIVE.",
        )
        result = _run(
            tmp_path,
            {"workspace/IDX.DAT": _image("IDXFILE.DAT")},
            {"workspace/IDX.DAT.idx": _emulation(_RECORDS)},
            source,
        )
        assert set(_file_results(result).values()) == {"INCONCLUSIVE"}
        assert result.verdict.state == VerdictState.PARTIAL

    def test_image_on_one_side_only_stays_inconclusive(self, tmp_path: Path) -> None:
        result = _run(tmp_path, {"workspace/IDX.DAT": _image("IDXFILE.DAT")}, {})
        assert result.verdict.state != VerdictState.VERIFIED


def test_reader_matches_gnucobol_on_a_fresh_image(tmp_path: Path) -> None:
    """Docker lane: rebuild MANY.DAT with GnuCOBOL and compare again."""
    if os.environ.get("RUN_DOCKER_TESTS") != "1":
        pytest.skip("Docker lane test: set RUN_DOCKER_TESTS=1 to run it")
    (tmp_path / "MANY.cob").write_bytes((DATA / "MANY.cob").read_bytes())
    os.chmod(tmp_path, 0o777)
    run = subprocess.run(
        ["docker", "run", "--rm", "--network", "none", "-v", f"{tmp_path}:/src",
         ORACLE_IMAGE, "sh", "-c",
         "cd /tmp && cobc -x /src/MANY.cob -o many && ./many > /src/expected"
         " && cp MANY.DAT /src/ && chmod a+r /src/MANY.DAT /src/expected"],
        capture_output=True, timeout=180,
    )
    assert run.returncode == 0, run.stderr.decode(errors="replace")
    expected = [line.encode() for line in (tmp_path / "expected").read_text().splitlines()]
    assert bdb_btree_records((tmp_path / "MANY.DAT").read_bytes()) == expected
