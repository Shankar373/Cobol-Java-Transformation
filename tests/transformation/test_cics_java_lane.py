"""Tests for the CICS modernisation lane: explicit Java/Spring service model.

Validation of the produced output model (``engine.cics``), the shared-lane
facade (``engine.transformation.cics_java_mapping``) and the generated Java
source.  No CICS TS runtime equivalence is claimed anywhere.
"""

from __future__ import annotations

import pathlib

from engine.cics import (
    CicsSpringApplication,
    CicsSpringGenerator,
    CicsSpringMapper,
    classify_command,
)
from engine.cics.model import (
    CicsBoundaryKind,
    CicsConstructStatus,
    CicsExplicitKind,
    CicsInteractionKind,
    CicsIssueSeverity,
    CicsResourceKind,
    CicsRespPolicy,
    CicsTerminalIoKind,
)
from engine.cics.naming import camel, pascal
from engine.transformation.cics_java_mapping import (
    extract_cics_blocks,
    map_cics_programs,
)
from engine.transformation.cics_parser import CicsParser
from engine.transformation.ir import (
    CicsApplication,
    CicsCommandType,
)
from engine.pipeline import WorkloadDefinition

SUPPORTED_SUBSET_VERSION = "1.0.0"


def _parse(text: str) -> CicsApplication:
    return CicsParser().parse_embedded_cics(text)


def _map(text: str, *, program_id: str = "CUSTINQ") -> CicsSpringApplication:
    return CicsSpringMapper().map(_parse(text), program_id=program_id)


# ============================================================================
# Subset classification
# ============================================================================


class TestSubsetClassification:
    """Each command is classified against the supported subset."""

    def test_terminal_io(self):
        for command in (CicsCommandType.SEND, CicsCommandType.RECEIVE):
            result = classify_command(command)
            assert result.status == CicsConstructStatus.MAPPED
            assert result.category == "TERMINAL_IO"

    def test_program_interaction(self):
        for command in (CicsCommandType.LINK, CicsCommandType.XCTL):
            result = classify_command(command)
            assert result.status == CicsConstructStatus.MAPPED
            assert result.category == "PROGRAM_INTERACTION"

    def test_return_is_program_interaction_and_boundary(self):
        result = classify_command(CicsCommandType.RETURN)
        assert result.status == CicsConstructStatus.MAPPED
        assert result.category == "PROGRAM_INTERACTION"
        assert result.is_mapped

    def test_resource_access(self):
        for command in (
            CicsCommandType.READ,
            CicsCommandType.WRITE,
            CicsCommandType.REWRITE,
            CicsCommandType.DELETE,
            CicsCommandType.STARTBR,
            CicsCommandType.READNEXT,
            CicsCommandType.READPREV,
            CicsCommandType.ENDBR,
            CicsCommandType.WRITEQ,
            CicsCommandType.READQ,
            CicsCommandType.DELETEQ,
        ):
            result = classify_command(command)
            assert result.status == CicsConstructStatus.MAPPED
            assert result.category == "RESOURCE_ACCESS"

    def test_boundary_commit(self):
        result = classify_command(CicsCommandType.SYNCPOINT)
        assert result.category == "BOUNDARY"
        assert result.is_mapped

    def test_boundary_rollback(self):
        result = classify_command(CicsCommandType.ABEND)
        assert result.category == "BOUNDARY"
        assert result.is_mapped

    def test_explicit_only(self):
        for command in (
            CicsCommandType.HANDLE_CONDITION,
            CicsCommandType.HANDLE_AID,
            CicsCommandType.ASSIGN,
        ):
            result = classify_command(command)
            assert result.status == CicsConstructStatus.EXPLICIT_ONLY
            assert result.category == "EXPLICIT_ONLY"

    def test_known_unsupported(self):
        for command in (
            CicsCommandType.ALLOCATE,
            CicsCommandType.FREE,
            CicsCommandType.HOLD,
            CicsCommandType.RELEASE,
            CicsCommandType.SET,
            CicsCommandType.IGNORE,
            CicsCommandType.POP,
            CicsCommandType.PUSH,
        ):
            result = classify_command(command)
            assert result.status == CicsConstructStatus.UNSUPPORTED
            assert result.category == "UNSUPPORTED"

    def test_unknown_defaults_unsupported(self):
        result = classify_command(CicsCommandType.ALLOCATE)
        assert result.status == CicsConstructStatus.UNSUPPORTED
        assert result.category == "UNSUPPORTED"
        assert not result.is_mapped

    def test_every_enum_classification_is_explicit(self):
        # Every parser-recognizable command must classify to a supported status
        # or the explicit UNSUPPORTED fallback. Nothing is silent.
        for command in CicsCommandType:
            result = classify_command(command)
            assert result.status in (
                CicsConstructStatus.MAPPED,
                CicsConstructStatus.EXPLICIT_ONLY,
                CicsConstructStatus.UNSUPPORTED,
            )
            assert result.category

        names = sorted(c.value for c in CicsCommandType)
        assert names == sorted(CicsCommandType(c.value).value for c in CicsCommandType)
        assert names == sorted(names)


