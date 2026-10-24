"""Deterministic contracts for indexed/relative FILE-CONTROL lowering.

The runtime equivalence proof is Docker-gated in
``tests/integration/test_indexed_relative_oracle_proof.py``.  These tests always
run and pin the honest classification:

* ORGANIZATION INDEXED / RELATIVE, ACCESS DYNAMIC and RECORD KEY are SUPPORTED
  for the certified subset (primary RECORD KEY at offset 0, ACCESS MODE
  DYNAMIC, no ALTERNATE RECORD KEY) — lowered and oracle-proven byte-identical
  to GnuCOBOL 3.1.2 for behavior (stdout, FILE STATUS, exit code), while the
  on-disk representation stays an emulation, not VSAM, and file-image
  equivalence is never claimed;
* an unparsed SELECT phrase fails closed (source-only UNSUPPORTED);
* ALTERNATE RECORD KEY is parsed, diagnosed and classified UNSUPPORTED because
  no alternate index is built;
* the parser records the SELECT metadata on FileDefinition, which is what the
  analyzer and mapper consume.
"""

from __future__ import annotations

from pathlib import Path

from engine.modernization.capability_analyzer import CapabilityAnalyzer, CapabilityLevel
from engine.transformation.application_discovery import ApplicationDiscovery
from engine.transformation.cobol_parser import CobolParser
from engine.transformation.ir import FileAccessMode, FileOrganization
from engine.transformation.semantic_capability import (
    CONSTRUCT_REGISTRY,
    CapabilityLevel as RegistryLevel,
)

FILE_CONTROL_KEYS = (
    "ORGANIZATION INDEXED",
    "ORGANIZATION RELATIVE",
    "ACCESS DYNAMIC",
    "RECORD KEY",
)

HEADER = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. {pid}.\n"
)

INDEXED = HEADER.format(pid="IDXDEMO") + (
    "       ENVIRONMENT DIVISION.\n"
    "       INPUT-OUTPUT SECTION.\n"
    "       FILE-CONTROL.\n"
    "           SELECT IDX-FILE ASSIGN TO \"IDX.DAT\"\n"
    "               ORGANIZATION IS INDEXED\n"
    "               ACCESS MODE IS DYNAMIC\n"
    "               RECORD KEY IS IDX-KEY\n"
    "               FILE STATUS IS WS-STATUS.\n"
    "       DATA DIVISION.\n"
    "       FILE SECTION.\n"
    "       FD  IDX-FILE.\n"
    "       01  IDX-REC.\n"
    "           05  IDX-KEY  PIC X(4).\n"
    "           05  IDX-DATA PIC X(10).\n"
    "       WORKING-STORAGE SECTION.\n"
    "       01  WS-STATUS PIC XX.\n"
    "       PROCEDURE DIVISION.\n"
    "           OPEN INPUT IDX-FILE.\n"
    "           CLOSE IDX-FILE.\n"
    "           STOP RUN.\n"
)

INDEXED_WITH_ALTERNATE = INDEXED.replace(
    "               RECORD KEY IS IDX-KEY\n",
    "               RECORD KEY IS IDX-KEY\n"
    "               ALTERNATE RECORD KEY IS IDX-DATA\n",
)

RELATIVE = HEADER.format(pid="RELDEMO") + (
    "       ENVIRONMENT DIVISION.\n"
    "       INPUT-OUTPUT SECTION.\n"
    "       FILE-CONTROL.\n"
    "           SELECT REL-FILE ASSIGN TO \"REL.DAT\"\n"
    "               ORGANIZATION IS RELATIVE\n"
    "               ACCESS MODE IS DYNAMIC\n"
    "               RELATIVE KEY IS WS-RRN\n"
    "               FILE STATUS IS WS-STATUS.\n"
    "       DATA DIVISION.\n"
    "       FILE SECTION.\n"
    "       FD  REL-FILE.\n"
    "       01  REL-REC PIC X(10).\n"
    "       WORKING-STORAGE SECTION.\n"
    "       01  WS-STATUS PIC XX.\n"
    "       01  WS-RRN PIC 9(4).\n"
    "       PROCEDURE DIVISION.\n"
    "           OPEN INPUT REL-FILE.\n"
    "           CLOSE REL-FILE.\n"
    "           STOP RUN.\n"
)


