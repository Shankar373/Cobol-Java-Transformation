"""Phase 7 focused gate: MQ queue-name + IMS PCB/segment dependency edges (roadmap P3-6).

Roadmap P3-4 (BL-084/085, DONE) detects `EXEC MQI` / `EXEC DLI` as
constructs; P3-6 (BL-087, filed OPEN audit-first) is the ledger
increment: queue names and PCB/segment references extracted from real
blocks become `visible` entries in the platform dependency ledger via
`build_dependency_ledger(extra_dependencies=...)`, classified
`UNSUPPORTED` with proof state `BLOCKED` (no MQ/IMS runtime lane exists
— same structural truth as the JCL/DB2/CICS lanes), `required=True`
(fail-closed like JCL), deterministic and deduplicated.

Acceptance (docs/BACKLOG.md BL-087):
1. `engine.modernization.external_dependency_edges.extract_external_dependency_entries`
   exists and returns ledger entries for real `QUEUE(…)`/`Q(…)` (MQ) and
   `PCB(…)`/`PCB NAME=…`/`SEGMENT(…)`/`SEGMENT NAME=…` (IMS) references
   inside `EXEC MQI`/`EXEC DLI` blocks — never for comment or
   string-literal text, never outside a block;
2. every entry is `visible=True`, `UNSUPPORTED`, `BLOCKED`,
   `required=True`, kind `MQ`/`IMS`;
3. repeated extraction is identical (deterministic) and duplicates
   collapse to one entry;
4. ledger integration keeps central status fail-closed (never VERIFIED);
5. no existing test is weakened.
"""

from __future__ import annotations

from pathlib import Path

from engine.modernization.external_dependency_edges import (
    extract_external_dependency_entries,
)
from engine.modernization.integrated_proof import (
    CentralStatus,
    CapabilityLevel,
    DependencyKind,
    ProofState,
    RuntimeLaneEvidence,
    build_dependency_ledger,
    evaluate_central_status,
)

MQ_BLOCK = (
    "       PROCEDURE DIVISION.\n"
    "           EXEC MQI PUT Q(HQUEUE) MSGDESC(WS-DESC)\n"
    "                BUFFER(WS-MSG-TEXT) BUFLEN(80)\n"
    "           END-EXEC.\n"
)

MQ_QUEUE_LITERAL_BLOCK = (
    "       PROCEDURE DIVISION.\n"
    "           EXEC MQI GET QUEUE('ORDERS')\n"
    "                MSGDESC(WS-DESC) BUFFER(WS-BUF) BUFLEN(80)\n"
    "           END-EXEC.\n"
)

DLI_BLOCK = (
    "       PROCEDURE DIVISION.\n"
    "           EXEC DLI GU\n"
    "                PCB NAME=IMSPCB\n"
    "                SEGMENT NAME=CUSTOMER\n"
    "           END-EXEC.\n"
)

DLI_PAREN_BLOCK = (
    "       PROCEDURE DIVISION.\n"
    "           EXEC DLI GHU\n"
    "                PCB(PCB1) SEGMENT(SEG-A)\n"
    "           END-EXEC.\n"
)

COMMENT_AND_LITERAL_TEXT = (
    "       PROCEDURE DIVISION.\n"
    "     *    EXEC MQI GET Q(COMMENTQ) END-EXEC.\n"
    "           DISPLAY \"EXEC DLI GU PCB(SECRET) END-EXEC\".\n"
    "     *>   EXEC DLI GHU PCB(NOTEQ) END-EXEC.\n"
    "           MOVE Q(PLAINQ) TO WS-Q.\n"
    "           STOP RUN.\n"
)

NO_EXEC_WRAPPER = (
    "       PROCEDURE DIVISION.\n"
    "           MOVE 1 TO WS-COUNT.\n"
    "           DISPLAY 'PCB SEGMENT QUEUE'.\n"
    "           STOP RUN.\n"
)


def _ids(entries) -> set[str]:
    return {entry.dependency_id for entry in entries}