# ============================================================================
# Naming helpers
# ============================================================================


class TestNaming:
    def test_pascal(self):
        assert pascal("WS-CUST-ID") == "WsCustId"

    def test_camel(self):
        assert camel("WS-CUST-ID") == "wsCustId"

    def test_pascal_alphanumeric(self):
        assert pascal("CUST") == "Cust"


# ============================================================================
# Explicit mapping
# ============================================================================


class TestExplicitMapping:
    """Commands are mapped into explicit Java/Spring model elements."""

    def test_explicit_only_block(self):
        app = _map("HANDLE CONDITION NOTFND(NOT-FOUND) ERROR(ERR-RTN)", program_id="X")
        service = app.services[0]
        assert service.source_program == "X"
        assert service.explicit_constructs
        assert service.explicit_constructs[0].kind == CicsExplicitKind.HANDLE_CONDITION
        assert "NOTFND(NOT-FOUND)" in service.explicit_constructs[0].raw_text
        assert service.unsupported_constructs == ()

    @staticmethod
    def _raw_text(app: CicsApplication) -> list[str]:
        return [c.raw_text for c in app.commands]

    def test_send_receive(self):
        app = _map("SEND MAP(INQMENU) MAPSET(INQMS)")
        io = app.services[0].terminal_ios[0]
        assert io.kind == CicsTerminalIoKind.SEND
        assert io.map_name == "INQMENU"
        assert io.mapset_name == "INQMS"

        app = _map("RECEIVE MAP(INQMENU) INTO(:WS-CUST) LENGTH(:WS-CUST-LEN)")
        io = app.services[0].terminal_ios[0]
        assert io.kind == CicsTerminalIoKind.RECEIVE
        assert io.map_name == "INQMENU"
        assert io.data_field == "WS-CUST"
        assert io.length_field == "WS-CUST-LEN"

    def test_resource_read(self):
        app = _map("READ DATASET(CUSTFILE) INTO(:WS-CUST) KEY(:WS-CUST-ID)")
        access = app.services[0].resource_accesses[0]
        assert access.operation == "READ"
        assert access.resource_kind == CicsResourceKind.FILE
        assert access.resource == "CUSTFILE"
        assert access.key_field == "WS-CUST-ID"
        assert access.data_field == "WS-CUST"

    def test_resource_write_file(self):
        app = _map("WRITE DATASET(CUSTFILE) FROM(:WS-CUST) LENGTH(:WS-CUST-LEN)")
        access = app.services[0].resource_accesses[0]
        assert access.operation == "WRITE"
        assert access.resource_kind == CicsResourceKind.FILE
        assert access.data_field == "WS-CUST"

    def test_queue_commands_mapped_as_queue(self):
        app = _map("WRITEQ TS QNAME(ORDERQ) FROM(:WS-ORDER) LENGTH(:WS-ORDER-LEN)")
        access = app.services[0].resource_accesses[0]
        assert access.operation == "WRITEQ"
        assert access.resource_kind == CicsResourceKind.QUEUE
        assert access.resource == "ORDERQ"

    def test_boundary_syncpoint_is_commit(self):
        app = _map("SYNCPOINT")
        boundary = app.services[0].transaction_boundaries[0]
        assert boundary.kind == CicsBoundaryKind.COMMIT
        assert app.services[0].is_transactional

    def test_boundary_abend_is_rollback(self):
        app = _map("ABEND")
        boundary = app.services[0].transaction_boundaries[0]
        assert boundary.kind == CicsBoundaryKind.ROLLBACK

    def test_return_is_pseudo_conversational_boundary(self):
        app = _map("RETURN TRANSID(CUST)")
        boundary = app.services[0].transaction_boundaries[0]
        assert boundary.kind == CicsBoundaryKind.PSEUDO_CONVERSATIONAL
        assert boundary.transaction_id == "CUST"
        interaction = app.services[0].program_interactions[0]
        assert interaction.kind == CicsInteractionKind.RETURN

    def test_pure_terminal_io_not_transactional(self):
        app = _map("SEND MAP(INQMENU)")
        assert not app.services[0].is_transactional

    def test_link_interaction(self):
        app = _map("LINK PROGRAM(CUSTUPD) COMMAREA(:WS-CUST) LENGTH(:WS-CUST-LEN)")
        interaction = app.services[0].program_interactions[0]
        assert interaction.kind == CicsInteractionKind.LINK
        assert interaction.program == "CUSTUPD"
        assert interaction.commarea == "WS-CUST"
        assert interaction.commarea_length == "WS-CUST-LEN"

    def test_host_variables_deduplicated(self):
        app = _map(
            "READ DATASET(F) INTO(:WS-CUST) KEY(:WS-CUST-ID) "
            "SEND MAP(M) FROM(:WS-CUST) LENGTH(:WS-CUST-LEN)"
        )
        host = app.services[0].host_variables
        assert host == ("WS-CUST", "WS-CUST-ID", "WS-CUST-LEN")

    def test_resp_policies(self):
        app = _map("READ DATASET(F) KEY(K) RESP(:WS-RESP)")
        assert app.services[0].resource_accesses[0].resp_policy == CicsRespPolicy.RESP_VARIABLE

        app = _map("READ DATASET(F) KEY(K) RESP2(:WS-RESP2)")
        assert app.services[0].resource_accesses[0].resp_policy == CicsRespPolicy.RESP2_VARIABLE

        app = _map("READ DATASET(F) KEY(K) NOHANDLE")
        assert app.services[0].resource_accesses[0].resp_policy == CicsRespPolicy.NO_HANDLE

        app = _map("READ DATASET(F) KEY(K)")
        assert app.services[0].resource_accesses[0].resp_policy == CicsRespPolicy.NO_HANDLE

    def test_assign_and_handle_aid(self):
        app = _map("ASSIGN APPLID(:WS-APPLID)")
        assert app.services[0].explicit_constructs[0].kind == CicsExplicitKind.ASSIGN

        app = _map("HANDLE AID PF3(PF3-RTN)")
        assert app.services[0].explicit_constructs[0].kind == CicsExplicitKind.HANDLE_AID

    def test_validation_error(self):
        app = _map("LINK COMMAREA(:WS-CUST)")
        assert any(issue.severity == CicsIssueSeverity.ERROR
                   for issue in app.services[0].issues)

    def test_missing_trailing_return_warns(self):
        app = _map("SEND MAP(M)")
        assert any(issue.severity == CicsIssueSeverity.WARNING
                   for issue in app.services[0].issues)


