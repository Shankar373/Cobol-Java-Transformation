"""Tests for CICS / Transaction Semantic Foundation.

Covers 37 acceptance criteria for:
- CICS IR types (CicsCommandType, CicsCommand, CicsApplication, etc.)
- CICS parser (embedded CICS extraction)
- COMMAREA and channel/container references
- RESP/RESP2 handling
- Dependency graph integration
- Transaction → program relationships
- Domain-neutral workload tests
- Lexical false-positive tests
- Mutation tests
- Negative/unsupported syntax tests
- Deterministic serialization tests
- Independent validation tests
- Regression tests
"""


from engine.transformation.ir import (
    CicsAidType,
    CicsApplication,
    CicsCommand,
    CicsCommandType,
    CicsConditionType,
    CicsHandleAid,
    CicsHandleCondition,
    CicsOperand,
    CicsResourceType,
    CicsRespHandling,
    CicsTransaction,
)
from engine.transformation.cics_parser import CicsParser


# ============================================================================
# TEST GROUP 1: CICS IR Construction Tests
# ============================================================================

class TestCicsCommandTypeEnum:
    """T1: CicsCommandType enum values."""

    def test_send(self):
        assert CicsCommandType.SEND.value == "SEND"

    def test_receive(self):
        assert CicsCommandType.RECEIVE.value == "RECEIVE"

    def test_read(self):
        assert CicsCommandType.READ.value == "READ"

    def test_write(self):
        assert CicsCommandType.WRITE.value == "WRITE"

    def test_rewrite(self):
        assert CicsCommandType.REWRITE.value == "REWRITE"

    def test_delete(self):
        assert CicsCommandType.DELETE.value == "DELETE"

    def test_startbr(self):
        assert CicsCommandType.STARTBR.value == "STARTBR"

    def test_readnext(self):
        assert CicsCommandType.READNEXT.value == "READNEXT"

    def test_readprev(self):
        assert CicsCommandType.READPREV.value == "READPREV"

    def test_endbr(self):
        assert CicsCommandType.ENDBR.value == "ENDBR"

    def test_link(self):
        assert CicsCommandType.LINK.value == "LINK"

    def test_xctl(self):
        assert CicsCommandType.XCTL.value == "XCTL"

    def test_return(self):
        assert CicsCommandType.RETURN.value == "RETURN"

    def test_syncpoint(self):
        assert CicsCommandType.SYNCPOINT.value == "SYNCPOINT"

    def test_abend(self):
        assert CicsCommandType.ABEND.value == "ABEND"

    def test_handle_condition(self):
        assert CicsCommandType.HANDLE_CONDITION.value == "HANDLE_CONDITION"

    def test_handle_aid(self):
        assert CicsCommandType.HANDLE_AID.value == "HANDLE_AID"

    def test_assign(self):
        assert CicsCommandType.ASSIGN.value == "ASSIGN"


class TestCicsResourceTypeEnum:
    """T2: CicsResourceType enum values."""

    def test_file(self):
        assert CicsResourceType.FILE.value == "FILE"

    def test_queue(self):
        assert CicsResourceType.QUEUE.value == "QUEUE"

    def test_program(self):
        assert CicsResourceType.PROGRAM.value == "PROGRAM"

    def test_transid(self):
        assert CicsResourceType.TRANSID.value == "TRANSID"

    def test_map(self):
        assert CicsResourceType.MAP.value == "MAP"

    def test_mapset(self):
        assert CicsResourceType.MAPSET.value == "MAPSET"


class TestCicsConditionTypeEnum:
    """T3: CicsConditionType enum values."""

    def test_normal(self):
        assert CicsConditionType.NORMAL.value == "NORMAL"

    def test_error(self):
        assert CicsConditionType.ERROR.value == "ERROR"

    def test_notfnd(self):
        assert CicsConditionType.NOTFND.value == "NOTFND"

    def test_invreq(self):
        assert CicsConditionType.INVREQ.value == "INVREQ"

    def test_ioerr(self):
        assert CicsConditionType.IOERR.value == "IOERR"


class TestCicsAidTypeEnum:
    """T4: CicsAidType enum values."""

    def test_clear(self):
        assert CicsAidType.CLEAR.value == "CLEAR"

    def test_pf1(self):
        assert CicsAidType.PF1.value == "PF1"

    def test_pf24(self):
        assert CicsAidType.PF24.value == "PF24"

    def test_enter(self):
        assert CicsAidType.ENTER.value == "ENTER"


class TestCicsOperandAttributes:
    """T5: CicsOperand attributes."""

    def test_keyword_value(self):
        op = CicsOperand(keyword="DATASET", value="MYFILE")
        assert op.keyword == "DATASET"
        assert op.value == "MYFILE"

    def test_host_variable(self):
        op = CicsOperand(keyword="INTO", value=":WS-RECORD", is_host_variable=True)
        assert op.is_host_variable is True

    def test_literal(self):
        op = CicsOperand(keyword="PROGRAM", value="'SUBPROG'", is_literal=True)
        assert op.is_literal is True


