"""SIMCICS-1: a deterministic, in-memory model of the CICS commands a COBOL transaction uses on data.

Specification version ``SIMCICS-1.0``.  File control on keyed (KSDS-style) files -- READ, READ UPDATE,
WRITE, REWRITE, DELETE, STARTBR, READNEXT, READPREV, ENDBR -- temporary-storage queues (WRITEQ TS,
READQ TS, DELETEQ TS) and SYNCPOINT / SYNCPOINT ROLLBACK.  Every command returns a RESP code.

What is modelled
    * Files declared by name with a key length and a record length; a file may be open or closed.  A record
      is a fixed-length string whose first ``keylen`` characters are its key; keys are unique.  A WRITE whose
      key differs from the record's key characters is INVREQ; a wrong length is LENGERR.
    * READ UPDATE holds the record for the task; REWRITE and DELETE (without a key) act on the held record
      and release it; SYNCPOINT releases it too.
    * Browsing: STARTBR positions at a key (GTEQ or EQUAL), READNEXT / READPREV move and return records,
      ENDBR ends the browse; one browse per file.
    * Recovery: every change since the last SYNCPOINT is undone by SYNCPOINT ROLLBACK.
    * Temporary storage: items are numbered from 1 in write order; READQ by item number or NEXT.

What is not modelled: terminal I/O (SEND/RECEIVE MAP), BMS, program control (LINK, XCTL, RETURN, ABEND),
transient data, locking between tasks, record-level wait, generic keys, RIDFLD forms other than the
full key, journaling, and CICS storage.  RESP values are IBM's documented DFHRESP numbers; none has been
compared with a CICS region (none is available), so equivalence to this model is ``SIMULATOR_VERIFIED``,
never ``IBM_VERIFIED``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

SPEC_VERSION = "SIMCICS-1.0"

NORMAL = 0
FILENOTFOUND = 12
NOTFND = 13
DUPREC = 14
INVREQ = 16
NOTOPEN = 19
ENDFILE = 20
LENGERR = 22
ITEMERR = 26
QIDERR = 44

_NAMES = {
    NORMAL: "NORMAL", FILENOTFOUND: "FILENOTFOUND", NOTFND: "NOTFND", DUPREC: "DUPREC", INVREQ: "INVREQ",
    NOTOPEN: "NOTOPEN", ENDFILE: "ENDFILE", LENGERR: "LENGERR", ITEMERR: "ITEMERR", QIDERR: "QIDERR",
}


@dataclass
class _File:
    name: str
    key_length: int
    record_length: int
    is_open: bool = True
    records: dict = field(default_factory=dict)  # key -> record, kept sorted on demand
    held: "str | None" = None  # key of the record held by READ UPDATE
    cursor: "str | None" = None  # key of the last record returned by a browse
    browsing: bool = False
    position: "str | None" = None  # key the next READNEXT starts from (inclusive) / READPREV (exclusive)


class SimCics:
    def __init__(self) -> None:
        self._files: dict[str, _File] = {}
        self._queues: dict[str, list[str]] = {}
        self._undo: list = []  # callables restoring the state before each change since the last syncpoint
        self._next_cursor: dict[str, int] = {}

    # -- configuration ----------------------------------------------------------------------
    def define(self, name: str, key_length: int, record_length: int, is_open: bool) -> None:
        self._files[name] = _File(name, key_length, record_length, is_open)

    def load(self, name: str, record: str) -> None:
        """Seed a record outside the unit of work (initial file contents)."""
        file = self._files[name]
        if len(record) != file.record_length:
            raise ValueError(f"LOAD {name}: record is {len(record)} characters, the file's is {file.record_length}")
        file.records[record[: file.key_length]] = record

    # -- helpers ------------------------------------------------------------------------------
    def _file(self, name: str):
        file = self._files.get(name)
        if file is None:
            return None, FILENOTFOUND
        if not file.is_open:
            return None, NOTOPEN
        return file, NORMAL

    @staticmethod
    def _sorted(file: _File) -> list[str]:
        return sorted(file.records)

    # -- file commands ------------------------------------------------------------------------
    def read(self, name: str, key: str, update: bool = False):
        file, resp = self._file(name)
        if file is None:
            return resp, ""
        if len(key) != file.key_length:
            return LENGERR, ""
        record = file.records.get(key)
        if record is None:
            return NOTFND, ""
        if update:
            file.held = key
        return NORMAL, record

    def write(self, name: str, key: str, data: str) -> int:
        file, resp = self._file(name)
        if file is None:
            return resp
        if len(data) != file.record_length or len(key) != file.key_length:
            return LENGERR
        if data[: file.key_length] != key:
            return INVREQ
        if key in file.records:
            return DUPREC
        file.records[key] = data
        self._undo.append(lambda f=file, k=key: f.records.pop(k, None))
        return NORMAL

    def rewrite(self, name: str, data: str) -> int:
        file, resp = self._file(name)
        if file is None:
            return resp
        if file.held is None:
            return INVREQ
        if len(data) != file.record_length:
            return LENGERR
        if data[: file.key_length] != file.held:
            return INVREQ
        key, previous = file.held, file.records[file.held]
        file.records[key] = data
        file.held = None
        self._undo.append(lambda f=file, k=key, p=previous: f.records.__setitem__(k, p))
        return NORMAL

    def delete(self, name: str, key: "str | None") -> int:
        file, resp = self._file(name)
        if file is None:
            return resp
        if key is None:
            if file.held is None:
                return INVREQ
            key = file.held
        elif len(key) != file.key_length:
            return LENGERR
        previous = file.records.get(key)
        if previous is None:
            return NOTFND
        del file.records[key]
        if file.held == key:
            file.held = None
        self._undo.append(lambda f=file, k=key, p=previous: f.records.__setitem__(k, p))
        return NORMAL

    # -- browse ---------------------------------------------------------------------------------
    def startbr(self, name: str, key: str, equal: bool) -> int:
        file, resp = self._file(name)
        if file is None:
            return resp
        if len(key) != file.key_length:
            return LENGERR
        if file.browsing:
            return INVREQ
        keys = self._sorted(file)
        if equal:
            if key not in file.records:
                return NOTFND
            start = key
        else:
            first = next((k for k in keys if k >= key), None)
            if first is None:
                return NOTFND
            start = first
        file.browsing = True
        file.position = start
        file.cursor = None
        return NORMAL

    def readnext(self, name: str):
        file, resp = self._file(name)
        if file is None:
            return resp, ""
        if not file.browsing:
            return INVREQ, ""
        keys = self._sorted(file)
        if file.cursor is None:
            candidates = [k for k in keys if k >= file.position]
        else:
            candidates = [k for k in keys if k > file.cursor]
        if not candidates:
            return ENDFILE, ""
        file.cursor = candidates[0]
        return NORMAL, file.records[file.cursor]

    def readprev(self, name: str):
        file, resp = self._file(name)
        if file is None:
            return resp, ""
        if not file.browsing:
            return INVREQ, ""
        keys = self._sorted(file)
        if file.cursor is None:
            candidates = [k for k in keys if k < file.position]
        else:
            candidates = [k for k in keys if k < file.cursor]
        if not candidates:
            return ENDFILE, ""
        file.cursor = candidates[-1]
        return NORMAL, file.records[file.cursor]

    def endbr(self, name: str) -> int:
        file, resp = self._file(name)
        if file is None:
            return resp
        if not file.browsing:
            return INVREQ
        file.browsing = False
        file.cursor = None
        file.position = None
        return NORMAL

    # -- temporary storage --------------------------------------------------------------------
    def writeq(self, queue: str, data: str):
        """``(resp, item)``; the queue is created by its first write."""
        items = self._queues.setdefault(queue, [])
        items.append(data)
        self._undo.append(lambda q=queue: self._undo_writeq(q))
        return NORMAL, len(items)

    def _undo_writeq(self, queue: str) -> None:
        items = self._queues.get(queue)
        if items is None:
            return
        items.pop()
        if not items:
            del self._queues[queue]

    def readq(self, queue: str, item: "int | None"):
        """``(resp, item, data)``; ``item`` None reads the next item after the last one read."""
        items = self._queues.get(queue)
        if items is None:
            return QIDERR, 0, ""
        if item is None:
            item = self._next_cursor.get(queue, 0) + 1
        if not 1 <= item <= len(items):
            return ITEMERR, 0, ""
        self._next_cursor[queue] = item
        return NORMAL, item, items[item - 1]

    def deleteq(self, queue: str) -> int:
        items = self._queues.get(queue)
        if items is None:
            return QIDERR
        del self._queues[queue]
        self._next_cursor.pop(queue, None)
        self._undo.append(lambda q=queue, i=items: self._queues.__setitem__(q, i))
        return NORMAL

    # -- unit of work -------------------------------------------------------------------------
    def syncpoint(self, rollback: bool = False) -> int:
        if rollback:
            while self._undo:
                self._undo.pop()()
        self._undo.clear()
        for file in self._files.values():
            file.held = None
        return NORMAL


# ------------------------------------------------------------------------------------------
# Scripts and the canonical trace
# ------------------------------------------------------------------------------------------

def run_script(script: str) -> list[str]:
    """Run a script and return its canonical trace, one line per command.

    Setup: ``FILE name keylen reclen open|closed``, ``LOAD name record``.  Commands: ``READ name key
    [UPDATE]``, ``WRITE name key data``, ``REWRITE name data``, ``DELETE name [key]``, ``STARTBR name key
    GTEQ|EQUAL``, ``READNEXT name``, ``READPREV name``, ``ENDBR name``, ``WRITEQ queue data``, ``READQ queue
    item|NEXT``, ``DELETEQ queue``, ``SYNCPOINT [ROLLBACK]``.  Data and keys are ASCII without spaces.  A
    trace line is the command, `` -> ``, the RESP name and, for a returned record, `` data=...``.
    """
    cics = SimCics()
    trace: list[str] = []
    for raw in script.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        op, *args = line.split(" ")
        if op == "FILE":
            cics.define(args[0], int(args[1]), int(args[2]), args[3] == "open")
            trace.append(f"{line} -> {SPEC_VERSION}")
        elif op == "LOAD":
            cics.load(args[0], args[1])
            trace.append(f"{line} -> loaded")
        else:
            trace.append(f"{line} -> {_step(cics, op, args)}")
    return trace


def _resp(code: int) -> str:
    return _NAMES.get(code, str(code))


def _with_data(resp: int, data: str) -> str:
    return _resp(resp) if resp != NORMAL else f"{_resp(resp)} data={data}"


def _step(cics: SimCics, op: str, args: list[str]) -> str:
    if op == "READ":
        return _with_data(*cics.read(args[0], args[1], len(args) > 2 and args[2] == "UPDATE"))
    if op == "WRITE":
        return _resp(cics.write(args[0], args[1], args[2]))
    if op == "REWRITE":
        return _resp(cics.rewrite(args[0], args[1]))
    if op == "DELETE":
        return _resp(cics.delete(args[0], args[1] if len(args) > 1 else None))
    if op == "STARTBR":
        return _resp(cics.startbr(args[0], args[1], args[2] == "EQUAL"))
    if op == "READNEXT":
        return _with_data(*cics.readnext(args[0]))
    if op == "READPREV":
        return _with_data(*cics.readprev(args[0]))
    if op == "ENDBR":
        return _resp(cics.endbr(args[0]))
    if op == "WRITEQ":
        resp, item = cics.writeq(args[0], args[1])
        return f"{_resp(resp)} item={item}"
    if op == "READQ":
        resp, item, data = cics.readq(args[0], None if args[1] == "NEXT" else int(args[1]))
        return _resp(resp) if resp != NORMAL else f"{_resp(resp)} item={item} data={data}"
    if op == "DELETEQ":
        return _resp(cics.deleteq(args[0]))
    if op == "SYNCPOINT":
        return _resp(cics.syncpoint(len(args) > 0 and args[0] == "ROLLBACK"))
    return "INVREQ"
