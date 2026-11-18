"""Subsystem interfaces inside COBOL source: ``EXEC SQL``, ``EXEC CICS``, ``EXEC DLI``, IMS and MQ calls, runtime calls.

Every function here works on tokens that already carry their source position, and records what is *named*: it never
guesses a table, queue or program it cannot see.  A name held in a variable becomes a dynamic reference (followed
through ``VALUE``/``MOVE`` by the caller), never a silent omission.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .cobol_text import Token
from .findings import detail

if TYPE_CHECKING:  # pragma: no cover
    from .scan_cobol import _State

IMS_ENTRIES = frozenset({"CBLTDLI", "AIBTDLI", "ASMTDLI", "PLITDLI", "CEETDLI"})
MQ_CALLS = frozenset({
    "MQCONN", "MQCONNX", "MQDISC", "MQOPEN", "MQCLOSE", "MQGET", "MQPUT", "MQPUT1", "MQINQ", "MQSET", "MQBEGIN",
    "MQCMIT", "MQBACK", "MQSUB", "MQSUBRQ", "MQCRTMH", "MQDLTMH", "MQCB", "MQCTL", "MQSTAT",
})
DB2_RUNTIME = frozenset({"DSNTIAR", "DSNTIAC", "DSNALI", "DSNHLI", "DSNULI", "DSNRLI", "DSNCLI", "DSNTIAD"})
SQL_TABLE_STOP = frozenset({
    "WHERE", "GROUP", "ORDER", "HAVING", "UNION", "FETCH", "FOR", "WITH", "INNER", "LEFT", "RIGHT", "FULL", "CROSS",
    "JOIN", "ON", "SET", "INTO", "USING", "OPTIMIZE", "VALUES", "SELECT", "AND", "OR", "EXCEPT", "INTERSECT", "WHEN",
    "ISOLATION", "SKIP", "QUERYNO", "FROM", "NATURAL", "LATERAL", "OUTER",
})
SQL_OPERATIONS = frozenset({
    "SELECT", "INSERT", "UPDATE", "DELETE", "MERGE", "OPEN", "FETCH", "CLOSE", "COMMIT", "ROLLBACK", "CALL", "PREPARE",
    "EXECUTE", "DECLARE", "SET", "WHENEVER", "CONNECT", "LOCK", "SAVEPOINT", "RELEASE", "GRANT", "REVOKE", "CREATE",
    "DROP", "ALTER", "DESCRIBE", "TRUNCATE", "VALUES", "BEGIN", "END", "INCLUDE", "ALLOCATE", "ASSOCIATE", "COMMENT",
})
SQL_INCLUDE_BUILTIN = frozenset({"SQLCA", "SQLDA"})

#: Operation the statement performs **on the table** it names, for ``mode`` on an ``accesses-table`` edge.  An
#: operation that does not touch rows (``PREPARE``, ``DECLARE TABLE``, ``COMMIT``) carries no mode rather than a
#: guessed one.
SQL_ACCESS_MODES: dict[str, str] = {
    "SELECT": "read", "FETCH": "read", "OPEN": "read",
    "INSERT": "write", "UPDATE": "write", "DELETE": "write", "MERGE": "read-write",
    "CREATE": "create", "DROP": "delete", "TRUNCATE": "delete", "ALTER": "update", "LOCK": "update",
}

#: Operation performed **on the MQ interface** by each MQ call.
MQ_ACCESS_MODES: dict[str, str] = {
    "MQPUT": "put", "MQPUT1": "put", "MQGET": "get", "MQOPEN": "allocate", "MQCLOSE": "delete",
    "MQINQ": "read", "MQSET": "write", "MQSUB": "route", "MQSUBRQ": "route",
}

#: Operation performed **on the IMS resource** by a DLI verb.
DLI_ACCESS_MODES: dict[str, str] = {
    "GU": "read", "GN": "read", "GHN": "read", "GNP": "read", "GHID": "read", "GHCU": "read",
    "ISRT": "create", "REPL": "update", "DLET": "delete",
}

#: Operation performed **on a CICS file** by a file command.
CICS_FILE_MODES: dict[str, str] = {
    "READ": "read", "READNEXT": "read", "READPREV": "read", "STARTBR": "search",
    "WRITE": "write", "REWRITE": "update", "DELETE": "delete",
}

CICS_PROGRAM_COMMANDS = {"LINK": "cics-link", "XCTL": "cics-xctl", "LOAD": "cics-load", "INVOKE": "cics-link"}
CICS_FILE_COMMANDS = frozenset({
    "READ", "WRITE", "REWRITE", "DELETE", "UNLOCK", "STARTBR", "READNEXT", "READPREV", "ENDBR", "RESETBR",
})
_CICS_SUBCOMMANDS = {
    "READQ": ("TS", "TD"), "WRITEQ": ("TS", "TD"), "DELETEQ": ("TS", "TD"),
    "HANDLE": ("CONDITION", "ABEND", "AID"), "IGNORE": ("CONDITION",), "PUSH": ("HANDLE",), "POP": ("HANDLE",),
    "SEND": ("MAP", "TEXT", "CONTROL", "PAGE", "LAST"), "RECEIVE": ("MAP", "PARTN"), "CONVERSE": ("DEFAULT",),
}


def classify_call(state: "_State", target: Token, name: str, args: list[str], verb: str) -> bool:
    """Record a call to an IMS/MQ/DB2/LE/runtime entry point; True when it was one (so it is not a program edge)."""
    if verb != "CALL":
        return False
    if name in IMS_ENTRIES:
        function = args[0] if args else ""
        resolved = ",".join(sorted(state.values.get(function, {}))) if function and not function.startswith("'") else \
            function.strip("'")
        state.ref(target, "uses-ims", "ims-interface", name, clause="CALL",
                  detail=detail(function=function, function_value=resolved,
                                pcb=args[1] if len(args) > 1 else ""),
                  mode=DLI_ACCESS_MODES.get(function.strip("'").upper(), ""))
        return True
    if name in MQ_CALLS:
        state.ref(target, "uses-mq", "mq-interface", name, clause="CALL", detail=detail(arguments=len(args)),
                  mode=MQ_ACCESS_MODES.get(name, ""))
        return True
    if name in DB2_RUNTIME:
        state.ref(target, "uses-runtime", "runtime", name, clause="CALL", detail=detail(subsystem="DB2"))
        return True
    if name.startswith(("CEE", "ILBO", "IGZ", "CBL_", "C$", "CBL-")) or name in ("SYSTEM", "ABORT"):
        state.ref(target, "uses-runtime", "runtime", name, clause="CALL",
                  detail=detail(subsystem="LE" if name.startswith(("CEE", "ILBO", "IGZ")) else "COBOL-runtime"))
        if name == "SYSTEM":
            command = next((a for a in args if a.startswith("'")), "(dynamic)")
            state.fact(target, "os-command", command.strip("'"))
        return True
    return False


def _name_at(tokens: list[Token], index: int) -> tuple[str, int]:
    """A possibly qualified SQL name (``a.b.c``) starting at ``index``; ``(name, next_index)`` or ``("", index)``."""
    if index >= len(tokens) or tokens[index].kind != "word":
        return "", index
    parts = [tokens[index].text]
    index += 1
    while index + 1 < len(tokens) and tokens[index].text == "." and tokens[index + 1].kind == "word":
        parts.append(tokens[index + 1].text)
        index += 2
    return ".".join(parts).upper(), index


def parse_exec(state: "_State", start: Token, body: list[Token]) -> None:
    """Dispatch one ``EXEC <kind> ... END-EXEC`` block (``body`` excludes both delimiters)."""
    if not body:
        state.fact(start, "exec-other", "(empty)")
        return
    kind = body[0].upper
    if kind == "SQL":
        _sql(state, start, body[1:])
    elif kind == "CICS":
        _cics(state, start, body[1:])
    elif kind == "DLI":
        _dli(state, start, body[1:])
    else:
        state.fact(start, "exec-other", kind, statement=" ".join(t.text for t in body[1:4])[:60])


def _sql(state: "_State", start: Token, stmt: list[Token]) -> None:
    if not stmt:
        return
    operation = stmt[0].upper
    if operation == "INCLUDE" and len(stmt) > 1:
        name = stmt[1].text.upper()
        if name in SQL_INCLUDE_BUILTIN:
            state.fact(stmt[1], "sql-include", name, builtin="yes")
        else:
            state.ref(stmt[1], "copies", "copybook", name, clause="EXEC SQL INCLUDE")
        return
    _sql_host_variables(state, stmt)
    state.fact(start, "sql-statement", operation if operation in SQL_OPERATIONS else "OTHER",
               text=" ".join(t.text for t in stmt[:6])[:80])
    if operation in ("PREPARE", "EXECUTE") and any(t.upper == "IMMEDIATE" for t in stmt[:3]) or operation == "PREPARE":
        state.fact(start, "dynamic-sql", operation)
        state.ref(start, "accesses-table", "table", "", clause=f"EXEC SQL {operation}", dynamic=True,
                  detail=detail(operation=operation))
    if operation == "CALL" and len(stmt) > 1:
        name, _ = _name_at(stmt, 1)
        if name:
            state.ref(stmt[1], "calls", "stored-procedure", name, clause="EXEC SQL CALL")
        return
    if operation == "DECLARE" and len(stmt) > 2:
        declared, after = _name_at(stmt, 1)
        if after < len(stmt) and stmt[after].upper == "TABLE":
            state.fact(stmt[1], "sql-declare-table", declared)
            state.ref(stmt[1], "accesses-table", "table", declared, clause="EXEC SQL DECLARE TABLE",
                      detail=detail(operation="DECLARE"))
            return
        state.fact(stmt[1], "sql-cursor", declared)
    _sql_tables(state, stmt, operation)


def _sql_host_variables(state: "_State", stmt: list[Token]) -> None:
    """``:NAME`` markers bind a host variable: an edge from the program to the data item that carries the value.

    A host variable the program never declares still becomes an edge (unresolved, non-blocking) rather than a
    silent omission, because the binding is written in the source and must be visible.
    """
    clause = f"EXEC SQL {stmt[0].upper if stmt else ''}".strip()
    for index in range(len(stmt) - 1):
        if stmt[index].text == ":" and stmt[index + 1].kind == "word":
            state.ref(stmt[index + 1], "sql-binds-hostvar", "data-item", stmt[index + 1].upper, clause=clause,
                      mode="bind")


def _sql_tables(state: "_State", stmt: list[Token], operation: str) -> None:
    index, count, seen_select = 0, len(stmt), operation
    while index < count:
        word = stmt[index].upper if stmt[index].kind == "word" else ""
        take = word in ("FROM", "JOIN") or (word == "UPDATE" and index == 0) \
            or (word == "INTO" and operation in ("INSERT", "MERGE")) or (word == "TABLE" and operation in ("LOCK", "DROP",
                                                                                                         "ALTER", "CREATE",
                                                                                                         "TRUNCATE"))
        if not take:
            index += 1
            continue
        index += 1
        while index < count:
            if stmt[index].text == "(" or stmt[index].text == ":":
                break  # a sub-select or host variable: the nested FROM is found by the outer loop
            name, after = _name_at(stmt, index)
            if not name or name in SQL_TABLE_STOP:
                break
            state.ref(stmt[index], "accesses-table", "table", name, clause=f"EXEC SQL {operation}",
                      detail=detail(operation=operation, keyword=word),
                      mode=SQL_ACCESS_MODES.get(operation, ""))
            index = after
            if index < count and stmt[index].kind == "word" and stmt[index].upper == "AS":
                index += 2
            elif index < count and stmt[index].kind == "word" and stmt[index].upper not in SQL_TABLE_STOP:
                index += 1  # correlation name
            if word == "FROM" and index < count and stmt[index].text == ",":
                index += 1
                continue
            break
    del seen_select


def _options(stmt: list[Token]) -> list[tuple[str, Token | None, bool, int]]:
    """``(OPTION, argument token or None, argument_is_literal, position)`` for every ``OPTION(arg)``."""
    found = []
    index = 0
    while index < len(stmt):
        token = stmt[index]
        if token.kind == "word" and index + 1 < len(stmt) and stmt[index + 1].text == "(":
            depth, cursor, inner = 1, index + 2, []
            while cursor < len(stmt) and depth:
                if stmt[cursor].text == "(":
                    depth += 1
                elif stmt[cursor].text == ")":
                    depth -= 1
                    if depth == 0:
                        break
                inner.append(stmt[cursor])
                cursor += 1
            argument = inner[0] if len(inner) == 1 else None
            found.append((token.upper, argument, bool(argument and argument.kind == "literal"), index))
            index = cursor
        index += 1
    return found


def _cics_mode(relation: str, full: str) -> str:
    """Operation the CICS command performs **on the resource** the edge points at; ``""`` when there is none."""
    head = full.split()[0]
    if relation == "uses-queue":
        return {"READQ": "get", "WRITEQ": "put", "DELETEQ": "delete"}.get(head, "")
    if relation == "uses-map":
        return {"SEND": "send", "RECEIVE": "receive"}.get(head, "execute")
    if relation == "starts-transaction" or relation == "cics-load":
        return "execute"
    if relation.startswith("cics-"):
        return "invoke"
    return ""


def _cics(state: "_State", start: Token, stmt: list[Token]) -> None:
    if not stmt:
        return
    command = stmt[0].upper
    second = stmt[1].upper if len(stmt) > 1 and stmt[1].kind == "word" else ""
    full = f"{command} {second}".strip() if command in _CICS_SUBCOMMANDS and second in _CICS_SUBCOMMANDS[command] else command
    options = _options(stmt)
    names = {name: (arg, lit) for name, arg, lit, _ in options}
    state.fact(start, "cics-command", full, options=",".join(sorted(names)))
    for option, relation, kind in (("PROGRAM", CICS_PROGRAM_COMMANDS.get(command, ""), "program"),
                                   ("TRANSID", "starts-transaction", "transaction"),
                                   ("MAPSET", "uses-map", "bms-mapset"),
                                   ("MAP", "uses-map", "bms-map"),
                                   ("QUEUE", "uses-queue", "cics-queue"),
                                   ("TSQUEUE", "uses-queue", "cics-queue"),
                                   ("TDQUEUE", "uses-queue", "cics-queue")):
        if option not in names:
            continue
        if option == "MAP" and "MAPSET" in names:
            continue
        if option == "PROGRAM" and not relation:
            if command in ("HANDLE", "ABEND", "ASSIGN", "INQUIRE", "SET", "DUMP"):
                continue
            relation = "cics-link"
        argument, literal = names[option]
        if argument is None:
            continue
        info = detail(command=full, queue_type=second if option.endswith("QUEUE") and second in ("TS", "TD") else "")
        mode = _cics_mode(relation, full)
        if literal:
            state.ref(argument, relation, kind, argument.text.upper(), clause=f"EXEC CICS {full}", detail=info,
                      mode=mode)
        else:
            state.deferred.append((argument, relation, kind, argument.upper, f"EXEC CICS {full}", info, mode))
    for option in ("FILE", "DATASET"):
        if option in names and command in CICS_FILE_COMMANDS:
            argument, literal = names[option]
            if argument is None:
                continue
            info = detail(command=full)
            mode = CICS_FILE_MODES.get(command, "")
            if literal:
                state.ref(argument, "uses-cics-file", "cics-file", argument.text.upper(), clause=f"EXEC CICS {full}",
                          detail=info, mode=mode)
            else:
                state.deferred.append((argument, "uses-cics-file", "cics-file", argument.upper,
                                       f"EXEC CICS {full}", info, mode))


def _dli(state: "_State", start: Token, stmt: list[Token]) -> None:
    if not stmt:
        return
    command = stmt[0].upper
    options = _options(stmt)
    names = {name: arg for name, arg, _, _ in options}
    state.fact(start, "dli-command", command, options=",".join(sorted(names)))
    state.ref(start, "uses-ims", "ims-interface", "EXEC DLI", clause=f"EXEC DLI {command}",
              detail=detail(function=command), mode="execute")
    psb = names.get("PSB")
    if psb is not None:
        state.ref(psb, "uses-ims", "ims-psb", psb.text.upper(), clause=f"EXEC DLI {command}",
                  mode=DLI_ACCESS_MODES.get(command, ""))
    for option in ("SEGMENT", "USING"):
        argument = names.get(option)
        if argument is not None and option == "SEGMENT":
            state.ref(argument, "uses-ims", "ims-segment", argument.text.upper(), clause=f"EXEC DLI {command}",
                      mode=DLI_ACCESS_MODES.get(command, ""))