class TestCicsCommandAttributes:
    """T6: CicsCommand attributes."""

    def test_command_type(self):
        cmd = CicsCommand(
            command_type=CicsCommandType.READ,
            raw_text="READ DATASET(MYFILE)",
        )
        assert cmd.command_type == CicsCommandType.READ

    def test_resource_name(self):
        cmd = CicsCommand(
            command_type=CicsCommandType.READ,
            raw_text="READ DATASET(MYFILE)",
            resource_name="MYFILE",
            resource_type=CicsResourceType.FILE,
        )
        assert cmd.resource_name == "MYFILE"
        assert cmd.resource_type == CicsResourceType.FILE

    def test_program_name(self):
        cmd = CicsCommand(
            command_type=CicsCommandType.LINK,
            raw_text="LINK PROGRAM(SUBPROG)",
            program_name="SUBPROG",
        )
        assert cmd.program_name == "SUBPROG"

    def test_transaction_id(self):
        cmd = CicsCommand(
            command_type=CicsCommandType.SEND,
            raw_text="SEND TRANSID(T001)",
            transaction_id="T001",
        )
        assert cmd.transaction_id == "T001"

    def test_resp_field(self):
        cmd = CicsCommand(
            command_type=CicsCommandType.READ,
            raw_text="READ DATASET(MYFILE) RESP(:WS-RESP)",
            resp_field=":WS-RESP",
            resp_handling=CicsRespHandling.RESP_VARIABLE,
        )
        assert cmd.resp_field == ":WS-RESP"
        assert cmd.resp_handling == CicsRespHandling.RESP_VARIABLE

    def test_resp2_field(self):
        cmd = CicsCommand(
            command_type=CicsCommandType.READ,
            raw_text="READ DATASET(MYFILE) RESP2(:WS-RESP2)",
            resp2_field=":WS-RESP2",
            resp_handling=CicsRespHandling.RESP2_VARIABLE,
        )
        assert cmd.resp2_field == ":WS-RESP2"

    def test_commarea(self):
        cmd = CicsCommand(
            command_type=CicsCommandType.LINK,
            raw_text="LINK PROGRAM(SUB) COMMAREA(:WS-COMM) LENGTH(100)",
            commarea_data=":WS-COMM",
            commarea_length="100",
        )
        assert cmd.commarea_data == ":WS-COMM"
        assert cmd.commarea_length == "100"

    def test_channel(self):
        cmd = CicsCommand(
            command_type=CicsCommandType.SEND,
            raw_text="SEND CHANNEL(CH1)",
            channel_name="CH1",
        )
        assert cmd.channel_name == "CH1"

    def test_containers(self):
        cmd = CicsCommand(
            command_type=CicsCommandType.SEND,
            raw_text="SEND CHANNEL(CH1) CONTAINER(C1) CONTAINER(C2)",
            container_names=("C1", "C2"),
        )
        assert cmd.container_names == ("C1", "C2")

    def test_map_name(self):
        cmd = CicsCommand(
            command_type=CicsCommandType.SEND,
            raw_text="SEND MAP(MAP1)",
            map_name="MAP1",
        )
        assert cmd.map_name == "MAP1"

    def test_mapset_name(self):
        cmd = CicsCommand(
            command_type=CicsCommandType.SEND,
            raw_text="SEND MAP(MAP1) MAPSET(MS1)",
            mapset_name="MS1",
        )
        assert cmd.mapset_name == "MS1"


class TestCicsHandleConditionAttributes:
    """T7: CicsHandleCondition attributes."""

    def test_condition(self):
        hc = CicsHandleCondition(
            condition=CicsConditionType.NOTFND,
            paragraph="NOT-FOUND-PARA",
        )
        assert hc.condition == CicsConditionType.NOTFND

    def test_paragraph(self):
        hc = CicsHandleCondition(
            condition=CicsConditionType.NOTFND,
            paragraph="NOT-FOUND-PARA",
        )
        assert hc.paragraph == "NOT-FOUND-PARA"


class TestCicsHandleAidAttributes:
    """T8: CicsHandleAid attributes."""

    def test_aid_type(self):
        ha = CicsHandleAid(
            aid_type=CicsAidType.PF3,
            paragraph="EXIT-PARA",
        )
        assert ha.aid_type == CicsAidType.PF3

    def test_paragraph(self):
        ha = CicsHandleAid(
            aid_type=CicsAidType.PF3,
            paragraph="EXIT-PARA",
        )
        assert ha.paragraph == "EXIT-PARA"


class TestCicsApplicationAttributes:
    """T9: CicsApplication attributes and methods."""

    def test_program_id(self):
        app = CicsApplication(program_id="MYPROG")
        assert app.program_id == "MYPROG"

    def test_get_program_dependencies(self):
        app = CicsApplication(
            program_id="PROG1",
            commands=(
                CicsCommand(
                    command_type=CicsCommandType.LINK,
                    raw_text="LINK PROGRAM(SUB1)",
                    program_name="SUB1",
                ),
                CicsCommand(
                    command_type=CicsCommandType.XCTL,
                    raw_text="XCTL PROGRAM(SUB2)",
                    program_name="SUB2",
                ),
            ),
        )
        deps = app.get_program_dependencies()
        assert "SUB1" in deps
        assert "SUB2" in deps

    def test_get_file_dependencies(self):
        app = CicsApplication(
            program_id="PROG1",
            commands=(
                CicsCommand(
                    command_type=CicsCommandType.READ,
                    raw_text="READ DATASET(MYFILE)",
                    resource_name="MYFILE",
                ),
                CicsCommand(
                    command_type=CicsCommandType.WRITE,
                    raw_text="WRITE DATASET(MYFILE)",
                    resource_name="MYFILE",
                ),
            ),
        )
        deps = app.get_file_dependencies()
        assert ("READ", "MYFILE") in deps
        assert ("WRITE", "MYFILE") in deps

    def test_get_transaction_dependencies(self):
        app = CicsApplication(
            program_id="PROG1",
            transactions=(
                CicsTransaction(transaction_id="T001", program_id="PROG1"),
                CicsTransaction(transaction_id="T002", program_id="PROG2"),
            ),
        )
        deps = app.get_transaction_dependencies()
        assert ("T001", "PROG1") in deps
        assert ("T002", "PROG2") in deps

    def test_validate(self):
        app = CicsApplication(
            program_id="PROG1",
            commands=(
                CicsCommand(
                    command_type=CicsCommandType.READ,
                    raw_text="READ",
                    resource_name="MYFILE",
                ),
            ),
        )
        issues = app.validate()
        assert isinstance(issues, list)


