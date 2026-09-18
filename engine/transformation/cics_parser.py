"""CICS parser for embedded CICS / transaction semantic extraction.

Parses embedded CICS statements within COBOL EXEC CICS ... END-EXEC blocks.
Extracts semantic CICS IR for:
- Terminal I/O (SEND, RECEIVE)
- File I/O (READ, WRITE, REWRITE, DELETE, STARTBR, READNEXT, READPREV, ENDBR)
- Program control (LINK, XCTL, RETURN)
- Transaction control (SYNCPOINT, ABEND)
- Condition handling (HANDLE CONDITION, HANDLE AID)
- Variable assignment (ASSIGN)
- COMMAREA and channel/container references
- Resource dependencies (files, queues, programs, maps, terminals)
- RESP/RESP2 handling

This is NOT a complete CICS parser. It handles only the supported subset
for semantic extraction.
"""

from __future__ import annotations

import re

from engine.transformation.ir import (
    CicsAidType,
    CicsApplication,
    CicsAssignment,
    CicsCommand,
    CicsCommandType,
    CicsConditionType,
    CicsHandleAid,
    CicsHandleCondition,
    CicsOperand,
    CicsResourceType,
    CicsRespHandling,
)
_COMMAND_MAP: dict[str, CicsCommandType] = {
    "SEND": CicsCommandType.SEND,
    "RECEIVE": CicsCommandType.RECEIVE,
    "READ": CicsCommandType.READ,
    "WRITE": CicsCommandType.WRITE,
    "REWRITE": CicsCommandType.REWRITE,
    "DELETE": CicsCommandType.DELETE,
    "STARTBR": CicsCommandType.STARTBR,
    "READNEXT": CicsCommandType.READNEXT,
    "READPREV": CicsCommandType.READPREV,
    "ENDBR": CicsCommandType.ENDBR,
    "LINK": CicsCommandType.LINK,
    "XCTL": CicsCommandType.XCTL,
    "RETURN": CicsCommandType.RETURN,
    "SYNCPOINT": CicsCommandType.SYNCPOINT,
    "ABEND": CicsCommandType.ABEND,
    "HANDLE": CicsCommandType.HANDLE_CONDITION,
    "ASSIGN": CicsCommandType.ASSIGN,
    "ALLOCATE": CicsCommandType.ALLOCATE,
    "FREE": CicsCommandType.FREE,
    "HOLD": CicsCommandType.HOLD,
    "RELEASE": CicsCommandType.RELEASE,
    "WRITEQ": CicsCommandType.WRITEQ,
    "READQ": CicsCommandType.READQ,
    "DELETEQ": CicsCommandType.DELETEQ,
    "SET": CicsCommandType.SET,
    "IGNORE": CicsCommandType.IGNORE,
    "POP": CicsCommandType.POP,
    "PUSH": CicsCommandType.PUSH,
}

# Maps condition name to CicsConditionType
_CONDITION_MAP: dict[str, CicsConditionType] = {
    "NORMAL": CicsConditionType.NORMAL,
    "ERROR": CicsConditionType.ERROR,
    "NOTFND": CicsConditionType.NOTFND,
    "DUPKEY": CicsConditionType.DUPKEY,
    "INVREQ": CicsConditionType.INVREQ,
    "IOERR": CicsConditionType.IOERR,
    "NOSPACE": CicsConditionType.NOSPACE,
    "NOTOPEN": CicsConditionType.NOTOPEN,
    "ENDDATA": CicsConditionType.ENDDATA,
    "ITEMERR": CicsConditionType.ITEMERR,
    "LENGERR": CicsConditionType.LENGERR,
    "QIDERR": CicsConditionType.QIDERR,
    "MAPFAIL": CicsConditionType.MAPFAIL,
    "ISSUEERR": CicsConditionType.ISSUEERR,
    "OVERFLOW": CicsConditionType.OVERFLOW,
    "INBFMH": CicsConditionType.INBFMH,
    "TERMERR": CicsConditionType.TERMERR,
    "RLINEMGR": CicsConditionType.RLINEMGR,
    "UCERR": CicsConditionType.UCERR,
    "TRANSIDERR": CicsConditionType.TRANSIDERR,
    "ENDAID": CicsConditionType.ENDAID,
    "KEYERR": CicsConditionType.KEYERR,
    "NOSTART": CicsConditionType.NOSTART,
    "NONVAL": CicsConditionType.NONVAL,
}