# ============================================================================
# Merging of multiple programs
# ============================================================================


class TestMerge:
    def test_merge_multiple_programs(self):
        from engine.transformation.cics_java_mapping import extract_cics_blocks

        cobol_a = "PROGRAM-ID. PROGA.\n EXEC CICS\n SEND MAP(A)\n END-EXEC."
        cobol_b = "PROGRAM-ID. PROGB.\n EXEC CICS\n LINK PROGRAM(B)\n END-EXEC."
        blocks = extract_cics_blocks(cobol_a) + extract_cics_blocks(cobol_b)
        merged = CicsSpringMapper().merge(blocks, application_id="a")
        assert [s.source_program for s in merged.services] == ["PROGA", "PROGB"]
        assert merged.application_id == "a"
        assert merged.supported_subset_version == SUPPORTED_SUBSET_VERSION

    def test_empty_application(self):
        merged = CicsSpringMapper().merge([])
        assert merged.services == ()
        assert merged.validate() == []


# ============================================================================
# Generated Java source
# ============================================================================


class TestGeneratedJava:
    def test_generated_file_set(self):
        app = _map("LINK PROGRAM(CUSTUPD) COMMAREA(:WS-CUST)")
        files = CicsSpringGenerator().generate(app)
        paths = {f.path for f in files}
        assert paths == {
            "src/main/java/com/generated/cics/CicsApplication.java",
            "src/main/java/com/generated/cics/cics/CicsRuntime.java",
            "src/main/java/com/generated/cics/client/ProgramClient.java",
            "src/main/java/com/generated/cics/service/CustinqService.java",
            "src/main/java/com/generated/cics/dto/CustinqCommArea.java",
            "cics-mapping/cics-application-CICS-MAPPING.md",
        }

    def test_source_is_ascii(self):
        app = _map("SEND MAP(M) RETURN")
        for f in CicsSpringGenerator().generate(app):
            assert all(ord(c) < 128 for c in f.source_code), f.path
        assert all(ord(c) < 128 for c in app.application_id)

    def test_every_source_has_disclaimer(self):
        app = _map("SEND MAP(M)")
        for f in CicsSpringGenerator().generate(app):
            assert "NOT CICS TS EQUIVALENCE" in f.source_code

    def test_report_has_versions_and_services(self):
        app = _map(
            "SEND MAP(M)\n"
            "RETURN TRANSID(CUST)",
            program_id="CUST",
        )
        files = CicsSpringGenerator().generate(app)
        report = next(f for f in files if f.path.endswith("CICS-MAPPING.md"))
        assert f"Supported subset version: {SUPPORTED_SUBSET_VERSION}" in report.source_code
        assert "CUST -> CustService" in report.source_code  # service title
        assert "PSEUDO_CONVERSATIONAL" in report.source_code

    def test_service_execute_preserves_command_order(self):
        app = _map(
            "HANDLE CONDITION NOTFND(NOT-FOUND)\n"
            "SEND MAP(M)\n"
            "READ DATASET(F) KEY(K)\n"
            "SYNCPOINT\n"
            "RETURN TRANSID(CUST)"
        )
        files = CicsSpringGenerator().generate(app)
        service = next(f for f in files if f.class_name == "CustinqService")
        source = service.source_code
        # flow order preserved end-to-end
        assert "step0();" in source
        assert "step4();" in source
        assert source.index("step0()") < source.index("step1()") < source.index("step4()")

    def test_unsupported_construct_marked_verbatim(self):
        app = _map("ALLOCATE\nSYNCPOINT")
        files = CicsSpringGenerator().generate(app)
        service = next(f for f in files if f.class_name == "CustinqService")
        assert "// CICS-UNSUPPORTED: ALLOCATE" in service.source_code
        report = next(f for f in files if f.path.endswith("CICS-MAPPING.md"))
        assert "`ALLOCATE`" in report.source_code

    def test_unknown_command_is_kept_explicit(self):
        app = _map("ALLOCATE")
        assert len(app.all_unsupported()) == 1
        files = CicsSpringGenerator().generate(app)
        service = next(f for f in files if f.class_name == "CustinqService")
        assert "CICS-UNSUPPORTED" in service.source_code

    def test_multiple_runs_identical(self):
        app = _map("SEND MAP(M)\nREAD DATASET(F) KEY(K)\nRETURN")
        once = CicsSpringGenerator().generate(app)
        twice = CicsSpringGenerator().generate(app)
        assert [(f.path, f.source_code) for f in once] == [
            (f.path, f.source_code) for f in twice
        ]

    def test_commarea_generated_from_host_variable(self):
        app = _map("READ DATASET(F) INTO(:WS-CUST) KEY(:WS-CUST-ID)")
        files = CicsSpringGenerator().generate(app)
        commarea = next(f for f in files if f.class_name == "CustinqCommArea")
        assert "wsCustId" in commarea.source_code