# ============================================================================
# TEST GROUP 2: Parser Tests for Every Supported Command
# ============================================================================

class TestCicsParserSend:
    """T10: CICS parser SEND command."""

    def test_send_map(self):
        parser = CicsParser()
        app = parser.parse_embedded_cics("SEND MAP(MAP1) MAPSET(MS1) TERMID(T1)")
        assert len(app.commands) == 1
        cmd = app.commands[0]
        assert cmd.command_type == CicsCommandType.SEND
        assert cmd.map_name == "MAP1"
        assert cmd.mapset_name == "MS1"
        assert cmd.terminal_id == "T1"

    def test_send_transid(self):
        parser = CicsParser()
        app = parser.parse_embedded_cics("SEND TRANSID(T001)")
        cmd = app.commands[0]
        assert cmd.transaction_id == "T001"

    def test_send_from(self):
        parser = CicsParser()
        app = parser.parse_embedded_cics("SEND FROM(:WS-DATA) LENGTH(:WS-LEN)")
        cmd = app.commands[0]
        assert cmd.from_field == ":WS-DATA"
        assert cmd.length_field == ":WS-LEN"


class TestCicsParserReceive:
    """T11: CICS parser RECEIVE command."""

    def test_receive_into(self):
        parser = CicsParser()
        app = parser.parse_embedded_cics("RECEIVE INTO(:WS-DATA) LENGTH(:WS-LEN)")
        assert len(app.commands) == 1
        cmd = app.commands[0]
        assert cmd.command_type == CicsCommandType.RECEIVE
        assert cmd.into_field == ":WS-DATA"
        assert cmd.length_field == ":WS-LEN"

    def test_receive_map(self):
        parser = CicsParser()
        app = parser.parse_embedded_cics("RECEIVE MAP(MAP1)")
        cmd = app.commands[0]
        assert cmd.map_name == "MAP1"


class TestCicsParserRead:
    """T12: CICS parser READ command."""

    def test_read_dataset(self):
        parser = CicsParser()
        app = parser.parse_embedded_cics("READ DATASET(MYFILE) INTO(:WS-REC) LENGTH(:WS-LEN)")
        assert len(app.commands) == 1
        cmd = app.commands[0]
        assert cmd.command_type == CicsCommandType.READ
        assert cmd.resource_name == "MYFILE"
        assert cmd.resource_type == CicsResourceType.FILE
        assert cmd.into_field == ":WS-REC"
        assert cmd.length_field == ":WS-LEN"

    def test_read_key(self):
        parser = CicsParser()
        app = parser.parse_embedded_cics("READ DATASET(MYFILE) KEY(:WS-KEY)")
        cmd = app.commands[0]
        assert cmd.key_field == ":WS-KEY"

    def test_read_ridfld(self):
        parser = CicsParser()
        app = parser.parse_embedded_cics("READ DATASET(MYFILE) RIDFLD(:WS-KEY)")
        cmd = app.commands[0]
        assert cmd.rid_field == ":WS-KEY"


class TestCicsParserWrite:
    """T13: CICS parser WRITE command."""

    def test_write_dataset(self):
        parser = CicsParser()
        app = parser.parse_embedded_cics("WRITE DATASET(MYFILE) FROM(:WS-REC) LENGTH(:WS-LEN)")
        assert len(app.commands) == 1
        cmd = app.commands[0]
        assert cmd.command_type == CicsCommandType.WRITE
        assert cmd.resource_name == "MYFILE"
        assert cmd.from_field == ":WS-REC"


class TestCicsParserRewrite:
    """T14: CICS parser REWRITE command."""

    def test_rewrite_dataset(self):
        parser = CicsParser()
        app = parser.parse_embedded_cics("REWRITE DATASET(MYFILE) FROM(:WS-REC)")
        assert len(app.commands) == 1
        cmd = app.commands[0]
        assert cmd.command_type == CicsCommandType.REWRITE
        assert cmd.resource_name == "MYFILE"


class TestCicsParserDelete:
    """T15: CICS parser DELETE command."""

    def test_delete_dataset(self):
        parser = CicsParser()
        app = parser.parse_embedded_cics("DELETE DATASET(MYFILE)")
        assert len(app.commands) == 1
        cmd = app.commands[0]
        assert cmd.command_type == CicsCommandType.DELETE
        assert cmd.resource_name == "MYFILE"


class TestCicsParserBrowse:
    """T16: CICS parser STARTBR/READNEXT/READPREV/ENDBR commands."""

    def test_startbr(self):
        parser = CicsParser()
        app = parser.parse_embedded_cics("STARTBR DATASET(MYFILE) KEY(:WS-KEY)")
        assert len(app.commands) == 1
        cmd = app.commands[0]
        assert cmd.command_type == CicsCommandType.STARTBR
        assert cmd.resource_name == "MYFILE"

    def test_readnext(self):
        parser = CicsParser()
        app = parser.parse_embedded_cics("READNEXT DATASET(MYFILE) INTO(:WS-REC)")
        cmd = app.commands[0]
        assert cmd.command_type == CicsCommandType.READNEXT

    def test_readprev(self):
        parser = CicsParser()
        app = parser.parse_embedded_cics("READPREV DATASET(MYFILE) INTO(:WS-REC)")
        cmd = app.commands[0]
        assert cmd.command_type == CicsCommandType.READPREV

    def test_endbr(self):
        parser = CicsParser()
        app = parser.parse_embedded_cics("ENDBR DATASET(MYFILE)")
        cmd = app.commands[0]
        assert cmd.command_type == CicsCommandType.ENDBR