class TestFileControlRegistry:
    def test_file_control_keys_are_supported_for_certified_subset(self) -> None:
        for key in FILE_CONTROL_KEYS:
            entry = CONSTRUCT_REGISTRY[key]
            assert entry.level is RegistryLevel.SUPPORTED, key
            assert "PROVEN" in entry.evidence, key

    def test_source_only_file_control_fails_closed(self) -> None:
        for key in FILE_CONTROL_KEYS:
            assert (
                CONSTRUCT_REGISTRY[key].effective_source_level
                is RegistryLevel.UNSUPPORTED
            ), key

    def test_vsam_file_image_is_not_overclaimed(self) -> None:
        for key in ("ORGANIZATION INDEXED", "ORGANIZATION RELATIVE"):
            evidence = CONSTRUCT_REGISTRY[key].evidence
            assert "not VSAM" in evidence or "emulat" in evidence.lower(), key
            assert "file-image equivalence is not claimed" in evidence, key


class TestFileControlParsing:
    def test_indexed_select_is_recorded_on_ir(self) -> None:
        program = CobolParser().parse(INDEXED)
        fd = program.file_definitions[0]
        assert fd.organization is FileOrganization.INDEXED
        assert fd.access_mode is FileAccessMode.DYNAMIC
        assert fd.record_key is not None
        assert fd.record_key.field_name == "IDX-KEY"

    def test_relative_select_is_recorded_on_ir(self) -> None:
        program = CobolParser().parse(RELATIVE)
        fd = program.file_definitions[0]
        assert fd.organization is FileOrganization.RELATIVE
        assert fd.relative_key == "WS-RRN"

    def test_alternate_key_is_kept_and_diagnosed(self) -> None:
        program = CobolParser().parse(INDEXED_WITH_ALTERNATE)
        fd = program.file_definitions[0]
        assert [k.field_name for k in fd.alternate_keys] == ["IDX-DATA"]
        # The parser surfaces the gap instead of silently dropping the path.
        # Diagnostics are collected on the parser instance.
        parser = CobolParser()
        parser.parse(INDEXED_WITH_ALTERNATE)
        messages = [d.message for d in parser.diagnostics.all]
        assert any(
            "ALTERNATE RECORD KEY" in message and "no alternate index" in message
            for message in messages
        ), messages


def _program_level(tmp_path: Path, source: str, pid: str) -> CapabilityLevel:
    (tmp_path / f"{pid}.cob").write_text(source, encoding="utf-8")
    app = ApplicationDiscovery().discover(str(tmp_path), application_id="files")
    report = CapabilityAnalyzer(docker_available=True).analyze(app)
    program = [c for c in report.components if c.component_type == "PROGRAM"]
    assert len(program) == 1, report.components
    return CapabilityLevel(program[0].level.value)


class TestFileControlVerdicts:
    def test_indexed_program_is_supported_for_certified_subset(self, tmp_path: Path) -> None:
        assert _program_level(tmp_path, INDEXED, "IDXDEMO") is CapabilityLevel.SUPPORTED

    def test_relative_program_is_supported(self, tmp_path: Path) -> None:
        assert _program_level(tmp_path, RELATIVE, "RELDEMO") is CapabilityLevel.SUPPORTED

    def test_alternate_key_program_stays_unsupported(self, tmp_path: Path) -> None:
        assert (
            _program_level(tmp_path, INDEXED_WITH_ALTERNATE, "IDXDEMO")
            is CapabilityLevel.UNSUPPORTED
        )