# Maps AID name to CicsAidType
_AID_MAP: dict[str, CicsAidType] = {
    "CLEAR": CicsAidType.CLEAR,
    "PA1": CicsAidType.PA1,
    "PA2": CicsAidType.PA2,
    "PA3": CicsAidType.PA3,
    "PF1": CicsAidType.PF1,
    "PF2": CicsAidType.PF2,
    "PF3": CicsAidType.PF3,
    "PF4": CicsAidType.PF4,
    "PF5": CicsAidType.PF5,
    "PF6": CicsAidType.PF6,
    "PF7": CicsAidType.PF7,
    "PF8": CicsAidType.PF8,
    "PF9": CicsAidType.PF9,
    "PF10": CicsAidType.PF10,
    "PF11": CicsAidType.PF11,
    "PF12": CicsAidType.PF12,
    "PF13": CicsAidType.PF13,
    "PF14": CicsAidType.PF14,
    "PF15": CicsAidType.PF15,
    "PF16": CicsAidType.PF16,
    "PF17": CicsAidType.PF17,
    "PF18": CicsAidType.PF18,
    "PF19": CicsAidType.PF19,
    "PF20": CicsAidType.PF20,
    "PF21": CicsAidType.PF21,
    "PF22": CicsAidType.PF22,
    "PF23": CicsAidType.PF23,
    "PF24": CicsAidType.PF24,
    "ENTER": CicsAidType.ENTER,
    "TAB": CicsAidType.TAB,
    "BOTHRONE": CicsAidType.BOTHRONE,
    "TRIGGER": CicsAidType.TRIGGER,
}

# Resource keywords: which operand keyword maps to which resource type
_RESOURCE_KEYWORDS: dict[str, CicsResourceType] = {
    "DATASET": CicsResourceType.FILE,
    "FILE": CicsResourceType.FILE,
    "QUEUE": CicsResourceType.QUEUE,
    "QNAME": CicsResourceType.QUEUE,
    "PROGRAM": CicsResourceType.PROGRAM,
    "TRANSID": CicsResourceType.TRANSID,
    "MAP": CicsResourceType.MAP,
    "MAPSET": CicsResourceType.MAPSET,
    "TERMID": CicsResourceType.TRANSID,
}