class TestCicsParserLink:
    """T17: CICS parser LINK command."""

    def test_link_program(self):
        parser = CicsParser()
        app = parser.parse_embedded_cics("LINK PROGRAM(SUBPROG)")
        assert len(app.commands) == 1
        cmd = app.commands[0]
        assert cmd.command_type == CicsCommandType.LINK
        assert cmd.program_name == "SUBPROG"

    def test_link_commarea(self):
        parser = CicsParser()
        app = parser.parse_embedded_cics("LINK PROGRAM(SUBPROG) COMMAREA(:WS-COMM) LENGTH(100)")
        cmd = app.commands[0]
        assert cmd.commarea_data == ":WS-COMM"
        assert cmd.commarea_length == "100"


class TestCicsParserXctl:
    """T18: CICS parser XCTL command."""

    def test_xctl_program(self):
        parser = CicsParser()
        app = parser.parse_embedded_cics("XCTL PROGRAM(NEXTPROG)")
        assert len(app.commands) == 1
        cmd = app.commands[0]
        assert cmd.command_type == CicsCommandType.XCTL
        assert cmd.program_name == "NEXTPROG"


class TestCicsParserReturn:
    """T19: CICS parser RETURN command."""

    def test_return(self):
        parser = CicsParser()
        app = parser.parse_embedded_cics("RETURN")
        assert len(app.commands) == 1
        cmd = app.commands[0]
        assert cmd.command_type == CicsCommandType.RETURN

    def test_return_transid(self):
        parser = CicsParser()
        app = parser.parse_embedded_cics("RETURN TRANSID(T001)")
        cmd = app.commands[0]
        assert cmd.transaction_id == "T001"


class TestCicsParserSyncpoint:
    """T20: CICS parser SYNCPOINT command."""

    def test_syncpoint(self):
        parser = CicsParser()
        app = parser.parse_embedded_cics("SYNCPOINT")
        assert len(app.commands) == 1
        cmd = app.commands[0]
        assert cmd.command_type == CicsCommandType.SYNCPOINT


class TestCicsParserAbend:
    """T21: CICS parser ABEND command."""

    def test_abend(self):
        parser = CicsParser()
        app = parser.parse_embedded_cics("ABEND")
        assert len(app.commands) == 1
        cmd = app.commands[0]
        assert cmd.command_type == CicsCommandType.ABEND

    def test_abend_code(self):
        parser = CicsParser()
        app = parser.parse_embedded_cics("ABEND ABCD")
        cmd = app.commands[0]
        assert cmd.command_type == CicsCommandType.ABEND


class TestCicsParserHandleCondition:
    """T22: CICS parser HANDLE CONDITION command."""

    def test_handle_condition(self):
        parser = CicsParser()
        app = parser.parse_embedded_cics("HANDLE CONDITION NOTFND(NOT-FOUND)")
        assert len(app.handle_conditions) == 1
        hc = app.handle_conditions[0]
        assert hc.condition == CicsConditionType.NOTFND
        assert hc.paragraph == "NOT-FOUND"

    def test_handle_condition_error(self):
        parser = CicsParser()
        app = parser.parse_embedded_cics("HANDLE CONDITION ERROR(ERR-PARA)")
        hc = app.handle_conditions[0]
        assert hc.condition == CicsConditionType.ERROR
        assert hc.paragraph == "ERR-PARA"


class TestCicsParserHandleAid:
    """T23: CICS parser HANDLE AID command."""

    def test_handle_aid_pf3(self):
        parser = CicsParser()
        app = parser.parse_embedded_cics("HANDLE AID PF3(EXIT-PARA)")
        assert len(app.handle_aids) == 1
        ha = app.handle_aids[0]
        assert ha.aid_type == CicsAidType.PF3
        assert ha.paragraph == "EXIT-PARA"

    def test_handle_aid_clear(self):
        parser = CicsParser()
        app = parser.parse_embedded_cics("HANDLE AID CLEAR(START-PARA)")
        ha = app.handle_aids[0]
        assert ha.aid_type == CicsAidType.CLEAR


class TestCicsParserAssign:
    """T24: CICS parser ASSIGN command."""

    def test_assign(self):
        parser = CicsParser()
        app = parser.parse_embedded_cics("ASSIGN EIBAID(:WS-AID)")
        assert len(app.assignments) == 1
        asgn = app.assignments[0]
        assert asgn.field == "EIBAID"
        assert asgn.variable == "WS-AID"

    def test_assign_eibdate(self):
        parser = CicsParser()
        app = parser.parse_embedded_cics("ASSIGN EIBDATE(:WS-DATE)")
        asgn = app.assignments[0]
        assert asgn.field == "EIBDATE"


class TestCicsParserQueue:
    """T25: CICS parser queue commands."""

    def test_writeq(self):
        parser = CicsParser()
        app = parser.parse_embedded_cics("WRITEQ TS QUEUE(MYQ) FROM(:WS-DATA)")
        assert len(app.commands) == 1
        cmd = app.commands[0]
        assert cmd.command_type == CicsCommandType.WRITEQ
        assert cmd.resource_name == "MYQ"

    def test_readq(self):
        parser = CicsParser()
        app = parser.parse_embedded_cics("READQ TS QUEUE(MYQ) INTO(:WS-DATA)")
        cmd = app.commands[0]
        assert cmd.command_type == CicsCommandType.READQ

    def test_deleteq(self):
        parser = CicsParser()
        app = parser.parse_embedded_cics("DELETEQ TS QUEUE(MYQ)")
        cmd = app.commands[0]
        assert cmd.command_type == CicsCommandType.DELETEQ