class TestExtractionPositives:
    def test_mq_queue_form_is_extracted(self) -> None:
        entries = extract_external_dependency_entries(MQ_BLOCK)
        assert _ids(entries) == {"MQ:QUEUE=HQUEUE"}, _ids(entries)

    def test_mq_queue_literal_forms_are_extracted(self) -> None:
        entries = extract_external_dependency_entries(MQ_QUEUE_LITERAL_BLOCK)
        assert _ids(entries) == {"MQ:QUEUE=ORDERS"}, _ids(entries)

    def test_dli_name_forms_are_extracted(self) -> None:
        entries = extract_external_dependency_entries(DLI_BLOCK)
        assert _ids(entries) == {"IMS:PCB=IMSPCB", "IMS:SEGMENT=CUSTOMER"}, (
            _ids(entries)
        )

    def test_dli_parenthesized_forms_are_extracted(self) -> None:
        entries = extract_external_dependency_entries(DLI_PAREN_BLOCK)
        assert _ids(entries) == {"IMS:PCB=PCB1", "IMS:SEGMENT=SEG-A"}, (
            _ids(entries)
        )


class TestLedgerEntryShape:
    def test_every_entry_is_visible_blocked_and_required(self) -> None:
        entries = extract_external_dependency_entries(MQ_BLOCK) + (
            extract_external_dependency_entries(DLI_BLOCK)
        )
        assert entries, "expected at least one entry"
        for entry in entries:
            assert entry.visible is True, entry
            assert entry.capability_level is CapabilityLevel.UNSUPPORTED, entry
            assert entry.proof_state is ProofState.BLOCKED, entry
            assert entry.required is True, entry
            assert entry.kind in (DependencyKind.MQ, DependencyKind.IMS), entry

    def test_mq_entries_use_the_mq_kind(self) -> None:
        entries = extract_external_dependency_entries(MQ_BLOCK)
        assert entries and entries[0].kind is DependencyKind.MQ, entries

    def test_ims_entries_use_the_ims_kind(self) -> None:
        entries = extract_external_dependency_entries(DLI_BLOCK)
        assert entries and all(
            entry.kind is DependencyKind.IMS for entry in entries
        ), entries


class TestNegativesAndDeterminism:
    def test_comment_and_literal_text_never_extract(self) -> None:
        entries = extract_external_dependency_entries(COMMENT_AND_LITERAL_TEXT)
        assert entries == (), entries

    def test_text_without_an_exec_block_never_extracts(self) -> None:
        entries = extract_external_dependency_entries(NO_EXEC_WRAPPER)
        assert entries == (), entries

    def test_repeated_extraction_is_identical(self) -> None:
        first = extract_external_dependency_entries(MQ_BLOCK + DLI_BLOCK)
        second = extract_external_dependency_entries(MQ_BLOCK + DLI_BLOCK)
        assert first == second

    def test_duplicate_references_collapse(self) -> None:
        duplicated = MQ_BLOCK + MQ_BLOCK
        entries = extract_external_dependency_entries(duplicated)
        assert _ids(entries) == {"MQ:QUEUE=HQUEUE"}, _ids(entries)


class TestLedgerIntegration:
    def _entries(self):
        return extract_external_dependency_entries(MQ_BLOCK + DLI_BLOCK)

    def test_ledger_includes_the_extra_entries(self) -> None:
        class _Report:
            capability_report = None

        ledger = build_dependency_ledger(
            _Report(), RuntimeLaneEvidence(), extra_dependencies=self._entries()
        )
        ids = _ids(ledger)
        assert {"MQ:QUEUE=HQUEUE", "IMS:PCB=IMSPCB", "IMS:SEGMENT=CUSTOMER"} <= ids, (
            ids
        )

    def test_central_status_stays_fail_closed(self) -> None:
        class _Report:
            capability_report = None

        ledger = build_dependency_ledger(
            _Report(), RuntimeLaneEvidence(), extra_dependencies=self._entries()
        )
        status, reasons = evaluate_central_status(ledger, RuntimeLaneEvidence())
        assert status is not CentralStatus.VERIFIED, (status, reasons)
        assert reasons, reasons

    def test_extractor_is_importable_from_the_documented_path(self) -> None:
        import engine.modernization.external_dependency_edges as module

        assert callable(module.extract_external_dependency_entries)
        assert Path(module.__file__).name == "external_dependency_edges.py"