class CicsParser:
    """Parse embedded CICS statements into CICS IR.

    Usage:
        parser = CicsParser()
        block = parser.parse_embedded_cics(cics_text)
    """

    def parse_embedded_cics(self, cics_text: str) -> CicsApplication:
        """Parse an embedded CICS block (between EXEC CICS and END-EXEC).

        Args:
            cics_text: the CICS text (without EXEC CICS/END-EXEC markers)

        Returns:
            CicsApplication with parsed commands
        """
        commands: list[CicsCommand] = []
        handle_conditions: list[CicsHandleCondition] = []
        handle_aids: list[CicsHandleAid] = []
        assignments: list[CicsAssignment] = []
        all_host_vars: list[str] = []

        # Split into individual CICS commands
        stmts = self._split_statements(cics_text)

        for stmt_text in stmts:
            stmt_text = stmt_text.strip()
            if not stmt_text:
                continue

            upper = stmt_text.upper()

            # Determine command type
            command_type = self._identify_command(upper)
            if command_type is None:
                # Unknown command — store raw
                continue

            # Parse operands
            operands = self._parse_operands(stmt_text)

            # Validate: READ/WRITE/REWRITE/DELETE/STARTBR/READNEXT/READPREV/ENDBR
            # require DATASET or FILE operand
            if command_type in (
                CicsCommandType.READ, CicsCommandType.WRITE,
                CicsCommandType.REWRITE, CicsCommandType.DELETE,
                CicsCommandType.STARTBR, CicsCommandType.READNEXT,
                CicsCommandType.READPREV, CicsCommandType.ENDBR,
            ):
                has_dataset = any(
                    op.keyword in ("DATASET", "FILE") for op in operands
                )
                if not has_dataset:
                    continue

            # Build CicsCommand
            cmd = self._build_command(command_type, stmt_text, operands)
            commands.append(cmd)

            # Extract special handling
            if command_type == CicsCommandType.HANDLE_CONDITION:
                hcs = self._parse_handle_conditions(stmt_text)
                handle_conditions.extend(hcs)

            elif command_type == CicsCommandType.HANDLE_AID:
                has = self._parse_handle_aids(stmt_text)
                handle_aids.extend(has)

            elif command_type == CicsCommandType.ASSIGN:
                asgns = self._parse_assignments(stmt_text)
                assignments.extend(asgns)

            # Collect host variables
            for op in operands:
                if op.is_host_variable:
                    var_name = op.value.lstrip(":")
                    if var_name not in all_host_vars:
                        all_host_vars.append(var_name)

        # Extract resource dependencies
        file_resources = self._extract_file_resources(commands)
        queue_resources = self._extract_queue_resources(commands)
        program_resources = self._extract_program_resources(commands)
        map_resources = self._extract_map_resources(commands)
        terminal_resources = self._extract_terminal_resources(commands)

        return CicsApplication(
            program_id="",  # caller must set
            commands=tuple(commands),
            handle_conditions=tuple(handle_conditions),
            handle_aids=tuple(handle_aids),
            assignments=tuple(assignments),
            file_resources=tuple(file_resources),
            queue_resources=tuple(queue_resources),
            program_resources=tuple(program_resources),
            map_resources=tuple(map_resources),
            terminal_resources=tuple(terminal_resources),
            host_variables=tuple(all_host_vars),
            raw_text=cics_text,
        )

    def _split_statements(self, cics_text: str) -> list[str]:
        """Split CICS text into individual statements.

        CICS commands are separated by periods or newlines.
        Handles parenthesized expressions (e.g., RESP=(...)).
        """
        stmts: list[str] = []
        current: list[str] = []
        paren_depth = 0
        in_quote = False
        quote_char = ""

        for ch in cics_text:
            if in_quote:
                current.append(ch)
                if ch == quote_char:
                    in_quote = False
                continue

            if ch in ("'", '"'):
                in_quote = True
                quote_char = ch
                current.append(ch)
            elif ch == "(":
                paren_depth += 1
                current.append(ch)
            elif ch == ")":
                paren_depth = max(0, paren_depth - 1)
                current.append(ch)
            elif ch == "." and paren_depth == 0:
                stmts.append("".join(current))
                current = []
            elif ch == "\n" and paren_depth == 0:
                # Newline at top level — treat as statement separator
                text = "".join(current).strip()
                if text:
                    stmts.append(text)
                current = []
            else:
                current.append(ch)

        # Last statement (may not end with . or newline)
        text = "".join(current).strip()
        if text:
            stmts.append(text)

        return stmts

    def _identify_command(self, upper: str) -> CicsCommandType | None:
        """Identify the CICS command type from the statement text."""
        # Strip leading whitespace
        upper = upper.strip()

        # Special handling for HANDLE (HANDLE CONDITION / HANDLE AID)
        if upper.startswith("HANDLE"):
            if "CONDITION" in upper:
                return CicsCommandType.HANDLE_CONDITION
            elif "AID" in upper:
                return CicsCommandType.HANDLE_AID
            return None

        # Special handling for queue commands (WRITEQ, READQ, DELETEQ)
        for prefix in ("WRITEQ", "READQ", "DELETEQ"):
            if upper.startswith(prefix):
                return _COMMAND_MAP.get(prefix)

        # Standard commands
        for cmd_name, cmd_type in _COMMAND_MAP.items():
            if upper.startswith(cmd_name):
                # Ensure it's a whole word match
                if len(upper) == len(cmd_name) or upper[len(cmd_name)] in (" ", "(", "\n", "\r"):
                    return cmd_type

        return None

    def _parse_operands(self, text: str) -> tuple[CicsOperand, ...]:
        """Parse CICS command operands.

        CICS operands can be:
        - KEY=VALUE pairs
        - KEY(VALUE) pairs
        - Bare keywords
        Operands are space-separated.
        Handles parenthesized expressions and quoted strings.
        """
        operands: list[CicsOperand] = []

        # Find the command name end
        cmd_end = 0
        for i, ch in enumerate(text):
            if ch in (" ", "(", "\n", "\r"):
                cmd_end = i
                break
        else:
            cmd_end = len(text)

        operand_text = text[cmd_end:].strip()

        # Split operands by space, respecting parentheses
        parts = self._split_by_space(operand_text)

        for part in parts:
            part = part.strip()
            if not part:
                continue

            # Check for KEY=VALUE
            eq_match = re.match(r"([A-Z][A-Z0-9_-]*)=(.*)", part, re.IGNORECASE)
            if eq_match:
                keyword = eq_match.group(1).upper()
                value = eq_match.group(2).strip()

                is_host = value.startswith(":")
                is_literal = (value.startswith("'") and value.endswith("'")) or \
                             (value.startswith('"') and value.endswith('"'))

                operands.append(CicsOperand(
                    keyword=keyword,
                    value=value,
                    is_host_variable=is_host,
                    is_literal=is_literal,
                ))
                continue

            # Check for KEY(VALUE) — CICS syntax
            kv_match = re.match(r"([A-Z][A-Z0-9_-]*)\(([^)]*)\)", part, re.IGNORECASE)
            if kv_match:
                keyword = kv_match.group(1).upper()
                value = kv_match.group(2).strip()

                is_host = value.startswith(":")
                is_literal = (value.startswith("'") and value.endswith("'")) or \
                             (value.startswith('"') and value.endswith('"'))

                operands.append(CicsOperand(
                    keyword=keyword,
                    value=value,
                    is_host_variable=is_host,
                    is_literal=is_literal,
                ))
                continue

            # Bare keyword
            keyword = part.upper()
            operands.append(CicsOperand(
                keyword=keyword,
                value="",
            ))

        return tuple(operands)

    def _split_by_space(self, text: str) -> list[str]:
        """Split text by spaces, respecting parentheses and quotes."""
        parts: list[str] = []
        current: list[str] = []
        paren_depth = 0
        in_quote = False
        quote_char = ""

        for ch in text:
            if in_quote:
                current.append(ch)
                if ch == quote_char:
                    in_quote = False
                continue

            if ch in ("'", '"'):
                in_quote = True
                quote_char = ch
                current.append(ch)
            elif ch == "(":
                paren_depth += 1
                current.append(ch)
            elif ch == ")":
                paren_depth = max(0, paren_depth - 1)
                current.append(ch)
            elif ch in (" ", "\t", "\n", "\r") and paren_depth == 0:
                if current:
                    parts.append("".join(current))
                    current = []
            else:
                current.append(ch)

        if current:
            parts.append("".join(current))

        return parts

    def _split_by_comma(self, text: str) -> list[str]:
        """Split text by commas, respecting parentheses and quotes."""
        parts: list[str] = []
        current: list[str] = []
        paren_depth = 0
        in_quote = False
        quote_char = ""

        for ch in text:
            if in_quote:
                current.append(ch)
                if ch == quote_char:
                    in_quote = False
                continue

            if ch in ("'", '"'):
                in_quote = True
                quote_char = ch
                current.append(ch)
            elif ch == "(":
                paren_depth += 1
                current.append(ch)
            elif ch == ")":
                paren_depth = max(0, paren_depth - 1)
                current.append(ch)
            elif ch == "," and paren_depth == 0:
                parts.append("".join(current))
                current = []
            else:
                current.append(ch)

        if current:
            parts.append("".join(current))

        return parts

    def _build_command(
        self,
        command_type: CicsCommandType,
        raw_text: str,
        operands: tuple[CicsOperand, ...],
    ) -> CicsCommand:
        """Build a CicsCommand with extracted references."""
        resource_name = ""
        resource_type = None
        program_name = ""
        transaction_id = ""
        into_field = ""
        from_field = ""
        set_field = ""
        length_field = ""
        key_field = ""
        resp_field = ""
        resp2_field = ""
        commarea_length = ""
        commarea_data = ""
        channel_name = ""
        container_names: list[str] = []
        map_name = ""
        mapset_name = ""
        terminal_id = ""
        rid_field = ""
        resp_handling = CicsRespHandling.NO_HANDLE

        for op in operands:
            kw = op.keyword
            val = op.value

            if kw == "DATASET" or kw == "FILE":
                resource_name = val
                resource_type = CicsResourceType.FILE
            elif kw == "QUEUE" or kw == "QNAME":
                resource_name = val
                resource_type = CicsResourceType.QUEUE
            elif kw == "PROGRAM":
                program_name = val
                if not resource_type:
                    resource_type = CicsResourceType.PROGRAM
            elif kw == "TRANSID":
                transaction_id = val
                resource_name = val
                resource_type = CicsResourceType.TRANSID
            elif kw == "INTO":
                into_field = val
            elif kw == "FROM":
                from_field = val
            elif kw == "SET":
                set_field = val
            elif kw == "LENGTH":
                length_field = val
            elif kw == "KEY" or kw == "RIDFLD":
                key_field = val
                rid_field = val
            elif kw == "RESP":
                resp_field = val
                resp_handling = CicsRespHandling.RESP_VARIABLE
            elif kw == "RESP2":
                resp2_field = val
                resp_handling = CicsRespHandling.RESP2_VARIABLE
            elif kw == "MAP":
                map_name = val
                resource_name = val
                resource_type = CicsResourceType.MAP
            elif kw == "MAPSET":
                mapset_name = val
                resource_name = val
                resource_type = CicsResourceType.MAPSET
            elif kw == "TERMID":
                terminal_id = val
                resource_name = val
                resource_type = CicsResourceType.TRANSID
            elif kw == "CHANNEL":
                channel_name = val
            elif kw == "CONTAINER":
                container_names.append(val)

        # Extract COMMAREA info
        if command_type in (CicsCommandType.LINK, CicsCommandType.XCTL, CicsCommandType.RETURN):
            for op in operands:
                if op.keyword == "COMMAREA":
                    commarea_data = op.value
                    # Look for LENGTH after COMMAREA
                    for op2 in operands:
                        if op2.keyword == "LENGTH":
                            commarea_length = op2.value
                            break

        return CicsCommand(
            command_type=command_type,
            raw_text=raw_text,
            operands=operands,
            resource_name=resource_name,
            resource_type=resource_type,
            commarea_length=commarea_length,
            commarea_data=commarea_data,
            channel_name=channel_name,
            container_names=tuple(container_names),
            program_name=program_name,
            transaction_id=transaction_id,
            into_field=into_field,
            from_field=from_field,
            set_field=set_field,
            length_field=length_field,
            key_field=key_field,
            resp_field=resp_field,
            resp2_field=resp2_field,
            resp_handling=resp_handling,
            map_name=map_name,
            mapset_name=mapset_name,
            terminal_id=terminal_id,
            rid_field=rid_field,
        )

    def _parse_handle_conditions(self, text: str) -> list[CicsHandleCondition]:
        """Parse HANDLE CONDITION conditions. Handles multiple conditions on one line."""
        conditions: list[CicsHandleCondition] = []
        upper = text.upper()

        # Find all condition paragraphs: CONDITION_NAME(PARA)
        # Pattern: word followed by (word)
        for match in re.finditer(r"([A-Z][A-Z0-9]*)\(([A-Z][A-Z0-9-]*)\)", upper):
            cond_name = match.group(1)
            paragraph = match.group(2)

            # Skip non-condition words like "CONDITION", "HANDLE"
            if cond_name in ("CONDITION", "HANDLE"):
                continue

            condition = _CONDITION_MAP.get(cond_name)
            if condition is not None:
                conditions.append(CicsHandleCondition(
                    condition=condition,
                    paragraph=paragraph,
                ))

        return conditions

    def _parse_handle_aids(self, text: str) -> list[CicsHandleAid]:
        """Parse HANDLE AID keys. Handles multiple AIDs on one line."""
        aids: list[CicsHandleAid] = []
        upper = text.upper()

        # Find all AID paragraphs: AID_NAME(PARA)
        for match in re.finditer(r"([A-Z][A-Z0-9]*)\(([A-Z][A-Z0-9-]*)\)", upper):
            aid_name = match.group(1)
            paragraph = match.group(2)

            # Skip non-AID words like "AID", "HANDLE"
            if aid_name in ("AID", "HANDLE"):
                continue

            aid_type = _AID_MAP.get(aid_name)
            if aid_type is not None:
                aids.append(CicsHandleAid(
                    aid_type=aid_type,
                    paragraph=paragraph,
                ))

        return aids

    def _parse_assignments(self, text: str) -> list[CicsAssignment]:
        """Parse ASSIGN statements. Handles multiple field(variable) pairs on one line."""
        assignments: list[CicsAssignment] = []
        upper = text.upper()

        # Find all FIELD(VARIABLE) patterns
        for match in re.finditer(r"([A-Z][A-Z0-9_-]*)\(\s*:?\s*([A-Z][A-Z0-9-]*)\s*\)", upper):
            field = match.group(1)
            variable = match.group(2)
            assignments.append(CicsAssignment(
                field=field,
                variable=variable,
            ))

        # Also try FIELD=VARIABLE patterns
        for match in re.finditer(r"([A-Z][A-Z0-9_-]*)\s*=\s*:?\s*([A-Z][A-Z0-9-]*)", upper):
            field = match.group(1)
            variable = match.group(2)
            # Avoid duplicating FIELD(VARIABLE) results
            if not any(a.field == field for a in assignments):
                assignments.append(CicsAssignment(
                    field=field,
                    variable=variable,
                ))

        return assignments

    def _extract_file_resources(self, commands: list[CicsCommand]) -> list[str]:
        """Extract unique file (DATASET) resource names."""
        resources: list[str] = []
        for cmd in commands:
            if cmd.resource_type == CicsResourceType.FILE and cmd.resource_name:
                if cmd.resource_name not in resources:
                    resources.append(cmd.resource_name)
        return resources

    def _extract_queue_resources(self, commands: list[CicsCommand]) -> list[str]:
        """Extract unique queue resource names."""
        resources: list[str] = []
        for cmd in commands:
            if cmd.resource_type == CicsResourceType.QUEUE and cmd.resource_name:
                if cmd.resource_name not in resources:
                    resources.append(cmd.resource_name)
        return resources

    def _extract_program_resources(self, commands: list[CicsCommand]) -> list[str]:
        """Extract unique program resource names (from LINK/XCTL)."""
        resources: list[str] = []
        for cmd in commands:
            if cmd.command_type in (CicsCommandType.LINK, CicsCommandType.XCTL):
                if cmd.program_name and cmd.program_name not in resources:
                    resources.append(cmd.program_name)
        return resources

    def _extract_map_resources(self, commands: list[CicsCommand]) -> list[str]:
        """Extract unique MAP/MAPSET resource names."""
        resources: list[str] = []
        for cmd in commands:
            if cmd.map_name and cmd.map_name not in resources:
                resources.append(cmd.map_name)
            if cmd.mapset_name and cmd.mapset_name not in resources:
                resources.append(cmd.mapset_name)
        return resources

    def _extract_terminal_resources(self, commands: list[CicsCommand]) -> list[str]:
        """Extract unique TERMID values."""
        resources: list[str] = []
        for cmd in commands:
            if cmd.terminal_id and cmd.terminal_id not in resources:
                resources.append(cmd.terminal_id)
        return resources