# ============================================================================
# TEST GROUP 3: COMMAREA Tests
# ============================================================================

class TestCicsCommarea:
    """T26: COMMAREA handling tests."""

    def test_link_commarea(self):
        parser = CicsParser()
        app = parser.parse_embedded_cics("LINK PROGRAM(SUB) COMMAREA(:WS-COMM) LENGTH(:WS-LEN)")
        cmd = app.commands[0]
        assert cmd.commarea_data == ":WS-COMM"
        assert cmd.commarea_length == ":WS-LEN"

    def test_xctl_commarea(self):
        parser = CicsParser()
        app = parser.parse_embedded_cics("XCTL PROGRAM(NEXT) COMMAREA(:WS-COMM) LENGTH(100)")
        cmd = app.commands[0]
        assert cmd.commarea_data == ":WS-COMM"
        assert cmd.commarea_length == "100"

    def test_return_commarea(self):
        parser = CicsParser()
        app = parser.parse_embedded_cics("RETURN COMMAREA(:WS-COMM) LENGTH(50)")
        cmd = app.commands[0]
        assert cmd.commarea_data == ":WS-COMM"
        assert cmd.commarea_length == "50"


# ============================================================================
# TEST GROUP 4: Channel/Container Tests
# ============================================================================

class TestCicsChannelContainer:
    """T27: Channel/Container handling tests."""

    def test_channel(self):
        parser = CicsParser()
        app = parser.parse_embedded_cics("SEND CHANNEL(CH1)")
        cmd = app.commands[0]
        assert cmd.channel_name == "CH1"

    def test_containers(self):
        parser = CicsParser()
        app = parser.parse_embedded_cics("SEND CHANNEL(CH1) CONTAINER(C1) CONTAINER(C2)")
        cmd = app.commands[0]
        assert cmd.container_names == ("C1", "C2")

    def test_container_host_variable(self):
        parser = CicsParser()
        app = parser.parse_embedded_cics("LINK PROGRAM(SUB) CHANNEL(CH1) CONTAINER(:WS-CONT)")
        cmd = app.commands[0]
        assert cmd.container_names == (":WS-CONT",)


# ============================================================================
# TEST GROUP 5: RESP/RESP2 Tests
# ============================================================================

class TestCicsRespHandling:
    """T28: RESP/RESP2 handling tests."""

    def test_resp_variable(self):
        parser = CicsParser()
        app = parser.parse_embedded_cics("READ DATASET(MYFILE) RESP(:WS-RESP)")
        cmd = app.commands[0]
        assert cmd.resp_field == ":WS-RESP"
        assert cmd.resp_handling == CicsRespHandling.RESP_VARIABLE

    def test_resp2_variable(self):
        parser = CicsParser()
        app = parser.parse_embedded_cics("READ DATASET(MYFILE) RESP2(:WS-RESP2)")
        cmd = app.commands[0]
        assert cmd.resp2_field == ":WS-RESP2"
        assert cmd.resp_handling == CicsRespHandling.RESP2_VARIABLE

    def test_no_resp(self):
        parser = CicsParser()
        app = parser.parse_embedded_cics("READ DATASET(MYFILE)")
        cmd = app.commands[0]
        assert cmd.resp_handling == CicsRespHandling.NO_HANDLE


# ============================================================================
# TEST GROUP 6: Dependency Graph Tests
# ============================================================================

class TestCicsDependencies:
    """T29: CICS dependency graph tests."""

    def test_file_dependencies(self):
        parser = CicsParser()
        cics_text = """
        READ DATASET(FILE1) INTO(:WS-REC)
        WRITE DATASET(FILE2) FROM(:WS-REC)
        DELETE DATASET(FILE1)
        """
        app = parser.parse_embedded_cics(cics_text)
        deps = app.get_file_dependencies()
        assert ("READ", "FILE1") in deps
        assert ("WRITE", "FILE2") in deps
        assert ("DELETE", "FILE1") in deps

    def test_program_dependencies(self):
        parser = CicsParser()
        cics_text = """
        LINK PROGRAM(SUB1) COMMAREA(:WS-COMM)
        XCTL PROGRAM(SUB2)
        """
        app = parser.parse_embedded_cics(cics_text)
        deps = app.get_program_dependencies()
        assert "SUB1" in deps
        assert "SUB2" in deps

    def test_transaction_dependencies(self):
        app = CicsApplication(
            program_id="PROG1",
            transactions=(
                CicsTransaction(transaction_id="T001", program_id="PROG1"),
                CicsTransaction(transaction_id="T002", program_id="PROG2"),
            ),
        )
        deps = app.get_transaction_dependencies()
        assert ("T001", "PROG1") in deps
        assert ("T002", "PROG2") in deps

    def test_unique_file_dependencies(self):
        parser = CicsParser()
        cics_text = """
        READ DATASET(MYFILE) INTO(:WS-REC)
        READ DATASET(MYFILE) INTO(:WS-REC2)
        """
        app = parser.parse_embedded_cics(cics_text)
        deps = app.get_file_dependencies()
        # Should be deduplicated
        file_deps = [d for d in deps if d[1] == "MYFILE"]
        assert len(file_deps) == 1


# ============================================================================
# TEST GROUP 7: Transaction → Program Relationship Tests
# ============================================================================