# ============================================================================
# COBOL facade (shared lane)
# ============================================================================


class TestFacade:
    COBOL = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CUSTINQ.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-CUST-ID PIC X(9).
       01 WS-CUST    PIC X(80).
       PROCEDURE DIVISION.
       *> CICS boolean constants are COBOL-evaluable in the shared runner.
       HANDLE-CUST-INQUIRY.
           EXEC CICS
               HANDLE CONDITION NOTFND(NOT-FOUND) ERROR(ERR-RTN)
               SEND MAP(INQMENU) MAPSET(INQMS)
               RECEIVE MAP(INQMENU)
               READ DATASET(CUSTFILE) INTO(:WS-CUST)
               READ DATASET(CUSTFILE) INTO(:WS-CUST) KEY(:WS-CUST-ID)
               SYNCPOINT
               RETURN TRANSID(CUST)
           END-EXEC.
           GOBACK.
       """

    def test_extract_cics_blocks(self):
        blocks = extract_cics_blocks(self.COBOL)
        assert len(blocks) == 1
        assert blocks[0].program_id == "CUSTINQ"

    def test_map_facade(self):
        application = map_cics_programs(self.COBOL)
        assert application.services[0].source_program == "CUSTINQ"
        assert application.services[0].is_transactional

    def test_end_to_end_transform(self):
        from engine.transformation.cics_java_mapping import transform_cics_program

        app, files = transform_cics_program(self.COBOL)
        assert app.validate() == []
        assert files
        assert "CUSTINQ" in [s.source_program for s in app.services]


def test_no_cics_ts_equivalence_claimed_in_model():
    """The output model never claims CICS TS runtime equivalence."""
    assert "No CICS TS runtime equivalence is claimed anywhere in this model." in (
        __import__("engine.cics.model", fromlist=[""]).__doc__
    )


# ============================================================================
# CICS workload fixture
# ============================================================================


class TestWorkloadFixture:
    """./fixtures/workload-cics is a source fixture for the lane."""

    @staticmethod
    def _program(name: str) -> str:
        return (
            pathlib.Path(__file__).resolve().parents[2]
            / "fixtures"
            / "workload-cics"
            / "cobol"
            / f"{name}.cob"
        ).read_text(encoding="utf-8")

    def test_comma_programs_map_to_one_service_each(self):
        from engine.transformation.cics_java_mapping import transform_cics_program

        for name in ("CUSTINQ", "ORDPROC"):
            app, files = transform_cics_program(
                self._program(name), application_id="cics-workload"
            )
            assert len(app.services) == 1, name
            assert app.validate() == [], name
            assert files, name

    def test_custinq_is_transactional_pseudo_conversational(self):
        from engine.transformation.cics_java_mapping import map_cics_programs

        app = map_cics_programs(self._program("CUSTINQ"))
        service = app.services[0]
        assert service.is_transactional
        assert CicsBoundaryKind.COMMIT in {
            b.kind for b in service.transaction_boundaries
        }
        assert CicsBoundaryKind.PSEUDO_CONVERSATIONAL in {
            b.kind for b in service.transaction_boundaries
        }
        assert ("LINK", "CUSTDISP") in service.get_interaction_targets()
        assert "read" in service.get_resource_operations()

    def test_ordproc_keeps_unsupported_allocate_explicit(self):
        from engine.transformation.cics_java_mapping import map_cics_programs

        app = map_cics_programs(self._program("ORDPROC"))
        service = app.services[0]
        assert {u.command for u in service.unsupported_constructs} == {"ALLOCATE"}
        assert service.has_unsupported

    def test_workload_declaration_is_valid(self):
        import importlib.util

        workloads = (
            pathlib.Path(__file__).resolve().parents[2] / "fixtures" / "workload-cics"
        )
        spec = importlib.util.spec_from_file_location(
            "wl_cics", workloads / "workload.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        workload = module.cics_workload()
        assert isinstance(workload, WorkloadDefinition)
        assert workload.workload_id == "cics"
        assert {a.artifact_type for a in workload.artifacts} == {
            "STDOUT",
            "STDERR",
            "EXIT_STATUS",
        }