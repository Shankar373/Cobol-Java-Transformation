"""Mapper tests for the isolated CICS modernization lane."""

from engine.cics.mapper import CicsSpringMapper
from engine.cics.model import (
    CicsBoundaryKind,
    CicsConstructStatus,
    CicsExplicitKind,
    CicsInteractionKind,
    CicsResourceKind,
    CicsService,
    CicsTerminalIoKind,
)
from engine.transformation.cics_parser import CicsParser


def _service(text: str, program_id: str = "DEMOPGM") -> CicsService:
    parsed = CicsParser().parse_embedded_cics(text)
    return CicsSpringMapper().map(parsed, program_id=program_id).services[0]


def test_send_maps_request_response():
    terminal = _service(
        "SEND MAP(OUTMAP) MAPSET(OUTSET) FROM(:WS-DATA) LENGTH(:WS-LEN)"
    ).terminal_ios[0]
    assert terminal.kind == CicsTerminalIoKind.SEND
    assert terminal.map_name == "OUTMAP"
    assert terminal.mapset_name == "OUTSET"
    assert terminal.data_field == "WS-DATA"
    assert terminal.length_field == "WS-LEN"


def test_receive_maps_request_response():
    terminal = _service(
        "RECEIVE MAP(INMAP) INTO(:WS-IN) LENGTH(:WS-LEN)"
    ).terminal_ios[0]
    assert terminal.kind == CicsTerminalIoKind.RECEIVE
    assert terminal.map_name == "INMAP"
    assert terminal.data_field == "WS-IN"
    assert terminal.length_field == "WS-LEN"


def test_link_maps_program_interaction():
    interaction = _service(
        "LINK PROGRAM(NEXTPGM) COMMAREA(:WS-CA) LENGTH(:WS-LEN)"
    ).program_interactions[0]
    assert interaction.kind == CicsInteractionKind.LINK
    assert interaction.program == "NEXTPGM"
    assert interaction.commarea == "WS-CA"
    assert interaction.commarea_length == "WS-LEN"


def test_xctl_maps_program_interaction():
    interaction = _service("XCTL PROGRAM(OTHERPGM)").program_interactions[0]
    assert interaction.kind == CicsInteractionKind.XCTL
    assert interaction.program == "OTHERPGM"


def test_return_creates_interaction_and_pseudo_conversational_boundary():
    service = _service("RETURN TRANSID(NEXT)")
    interaction = service.program_interactions[0]
    boundary = service.transaction_boundaries[0]
    assert interaction.kind == CicsInteractionKind.RETURN
    assert boundary.kind == CicsBoundaryKind.PSEUDO_CONVERSATIONAL
    assert boundary.transaction_id == "NEXT"
    assert interaction.raw_text == boundary.raw_text == "RETURN TRANSID(NEXT)"
    assert service.is_transactional


def test_syncpoint_maps_to_commit():
    service = _service("SYNCPOINT")
    assert service.transaction_boundaries[0].kind == CicsBoundaryKind.COMMIT
    assert service.is_transactional


def test_abend_maps_to_rollback():
    service = _service("ABEND")
    assert service.transaction_boundaries[0].kind == CicsBoundaryKind.ROLLBACK
    assert service.is_transactional


def test_file_crud_operations_map_as_files():
    cases = {
        "READ DATASET(CUSTFILE) INTO(:WS-CUST) RIDFLD(:WS-ID)": "READ",
        "WRITE DATASET(AUDIT) FROM(:WS-AUDIT) LENGTH(:WS-LEN)": "WRITE",
        "REWRITE DATASET(CUSTFILE) FROM(:WS-CUST) LENGTH(:WS-LEN)": "REWRITE",
        "DELETE DATASET(CUSTFILE) RIDFLD(:WS-ID)": "DELETE",
    }
    for text, operation in cases.items():
        access = _service(text).resource_accesses[0]
        assert access.operation == operation
        assert access.resource_kind == CicsResourceKind.FILE


def test_browse_operations_map_as_files():
    cases = {
        "STARTBR DATASET(CUSTFILE) RIDFLD(:WS-ID)": "STARTBR",
        "READNEXT DATASET(CUSTFILE) INTO(:WS-CUST) LENGTH(:WS-LEN)": "READNEXT",
        "READPREV DATASET(CUSTFILE) INTO(:WS-CUST) LENGTH(:WS-LEN)": "READPREV",
        "ENDBR DATASET(CUSTFILE)": "ENDBR",
    }
    for text, operation in cases.items():
        access = _service(text).resource_accesses[0]
        assert access.operation == operation
        assert access.resource_kind == CicsResourceKind.FILE


def test_queue_operations_map_as_queues():
    cases = {
        "WRITEQ TS QNAME(ORDERQ) FROM(:WS-ORD) LENGTH(:WS-LEN)": "WRITEQ",
        "READQ TS QNAME(ORDERQ) INTO(:WS-ORD) LENGTH(:WS-LEN)": "READQ",
        "DELETEQ TS QNAME(ORDERQ)": "DELETEQ",
    }
    for text, operation in cases.items():
        access = _service(text).resource_accesses[0]
        assert access.operation == operation
        assert access.resource_kind == CicsResourceKind.QUEUE
        assert access.resource == "ORDERQ"


def test_explicit_only_constructs_are_carried_verbatim():
    handle = _service("HANDLE CONDITION NOTFND(NOT-FOUND)").explicit_constructs[0]
    aid = _service("HANDLE AID PF3(PF3-RTN)").explicit_constructs[0]
    assign = _service("ASSIGN APPLID(:WS-APPLID)").explicit_constructs[0]
    assert handle.kind == CicsExplicitKind.HANDLE_CONDITION
    assert "NOTFND(NOT-FOUND)" in handle.raw_text
    assert aid.kind == CicsExplicitKind.HANDLE_AID
    assert "PF3(PF3-RTN)" in aid.raw_text
    assert assign.kind == CicsExplicitKind.ASSIGN
    assert "APPLID(:WS-APPLID)" in assign.raw_text


def test_explicit_only_flow_steps_are_not_runtime_behavior():
    service = _service("HANDLE CONDITION NOTFND(NOT-FOUND)")
    assert service.flow[0].status == CicsConstructStatus.EXPLICIT_ONLY
    assert service.unsupported_constructs == ()


def test_unsupported_constructs_stay_explicit():
    service = _service("ALLOCATE")
    unsupported = service.unsupported_constructs[0]
    assert unsupported.command == "ALLOCATE"
    assert unsupported.raw_text == "ALLOCATE"
    assert "outside the supported" in unsupported.reason
    assert service.flow[0].status == CicsConstructStatus.UNSUPPORTED


def test_command_order_is_preserved():
    service = _service(
        "SEND MAP(FIRST)\n"
        "READ DATASET(CUSTFILE) RIDFLD(:WS-ID)\n"
        "SYNCPOINT\n"
        "RETURN TRANSID(NEXT)"
    )
    assert [step.step_kind for step in service.flow] == [
        "SEND",
        "READ",
        "SYNCPOINT",
        "RETURN",
    ]
    assert [step.index for step in service.flow] == [0, 1, 2, 3]


def test_transactional_signals_mark_service_transactional():
    assert _service("WRITE DATASET(AUDIT) FROM(:WS-A)").is_transactional
    assert _service("LINK PROGRAM(NEXTPGM)").is_transactional
    assert _service("XCTL PROGRAM(NEXTPGM)").is_transactional


def test_pure_terminal_io_is_not_transactional():
    assert not _service("SEND MAP(OUTMAP)").is_transactional
    assert not _service("RECEIVE MAP(INMAP)").is_transactional