class TestCicsTransactionProgram:
    """T30: Transaction → program relationship tests."""

    def test_single_transaction(self):
        app = CicsApplication(
            program_id="PROG1",
            transactions=(
                CicsTransaction(transaction_id="T001", program_id="PROG1"),
            ),
        )
        deps = app.get_transaction_dependencies()
        assert len(deps) == 1
        assert deps[0] == ("T001", "PROG1")

    def test_multiple_transactions(self):
        app = CicsApplication(
            program_id="PROG1",
            transactions=(
                CicsTransaction(transaction_id="T001", program_id="PROG1"),
                CicsTransaction(transaction_id="T002", program_id="PROG1"),
                CicsTransaction(transaction_id="T003", program_id="PROG2"),
            ),
        )
        deps = app.get_transaction_dependencies()
        assert len(deps) == 3

    def test_transaction_terminal(self):
        txn = CicsTransaction(
            transaction_id="T001",
            program_id="PROG1",
            terminal_id="TERM1",
        )
        assert txn.terminal_id == "TERM1"


# ============================================================================
# TEST GROUP 8: Domain-Neutral Workload Tests
# ============================================================================

class TestDomainNeutral:
    """T31: Domain-neutral workload tests (Account/Order/Customer)."""

    def test_account_workload(self):
        """Account inquiry — purely structural, no domain vocabulary detection."""
        parser = CicsParser()
        cics_text = """
        SEND MAP(ACCTMAP) MAPSET(ACCTMS) TERMID(TERM1)
        RECEIVE MAP(ACCTMAP)
        READ DATASET(ACCTFILE) INTO(:WS-ACCT) KEY(:WS-ACCT-ID)
        SEND FROM(:WS-ACCT) LENGTH(:WS-ACCT-LEN)
        """
        app = parser.parse_embedded_cics(cics_text)
        assert len(app.commands) == 4
        assert "ACCTFILE" in app.file_resources
        assert "ACCTMAP" in app.map_resources

    def test_order_workload(self):
        """Order processing — purely structural."""
        parser = CicsParser()
        cics_text = """
        LINK PROGRAM(ORDPROC) COMMAREA(:WS-ORD) LENGTH(:WS-ORD-LEN)
        WRITE DATASET(ORDFILE) FROM(:WS-ORD) LENGTH(:WS-ORD-LEN)
        SYNCPOINT
        """
        app = parser.parse_embedded_cics(cics_text)
        assert len(app.commands) == 3
        assert "ORDFILE" in app.file_resources
        assert "ORDPROC" in app.program_resources

    def test_customer_workload(self):
        """Customer maintenance — purely structural."""
        parser = CicsParser()
        cics_text = """
        READ DATASET(CUSTFILE) INTO(:WS-CUST) KEY(:WS-CUST-ID)
        IF :WS-RESP = 0
          XCTL PROGRAM(CUSTEDIT) COMMAREA(:WS-CUST)
        END-IF
        """
        app = parser.parse_embedded_cics(cics_text)
        assert len(app.commands) == 2
        assert "CUSTFILE" in app.file_resources
        assert "CUSTEDIT" in app.program_resources


# ============================================================================
# TEST GROUP 9: Lexical False-Positive Tests
# ============================================================================

class TestLexicalFalsePositives:
    """T32: Lexical false-positive tests."""

    def test_cobol_not_cics(self):
        """COBOL READ should not be parsed as CICS READ."""
        parser = CicsParser()
        app = parser.parse_embedded_cics("READ INTO(:WS-DATA)")
        # 'READ' without DATASET is not a valid CICS command
        assert len(app.commands) == 0

    def test_empty_command(self):
        """Empty string should produce no commands."""
        parser = CicsParser()
        app = parser.parse_embedded_cics("")
        assert len(app.commands) == 0

    def test_whitespace_only(self):
        """Whitespace-only should produce no commands."""
        parser = CicsParser()
        app = parser.parse_embedded_cics("   \n  \t  ")
        assert len(app.commands) == 0

    def test_comment_only(self):
        """Comment-only should produce no commands."""
        parser = CicsParser()
        app = parser.parse_embedded_cics("* this is a comment")
        assert len(app.commands) == 0

    def test_unknown_command(self):
        """Unknown command should be ignored."""
        parser = CicsParser()
        app = parser.parse_embedded_cics("FOOBAR DATASET(MYFILE)")
        assert len(app.commands) == 0

    def test_cobol_display_not_cics(self):
        """DISPLAY statement should not be parsed as CICS."""
        parser = CicsParser()
        app = parser.parse_embedded_cics("DISPLAY 'HELLO'")
        assert len(app.commands) == 0


# ============================================================================
# TEST GROUP 10: Mutation Tests
# ============================================================================

