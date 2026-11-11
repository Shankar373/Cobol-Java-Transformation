"""Roadmap unit 2: real IBM MQ and IMS call forms are detected and ledgered.

``EXEC MQI`` is not IBM syntax: real MQ programs ``CALL 'MQCONN'/'MQOPEN'/
'MQGET'/'MQPUT'...`` and real IMS batch programs ``CALL 'CBLTDLI'`` (or
``'AIBTDLI'``) ``USING <function> <pcb> <io-area> [<ssa>...]``. Until this
unit only the generic INCONCLUSIVE evidence marker saw them: no registry key,
no capability reason, no dependency edges. Classification only - no runtime,
no equivalence claim, nothing is transformed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.modernization.capability_analyzer import CapabilityAnalyzer, CapabilityLevel
from engine.modernization.external_dependency_edges import extract_external_dependency_entries
from engine.transformation.application_discovery import ApplicationDiscovery
from engine.transformation.semantic_capability import CONSTRUCT_REGISTRY, scan_constructs

HEAD = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. {pid}.\n"
    "       DATA DIVISION.\n"
    "       WORKING-STORAGE SECTION.\n"
)

IMS = HEAD.format(pid="IMSCALL") + (
    "       01 DLI-GU          PIC X(4)  VALUE 'GU  '.\n"
    "       01 DLI-ISRT        PIC X(4)  VALUE 'ISRT'.\n"
    "       01 SSA-CUST        PIC X(9)  VALUE 'CUSTOMER '.\n"
    "       01 SSA-ORDER       PIC X(9)  VALUE 'ORDERS   '.\n"
    "       01 IO-AREA         PIC X(80).\n"
    "       LINKAGE SECTION.\n"
    "       01 IMSPCB          PIC X(40).\n"
    "       PROCEDURE DIVISION USING IMSPCB.\n"
    "           CALL 'CBLTDLI' USING DLI-GU IMSPCB IO-AREA SSA-CUST SSA-ORDER.\n"
    "           CALL 'CBLTDLI' USING DLI-ISRT IMSPCB IO-AREA.\n"
    "           STOP RUN.\n"
)

AIB = HEAD.format(pid="AIBCALL") + (
    "       01 DLI-GN          PIC X(4)  VALUE 'GN  '.\n"
    "       01 IO-AREA         PIC X(80).\n"
    "       01 AIBBLK          PIC X(120).\n"
    "       PROCEDURE DIVISION.\n"
    "           CALL \"AIBTDLI\" USING DLI-GN AIBBLK IO-AREA.\n"
    "           STOP RUN.\n"
)

MQ = HEAD.format(pid="MQCALL") + (
    "       01 QMGR-NAME       PIC X(48) VALUE 'QM1'.\n"
    "       01 MQOD.\n"
    "          05 MQOD-OBJECTNAME PIC X(48) VALUE 'ORDERS.IN'.\n"
    "       01 HCONN           PIC S9(9) BINARY.\n"
    "       01 HOBJ            PIC S9(9) BINARY.\n"
    "       01 CC              PIC S9(9) BINARY.\n"
    "       01 RC              PIC S9(9) BINARY.\n"
    "       PROCEDURE DIVISION.\n"
    "           CALL 'MQCONN' USING QMGR-NAME HCONN CC RC.\n"
    "           CALL 'MQOPEN' USING HCONN MQOD OPTS HOBJ CC RC.\n"
    "           MOVE 'AUDIT.OUT' TO MQOD-OBJECTNAME.\n"
    "           CALL 'MQPUT1' USING HCONN MQOD MD PMO LEN BUF CC RC.\n"
    "           CALL 'MQGET' USING HCONN HOBJ MD GMO LEN BUF DL CC RC.\n"
    "           CALL 'MQCLOSE' USING HCONN HOBJ OPTS CC RC.\n"
    "           CALL 'MQDISC' USING HCONN CC RC.\n"
    "           STOP RUN.\n"
)

PLAIN = HEAD.format(pid="PLAIN") + (
    "       01 WS-X PIC X(8).\n"
    "       PROCEDURE DIVISION.\n"
    "           CALL 'SUBPROG' USING WS-X.\n"
    "           STOP RUN.\n"
)


def _ids(source: str) -> set[str]:
    return {e.dependency_id for e in extract_external_dependency_entries(source)}


def _program(tmp_path: Path, source: str, program_id: str):
    src = tmp_path / "cobol"
    src.mkdir(parents=True, exist_ok=True)
    (src / f"{program_id}.cob").write_text(source, encoding="utf-8")
    app = ApplicationDiscovery().discover(src, application_id="unit2")
    report = CapabilityAnalyzer(docker_available=True).analyze(app, source_root=src)
    return next(
        c for c in report.components
        if c.component_type == "PROGRAM" and c.component_id == program_id
    )


class TestScanDetection:
    def test_ims_calls_are_detected(self):
        assert "CALL DLI" in scan_constructs(IMS)
        assert "CALL DLI" in scan_constructs(AIB)

    def test_mq_calls_are_detected(self):
        assert "CALL MQI" in scan_constructs(MQ)

    def test_ordinary_call_is_neither(self):
        found = scan_constructs(PLAIN)
        assert "CALL DLI" not in found and "CALL MQI" not in found

    @pytest.mark.parametrize("name", [
        "MQCONN", "MQCONNX", "MQDISC", "MQOPEN", "MQCLOSE", "MQGET", "MQPUT", "MQPUT1",
        "MQINQ", "MQSET", "MQBEGIN", "MQCMIT", "MQBACK", "MQSUB", "MQSUBRQ", "MQCB", "MQCTL", "MQSTAT",
    ])
    def test_every_mqi_verb_is_detected_in_any_case(self, name):
        for spelled in (name, name.lower()):
            src = "       PROCEDURE DIVISION.\n" f"           call '{spelled}' using h cc rc.\n           STOP RUN.\n"
            assert "CALL MQI" in scan_constructs(src), spelled

    @pytest.mark.parametrize("name", ["CBLTDLI", "AIBTDLI", "CEETDLI", "PLITDLI"])
    def test_every_dli_entry_is_detected(self, name):
        src = "       PROCEDURE DIVISION.\n" f"           CALL '{name}' USING f p io.\n           STOP RUN.\n"
        assert "CALL DLI" in scan_constructs(src), name

    def test_comments_and_other_literals_never_detect(self):
        src = (
            "       PROCEDURE DIVISION.\n"
            "      *    CALL 'MQOPEN' USING H\n"
            "           DISPLAY \"CALL 'MQOPEN' USING HCONN\".\n"
            "           DISPLAY 'CALL ''CBLTDLI'' USING X'.\n"
            "      *>   CALL 'CBLTDLI' USING F P\n"
            "           STOP RUN.\n"
        )
        found = scan_constructs(src)
        assert "CALL MQI" not in found and "CALL DLI" not in found, sorted(found)

    def test_near_misses_never_detect(self):
        src = (
            "       PROCEDURE DIVISION.\n"
            "           CALL 'MQOPENX' USING H.\n"
            "           CALL 'XMQOPEN' USING H.\n"
            "           CALL 'CBLTDLIX' USING H.\n"
            "           CALL 'MQ' USING H.\n"
            "           MOVE WS-CALL-MQOPEN TO WS-Y.\n"
            "           STOP RUN.\n"
        )
        found = scan_constructs(src)
        assert "CALL MQI" not in found and "CALL DLI" not in found, sorted(found)

    def test_detection_is_deterministic(self):
        assert scan_constructs(IMS + MQ) == scan_constructs(IMS + MQ)


class TestRegistry:
    @pytest.mark.parametrize("key", ["CALL DLI", "CALL MQI"])
    def test_rows_fail_closed(self, key):
        entry = CONSTRUCT_REGISTRY[key]
        assert entry.level is CapabilityLevel.UNSUPPORTED
        assert entry.effective_source_level is CapabilityLevel.UNSUPPORTED

    def test_exec_mqi_is_labelled_as_not_ibm_syntax(self):
        assert "not" in CONSTRUCT_REGISTRY["EXEC MQI"].evidence.lower() or "CALL" in CONSTRUCT_REGISTRY["EXEC MQI"].evidence


class TestLedgerEdges:
    def test_ims_cblitdli_edges(self):
        assert _ids(IMS) >= {
            "IMS:CALL=CBLTDLI", "IMS:FUNCTION=GU", "IMS:FUNCTION=ISRT", "IMS:PCB=IMSPCB",
            "IMS:SEGMENT=CUSTOMER", "IMS:SEGMENT=ORDERS",
        }

    def test_ims_aib_edges(self):
        assert _ids(AIB) >= {"IMS:CALL=AIBTDLI", "IMS:FUNCTION=GN", "IMS:AIB=AIBBLK"}

    def test_mq_edges(self):
        assert _ids(MQ) >= {
            "MQ:CALL=MQCONN", "MQ:CALL=MQOPEN", "MQ:CALL=MQPUT1", "MQ:CALL=MQGET",
            "MQ:CALL=MQCLOSE", "MQ:CALL=MQDISC",
            "MQ:QUEUE=ORDERS.IN", "MQ:QUEUE=AUDIT.OUT", "MQ:QMGR=QM1",
        }

    def test_every_edge_is_blocked_and_unsupported(self):
        for source in (IMS, AIB, MQ):
            entries = extract_external_dependency_entries(source)
            assert entries
            for e in entries:
                assert e.capability_level is CapabilityLevel.UNSUPPORTED
                assert e.proof_state.name == "BLOCKED"
                assert e.required is True

    def test_reasons_name_the_call_form_not_exec(self):
        reasons = " ".join(e.reason for e in extract_external_dependency_entries(IMS + MQ))
        assert "CALL" in reasons and "EXEC DLI" not in reasons and "EXEC MQI" not in reasons

    def test_unresolvable_arguments_yield_only_the_call_edge(self):
        src = (
            "       PROCEDURE DIVISION.\n"
            "           CALL 'CBLTDLI' USING WS-FUNC WS-PCB WS-IO.\n"
            "           STOP RUN.\n"
        )
        ids = _ids(src)
        assert "IMS:CALL=CBLTDLI" in ids and "IMS:PCB=WS-PCB" in ids
        assert not [i for i in ids if i.startswith("IMS:FUNCTION=")]

    def test_plain_program_and_exec_forms_are_unchanged(self):
        assert _ids(PLAIN) == set()
        exec_form = (
            "       PROCEDURE DIVISION.\n"
            "           EXEC DLI GU PCB NAME=P1 SEGMENT NAME=CUST END-EXEC.\n"
            "           STOP RUN.\n"
        )
        assert _ids(exec_form) == {"IMS:PCB=P1", "IMS:SEGMENT=CUST"}

    def test_edges_are_sorted_and_deduplicated(self):
        entries = extract_external_dependency_entries(MQ + MQ)
        ids = [e.dependency_id for e in entries]
        assert ids == sorted(set(ids))


class TestVerdicts:
    @pytest.mark.parametrize("source,pid", [(IMS, "IMSCALL"), (AIB, "AIBCALL"), (MQ, "MQCALL")])
    def test_program_is_never_supported_and_names_the_subsystem(self, tmp_path, source, pid):
        program = _program(tmp_path, source, pid)
        assert program.level not in (CapabilityLevel.SUPPORTED, CapabilityLevel.PARTIAL), program
        text = " ".join(str(r) for r in getattr(program, "reasons", ())) + str(program)
        assert ("CALL DLI" in text) or ("CALL MQI" in text) or ("IMS" in text) or ("MQ" in text)


class TestProductSurface:
    """The edges reach the integrated proof the API serves; nothing is VERIFIED."""

    @pytest.mark.parametrize("source,name,expected", [
        (MQ, "MQCALL", {"MQ:CALL=MQOPEN", "MQ:QUEUE=ORDERS.IN", "MQ:QMGR=QM1"}),
        (IMS, "IMSCALL", {"IMS:CALL=CBLTDLI", "IMS:PCB=IMSPCB", "IMS:SEGMENT=CUSTOMER"}),
    ])
    def test_integrated_proof_carries_the_call_form_edges(self, tmp_path, source, name, expected):
        import api.app as app_mod
        import api.service as svc_mod
        from api.models import RunStage
        from api.service import Service
        from api.store import Store
        from tests.integration.test_integrated_proof_api import _fresh_run_record, _stored_report

        store = Store()
        svc = Service(store)
        app_mod._store = svc_mod._store = store
        app_mod._service = svc_mod._service = svc
        (tmp_path / f"{name}.cob").write_text(source, encoding="utf-8")
        app = svc.create_application( target_runtime="spring_boot",
            name=f"calls-{name}", description="", workload_id="wl-calls", java_entrypoint="Main"
        )
        app.cobol_source_path = str(tmp_path)
        store.update_application(app)
        run = store.add_run(_fresh_run_record(svc, app.id))
        run.stage = RunStage.COMPLETED
        run.modernization_report = _stored_report(app.id)
        store.update_run(run)

        proof = svc.get_integrated_proof(run.id)["proof"]
        ids = {e["dependency_id"] for e in proof["dependency_ledger"]}
        assert expected <= ids, sorted(ids)
        assert proof["central_status"] != "VERIFIED"
        assert proof["required_dependencies_proven"] is False