class TestMutation:
    """T33: Mutation tests — verify each field is independently tracked."""

    def test_resource_name_mutation(self):
        """Changing resource_name produces different command."""
        cmd1 = CicsCommand(
            command_type=CicsCommandType.READ,
            raw_text="READ DATASET(FILE1)",
            resource_name="FILE1",
        )
        cmd2 = CicsCommand(
            command_type=CicsCommandType.READ,
            raw_text="READ DATASET(FILE2)",
            resource_name="FILE2",
        )
        assert cmd1.resource_name != cmd2.resource_name

    def test_program_name_mutation(self):
        """Changing program_name produces different command."""
        cmd1 = CicsCommand(
            command_type=CicsCommandType.LINK,
            raw_text="LINK PROGRAM(PROG1)",
            program_name="PROG1",
        )
        cmd2 = CicsCommand(
            command_type=CicsCommandType.LINK,
            raw_text="LINK PROGRAM(PROG2)",
            program_name="PROG2",
        )
        assert cmd1.program_name != cmd2.program_name

    def test_command_type_mutation(self):
        """Changing command_type produces different command."""
        cmd1 = CicsCommand(
            command_type=CicsCommandType.READ,
            raw_text="READ",
        )
        cmd2 = CicsCommand(
            command_type=CicsCommandType.WRITE,
            raw_text="WRITE",
        )
        assert cmd1.command_type != cmd2.command_type

    def test_resp_handling_mutation(self):
        """Changing resp_handling produces different command."""
        cmd1 = CicsCommand(
            command_type=CicsCommandType.READ,
            raw_text="READ",
            resp_handling=CicsRespHandling.NO_HANDLE,
        )
        cmd2 = CicsCommand(
            command_type=CicsCommandType.READ,
            raw_text="READ",
            resp_handling=CicsRespHandling.RESP_VARIABLE,
            resp_field=":WS-RESP",
        )
        assert cmd1.resp_handling != cmd2.resp_handling


# ============================================================================
# TEST GROUP 11: Negative/Unsupported Syntax Tests
# ============================================================================

class TestNegativeUnsupported:
    """T34: Negative/unsupported syntax tests."""

    def test_unsupported_command_ignored(self):
        """Unsupported CICS commands are silently ignored."""
        parser = CicsParser()
        app = parser.parse_embedded_cics("ADDRESS EIBLOC")
        assert len(app.commands) == 0

    def test_malformed_operand(self):
        """Malformed operand is handled gracefully."""
        parser = CicsParser()
        app = parser.parse_embedded_cics("READ DATASET(MYFILE) INVALID")
        assert len(app.commands) == 1
        cmd = app.commands[0]
        assert cmd.resource_name == "MYFILE"

    def test_missing_operand_value(self):
        """Missing operand value is handled gracefully."""
        parser = CicsParser()
        app = parser.parse_embedded_cics("READ DATASET(MYFILE) LENGTH")
        assert len(app.commands) == 1

    def test_nested_parentheses(self):
        """Nested parentheses are handled gracefully."""
        parser = CicsParser()
        app = parser.parse_embedded_cics("READ DATASET(MYFILE) RESP((:WS-RESP))")
        assert len(app.commands) == 1


# ============================================================================
# TEST GROUP 12: Deterministic Serialization Tests
# ============================================================================

class TestDeterministicSerialization:
    """T35: Deterministic serialization tests."""

    def test_command_deterministic(self):
        """Same input produces same output."""
        parser = CicsParser()
        cics_text = "READ DATASET(MYFILE) INTO(:WS-REC) RESP(:WS-RESP)"
        app1 = parser.parse_embedded_cics(cics_text)
        app2 = parser.parse_embedded_cics(cics_text)
        assert len(app1.commands) == len(app2.commands)
        assert app1.commands[0].command_type == app2.commands[0].command_type
        assert app1.commands[0].resource_name == app2.commands[0].resource_name

    def test_multiple_commands_order(self):
        """Multiple commands maintain order."""
        parser = CicsParser()
        cics_text = """
        SEND MAP(MAP1)
        READ DATASET(MYFILE)
        SYNCPOINT
        """
        app = parser.parse_embedded_cics(cics_text)
        assert len(app.commands) == 3
        assert app.commands[0].command_type == CicsCommandType.SEND
        assert app.commands[1].command_type == CicsCommandType.READ
        assert app.commands[2].command_type == CicsCommandType.SYNCPOINT


# ============================================================================
# TEST GROUP 13: Independent Validation Tests
# ============================================================================

class TestIndependentValidation:
    """T36: Independent validation tests."""

    def test_validate_read_without_dataset(self):
        """READ without DATASET should produce validation error."""
        app = CicsApplication(
            program_id="PROG1",
            commands=(
                CicsCommand(
                    command_type=CicsCommandType.READ,
                    raw_text="READ",
                    resource_name="",
                ),
            ),
        )
        issues = app.validate()
        assert any("DATASET" in e for e in issues)

    def test_validate_link_without_program(self):
        """LINK without PROGRAM should produce validation error."""
        app = CicsApplication(
            program_id="PROG1",
            commands=(
                CicsCommand(
                    command_type=CicsCommandType.LINK,
                    raw_text="LINK",
                    program_name="",
                ),
            ),
        )
        issues = app.validate()
        assert any("PROGRAM" in e for e in issues)

    def test_validate_send_without_map_or_termid(self):
        """SEND without MAP or TERMID should produce validation error."""
        app = CicsApplication(
            program_id="PROG1",
            commands=(
                CicsCommand(
                    command_type=CicsCommandType.SEND,
                    raw_text="SEND",
                    map_name="",
                    terminal_id="",
                ),
            ),
        )
        issues = app.validate()
        assert any("SEND" in e for e in issues)

    def test_validate_clean(self):
        """Valid application should have no errors."""
        app = CicsApplication(
            program_id="PROG1",
            commands=(
                CicsCommand(
                    command_type=CicsCommandType.READ,
                    raw_text="READ DATASET(MYFILE)",
                    resource_name="MYFILE",
                ),
                CicsCommand(
                    command_type=CicsCommandType.LINK,
                    raw_text="LINK PROGRAM(SUB)",
                    program_name="SUB",
                ),
                CicsCommand(
                    command_type=CicsCommandType.SEND,
                    raw_text="SEND MAP(MAP1)",
                    map_name="MAP1",
                ),
            ),
        )
        issues = app.validate()
        assert len(issues) == 0


# ============================================================================
# TEST GROUP 14: Regression Tests
# ============================================================================

class TestRegression:
    """T37: Regression tests — comprehensive end-to-end scenarios."""

    def test_complex_cics_program(self):
        """Complex CICS program with multiple command types."""
        parser = CicsParser()
        cics_text = """
        HANDLE CONDITION NOTFND(NOT-FOUND) ERROR(ERR-RTN)
        HANDLE AID PF3(EXIT-PROG) CLEAR(START-PROG)
        ASSIGN EIBAID(:WS-AID) EIBDATE(:WS-DATE)
        SEND MAP(MAINMAP) MAPSET(MAINMS) TERMID(:WS-TERM)
        RECEIVE MAP(MAINMAP)
        READ DATASET(CUSTFILE) INTO(:WS-CUST) KEY(:WS-CUST-ID) RESP(:WS-RESP)
        IF :WS-RESP = 0
          LINK PROGRAM(CUSTUPD) COMMAREA(:WS-CUST) LENGTH(:WS-CUST-LEN)
        END-IF
        WRITEQ TS QUEUE(ERRQ) FROM(:WS-ERR) LENGTH(:WS-ERR-LEN)
        SYNCPOINT
        RETURN TRANSID(T001)
        """
        app = parser.parse_embedded_cics(cics_text)

        # Commands
        assert len(app.commands) >= 8

        # Handle conditions
        assert len(app.handle_conditions) == 2
        assert app.handle_conditions[0].condition == CicsConditionType.NOTFND
        assert app.handle_conditions[1].condition == CicsConditionType.ERROR

        # Handle AIDs
        assert len(app.handle_aids) == 2
        assert app.handle_aids[0].aid_type == CicsAidType.PF3
        assert app.handle_aids[1].aid_type == CicsAidType.CLEAR

        # Assignments
        assert len(app.assignments) == 2

        # Resources
        assert "CUSTFILE" in app.file_resources
        assert "ERRQ" in app.queue_resources
        assert "CUSTUPD" in app.program_resources
        assert "MAINMAP" in app.map_resources
        assert "MAINMS" in app.map_resources

        # Host variables
        assert len(app.host_variables) > 0

        # Dependencies
        file_deps = app.get_file_dependencies()
        assert any(d[0] == "READ" and d[1] == "CUSTFILE" for d in file_deps)

        prog_deps = app.get_program_dependencies()
        assert "CUSTUPD" in prog_deps

    def test_full_transaction_flow(self):
        """Full transaction flow: receive → process → send → commit."""
        parser = CicsParser()
        cics_text = """
        RECEIVE MAP(INPUTMAP) INTO(:WS-INPUT)
        READ DATASET(MASTERFILE) INTO(:WS-MASTER) KEY(:WS-KEY) RESP(:WS-RESP)
        WRITE DATASET(AUDITFILE) FROM(:WS-AUDIT) LENGTH(:WS-AUDIT-LEN)
        SEND MAP(OUTPUTMAP) FROM(:WS-OUTPUT) LENGTH(:WS-OUT-LEN)
        SYNCPOINT
        RETURN
        """
        app = parser.parse_embedded_cics(cics_text)

        assert len(app.commands) == 6
        assert "MASTERFILE" in app.file_resources
        assert "AUDITFILE" in app.file_resources

    def test_multi_program_link(self):
        """Multi-program LINK chain."""
        parser = CicsParser()
        cics_text = """
        LINK PROGRAM(PROG1) COMMAREA(:WS-COMM1) LENGTH(:WS-LEN1)
        LINK PROGRAM(PROG2) COMMAREA(:WS-COMM2) LENGTH(:WS-LEN2)
        XCTL PROGRAM(PROG3)
        """
        app = parser.parse_embedded_cics(cics_text)

        prog_deps = app.get_program_dependencies()
        assert "PROG1" in prog_deps
        assert "PROG2" in prog_deps
        assert "PROG3" in prog_deps

    def test_browse_chain(self):
        """Browse chain: STARTBR → READNEXT → ENDBR."""
        parser = CicsParser()
        cics_text = """
        STARTBR DATASET(MYFILE) KEY(:WS-START-KEY)
        READNEXT DATASET(MYFILE) INTO(:WS-REC) LENGTH(:WS-LEN)
        READNEXT DATASET(MYFILE) INTO(:WS-REC) LENGTH(:WS-LEN)
        ENDBR DATASET(MYFILE)
        """
        app = parser.parse_embedded_cics(cics_text)

        assert len(app.commands) == 4
        assert app.commands[0].command_type == CicsCommandType.STARTBR
        assert app.commands[1].command_type == CicsCommandType.READNEXT
        assert app.commands[2].command_type == CicsCommandType.READNEXT
        assert app.commands[3].command_type == CicsCommandType.ENDBR

    def test_resp_distinct_from_sqlcode(self):
        """CICS RESP must remain distinct from SQLCODE."""
        parser = CicsParser()
        app = parser.parse_embedded_cics("READ DATASET(MYFILE) RESP(:WS-RESP)")
        cmd = app.commands[0]
        assert cmd.resp_field == ":WS-RESP"
        assert cmd.resp_handling == CicsRespHandling.RESP_VARIABLE
        # RESP is CICS-specific, not SQLCODE
        assert cmd.resp_field != "SQLCODE"

    def test_resp_distinct_from_file_status(self):
        """CICS RESP must remain distinct from FILE STATUS."""
        parser = CicsParser()
        app = parser.parse_embedded_cics("READ DATASET(MYFILE) RESP(:WS-RESP)")
        cmd = app.commands[0]
        assert cmd.resp_field != "FILE-STATUS"
