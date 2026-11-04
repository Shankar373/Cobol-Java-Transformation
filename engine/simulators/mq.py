"""SIMMQ-1: a deterministic, in-memory model of the IBM MQ calls a batch COBOL program makes.

Specification version ``SIMMQ-1.0``.  Calls: MQCONN, MQOPEN, MQPUT, MQGET, MQCLOSE, MQCMIT, MQBACK,
MQDISC, plus an administrative ``SETQ``.  Each call returns ``(completion code, reason code)`` and,
for MQGET, the message.  Completion codes: 0 OK, 1 WARNING, 2 FAILED.

What is modelled
    * FIFO queues with a maximum depth; get/put inhibit; shared and exclusive input opens.
    * Unit of work: a ``SYNCPOINT`` put is invisible to getters until ``MQCMIT`` and vanishes on
      ``MQBACK``; a ``SYNCPOINT`` get removes the message provisionally and ``MQBACK`` returns it to the
      front of its queue; ``MQDISC`` commits.  Without the option a call is outside the unit of work.
    * Browse (first / next) with a cursor per object handle; truncated messages (accepted or not).
    * A wait (``MQGMO_WAIT``) on an empty queue ends as no-message-available: the model is
      single-threaded and has no clock.

What is not modelled (a program using it is not covered): message descriptors and properties, priorities,
MsgId/CorrelId matching, topics, distribution lists, channels, security, persistence across runs, and the
real MQ structures (MQMD, MQOD, MQPMO, MQGMO) -- options are plain integers below.

Reason codes follow IBM's documented values.  They have **not** been checked against an IBM MQ queue
manager here (none is available); this model is the specification, and equivalence to it is
``SIMULATOR_VERIFIED``, never ``IBM_VERIFIED``.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

SPEC_VERSION = "SIMMQ-1.0"

MQCC_OK, MQCC_WARNING, MQCC_FAILED = 0, 1, 2

MQRC_NONE = 0
MQRC_ALREADY_CONNECTED = 2002
MQRC_GET_INHIBITED = 2016
MQRC_HCONN_ERROR = 2018
MQRC_HOBJ_ERROR = 2019
MQRC_NO_MSG_AVAILABLE = 2033
MQRC_NOT_OPEN_FOR_BROWSE = 2036
MQRC_NOT_OPEN_FOR_INPUT = 2037
MQRC_NOT_OPEN_FOR_OUTPUT = 2039
MQRC_OBJECT_IN_USE = 2042
MQRC_PUT_INHIBITED = 2051
MQRC_Q_FULL = 2053
MQRC_Q_MGR_NAME_ERROR = 2058
MQRC_TRUNCATED_MSG_ACCEPTED = 2079
MQRC_TRUNCATED_MSG_FAILED = 2080
MQRC_UNKNOWN_OBJECT_NAME = 2085
MQRC_OPTIONS_ERROR = 2046
MQRC_NO_MSG_UNDER_CURSOR = 2034

# MQOPEN options
MQOO_INPUT_SHARED = 2
MQOO_INPUT_EXCLUSIVE = 4
MQOO_BROWSE = 8
MQOO_OUTPUT = 16
_OPEN_BITS = MQOO_INPUT_SHARED | MQOO_INPUT_EXCLUSIVE | MQOO_BROWSE | MQOO_OUTPUT

# MQPMO / MQGMO options (plain integers in SIMMQ-1)
OPT_WAIT = 1
OPT_SYNCPOINT = 2
OPT_NO_SYNCPOINT = 4
OPT_BROWSE_FIRST = 16
OPT_BROWSE_NEXT = 32
OPT_ACCEPT_TRUNCATED = 64
_GET_BITS = (OPT_WAIT | OPT_SYNCPOINT | OPT_NO_SYNCPOINT | OPT_BROWSE_FIRST | OPT_BROWSE_NEXT
             | OPT_ACCEPT_TRUNCATED)
_PUT_BITS = OPT_SYNCPOINT | OPT_NO_SYNCPOINT

DEFAULT_MAX_DEPTH = 5000


@dataclass
class _Queue:
    name: str
    max_depth: int = DEFAULT_MAX_DEPTH
    get_inhibited: bool = False
    put_inhibited: bool = False
    messages: deque = field(default_factory=deque)  # of _Message, committed or not
    shared_inputs: int = 0
    exclusive_input: bool = False


@dataclass(eq=False)  # identity: two equal payloads are still two messages
class _Message:
    data: bytes
    owner: int | None = None  # connection of an uncommitted put; None once committed
    taken_by: int | None = None  # connection of an uncommitted get


@dataclass
class _Handle:
    queue: str
    options: int
    cursor: int = -1  # browse position (index into the visible messages)


@dataclass
class GetResult:
    cc: int
    rc: int
    data: bytes = b""
    length: int = 0  # full length of the message the call saw


class SimMq:
    """One queue manager.  Handles are small integers allocated in call order (deterministic)."""

    def __init__(self, qmgr: str = "QM1", queues: tuple[str, ...] = ("Q1", "Q2", "Q3")) -> None:
        self.qmgr = qmgr
        self._queues = {name: _Queue(name) for name in queues}
        self._connections: dict[int, dict[int, _Handle]] = {}
        self._next_conn = 1
        self._next_obj = 1

    # -- administration -------------------------------------------------------------------
    def setq(self, name: str, max_depth: int, get_inhibited: bool, put_inhibited: bool) -> None:
        queue = self._queues.setdefault(name, _Queue(name))
        queue.max_depth = max_depth
        queue.get_inhibited = get_inhibited
        queue.put_inhibited = put_inhibited

    def depth(self, name: str) -> int:
        """Messages a getter could see: committed puts not provisionally taken."""
        queue = self._queues[name]
        return sum(1 for m in queue.messages if m.owner is None and m.taken_by is None)

    # -- calls ----------------------------------------------------------------------------
    def mqconn(self, qmgr: str) -> tuple[int, int, int]:
        """``(hconn, cc, rc)``."""
        if qmgr.strip() not in ("", self.qmgr):
            return 0, MQCC_FAILED, MQRC_Q_MGR_NAME_ERROR
        hconn = self._next_conn
        self._next_conn += 1
        self._connections[hconn] = {}
        return hconn, MQCC_OK, MQRC_NONE

    def mqopen(self, hconn: int, name: str, options: int) -> tuple[int, int, int]:
        """``(hobj, cc, rc)``."""
        handles = self._connections.get(hconn)
        if handles is None:
            return 0, MQCC_FAILED, MQRC_HCONN_ERROR
        if options & ~_OPEN_BITS or not options & _OPEN_BITS:
            return 0, MQCC_FAILED, MQRC_OPTIONS_ERROR
        if options & MQOO_INPUT_SHARED and options & MQOO_INPUT_EXCLUSIVE:
            return 0, MQCC_FAILED, MQRC_OPTIONS_ERROR
        queue = self._queues.get(name.strip())
        if queue is None:
            return 0, MQCC_FAILED, MQRC_UNKNOWN_OBJECT_NAME
        if options & MQOO_INPUT_EXCLUSIVE and (queue.exclusive_input or queue.shared_inputs):
            return 0, MQCC_FAILED, MQRC_OBJECT_IN_USE
        if options & MQOO_INPUT_SHARED and queue.exclusive_input:
            return 0, MQCC_FAILED, MQRC_OBJECT_IN_USE
        if options & MQOO_INPUT_EXCLUSIVE:
            queue.exclusive_input = True
        if options & MQOO_INPUT_SHARED:
            queue.shared_inputs += 1
        hobj = self._next_obj
        self._next_obj += 1
        handles[hobj] = _Handle(queue.name, options)
        return hobj, MQCC_OK, MQRC_NONE

    def mqput(self, hconn: int, hobj: int, data: bytes, options: int = 0) -> tuple[int, int]:
        handle, error = self._handle(hconn, hobj)
        if error:
            return error
        if options & ~_PUT_BITS or options & OPT_SYNCPOINT and options & OPT_NO_SYNCPOINT:
            return MQCC_FAILED, MQRC_OPTIONS_ERROR
        if not handle.options & MQOO_OUTPUT:
            return MQCC_FAILED, MQRC_NOT_OPEN_FOR_OUTPUT
        queue = self._queues[handle.queue]
        if queue.put_inhibited:
            return MQCC_FAILED, MQRC_PUT_INHIBITED
        if len(queue.messages) >= queue.max_depth:
            return MQCC_FAILED, MQRC_Q_FULL
        queue.messages.append(_Message(bytes(data), owner=hconn if options & OPT_SYNCPOINT else None))
        return MQCC_OK, MQRC_NONE

    def mqget(self, hconn: int, hobj: int, max_length: int, options: int = 0) -> GetResult:
        handle, error = self._handle(hconn, hobj)
        if error:
            return GetResult(*error)
        browse = options & (OPT_BROWSE_FIRST | OPT_BROWSE_NEXT)
        bad = (
            options & ~_GET_BITS
            or options & OPT_SYNCPOINT and options & OPT_NO_SYNCPOINT
            or options & OPT_BROWSE_FIRST and options & OPT_BROWSE_NEXT
            or browse and options & OPT_SYNCPOINT
        )
        if bad or max_length < 0:
            return GetResult(MQCC_FAILED, MQRC_OPTIONS_ERROR)
        if browse and not handle.options & MQOO_BROWSE:
            return GetResult(MQCC_FAILED, MQRC_NOT_OPEN_FOR_BROWSE)
        if not browse and not handle.options & (MQOO_INPUT_SHARED | MQOO_INPUT_EXCLUSIVE):
            return GetResult(MQCC_FAILED, MQRC_NOT_OPEN_FOR_INPUT)
        queue = self._queues[handle.queue]
        if queue.get_inhibited:
            return GetResult(MQCC_FAILED, MQRC_GET_INHIBITED)
        visible = [m for m in queue.messages
                   if (m.owner is None or m.owner == hconn) and m.taken_by is None]
        if browse:
            handle.cursor = 0 if options & OPT_BROWSE_FIRST else handle.cursor + 1
            if handle.cursor >= len(visible):
                handle.cursor = max(len(visible) - 1, -1) if options & OPT_BROWSE_NEXT else -1
                return GetResult(MQCC_FAILED, MQRC_NO_MSG_AVAILABLE)
            message = visible[handle.cursor]
        else:
            if not visible:
                return GetResult(MQCC_FAILED, MQRC_NO_MSG_AVAILABLE)
            message = visible[0]
        length = len(message.data)
        if length > max_length and not options & OPT_ACCEPT_TRUNCATED:
            return GetResult(MQCC_FAILED, MQRC_TRUNCATED_MSG_FAILED, message.data[:max_length], length)
        cc, rc = (MQCC_WARNING, MQRC_TRUNCATED_MSG_ACCEPTED) if length > max_length else (MQCC_OK, MQRC_NONE)
        if not browse:
            if options & OPT_SYNCPOINT:
                message.taken_by = hconn
            else:
                queue.messages.remove(message)
        return GetResult(cc, rc, message.data[:max_length], length)

    def mqclose(self, hconn: int, hobj: int) -> tuple[int, int]:
        handle, error = self._handle(hconn, hobj)
        if error:
            return error
        queue = self._queues[handle.queue]
        if handle.options & MQOO_INPUT_EXCLUSIVE:
            queue.exclusive_input = False
        if handle.options & MQOO_INPUT_SHARED:
            queue.shared_inputs -= 1
        del self._connections[hconn][hobj]
        return MQCC_OK, MQRC_NONE

    def mqcmit(self, hconn: int) -> tuple[int, int]:
        if hconn not in self._connections:
            return MQCC_FAILED, MQRC_HCONN_ERROR
        for queue in self._queues.values():
            kept = deque()
            for message in queue.messages:
                if message.taken_by == hconn:
                    continue  # a provisional get becomes final
                if message.owner == hconn:
                    message.owner = None  # a provisional put becomes visible
                kept.append(message)
            queue.messages = kept
        return MQCC_OK, MQRC_NONE

    def mqback(self, hconn: int) -> tuple[int, int]:
        if hconn not in self._connections:
            return MQCC_FAILED, MQRC_HCONN_ERROR
        for queue in self._queues.values():
            kept = deque()
            for message in queue.messages:
                if message.owner == hconn:
                    continue  # a provisional put vanishes
                if message.taken_by == hconn:
                    message.taken_by = None  # a provisional get is undone, in place
                kept.append(message)
            queue.messages = kept
        return MQCC_OK, MQRC_NONE

    def mqdisc(self, hconn: int) -> tuple[int, int]:
        if hconn not in self._connections:
            return MQCC_FAILED, MQRC_HCONN_ERROR
        self.mqcmit(hconn)
        for hobj in list(self._connections[hconn]):
            self.mqclose(hconn, hobj)
        del self._connections[hconn]
        return MQCC_OK, MQRC_NONE

    # -- helpers --------------------------------------------------------------------------
    def _handle(self, hconn: int, hobj: int):
        handles = self._connections.get(hconn)
        if handles is None:
            return None, (MQCC_FAILED, MQRC_HCONN_ERROR)
        handle = handles.get(hobj)
        if handle is None:
            return None, (MQCC_FAILED, MQRC_HOBJ_ERROR)
        return handle, None


# ------------------------------------------------------------------------------------------
# Scripts and the canonical trace
# ------------------------------------------------------------------------------------------

def run_script(script: str) -> list[str]:
    """Run a script and return its canonical trace, one line per operation.

    Script lines (fields separated by one space; message data is hexadecimal, ``-`` is empty):
    ``QMGR name q1,q2,..`` (first line), ``SETQ queue maxdepth getinh putinh``, ``CONN [qmgr]``,
    ``OPEN hconn queue options``, ``PUT hconn hobj hex options``, ``GET hconn hobj maxlen options``,
    ``CLOSE hconn hobj``, ``CMIT hconn``, ``BACK hconn``, ``DISC hconn``, ``DEPTH queue``.
    A trace line is the operation as given, `` -> ``, then ``cc rc`` and, where the call returns them,
    the handle (``h=n``) or the message (``len=n data=hex``).
    """
    mq: SimMq | None = None
    trace: list[str] = []
    for raw in script.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        op, *args = line.split(" ")
        if op == "QMGR":
            mq = SimMq(args[0], tuple(args[1].split(",")))
            trace.append(f"{line} -> {SPEC_VERSION}")
            continue
        if mq is None:
            raise ValueError("a script starts with QMGR")
        trace.append(f"{line} -> {_step(mq, op, args)}")
    return trace


def _hex(data: bytes) -> str:
    return data.hex() if data else "-"


def _step(mq: SimMq, op: str, args: list[str]) -> str:
    if op == "SETQ":
        mq.setq(args[0], int(args[1]), args[2] == "1", args[3] == "1")
        return "ok"
    if op == "DEPTH":
        return f"depth={mq.depth(args[0])}"
    if op == "CONN":
        hconn, cc, rc = mq.mqconn(args[0] if args else "")  # a blank name is the default manager
        return f"{cc} {rc} h={hconn}"
    if op == "OPEN":
        hobj, cc, rc = mq.mqopen(int(args[0]), args[1], int(args[2]))
        return f"{cc} {rc} h={hobj}"
    if op == "PUT":
        data = b"" if args[2] == "-" else bytes.fromhex(args[2])
        cc, rc = mq.mqput(int(args[0]), int(args[1]), data, int(args[3]))
        return f"{cc} {rc}"
    if op == "GET":
        result = mq.mqget(int(args[0]), int(args[1]), int(args[2]), int(args[3]))
        return f"{result.cc} {result.rc} len={result.length} data={_hex(result.data)}"
    if op == "CLOSE":
        cc, rc = mq.mqclose(int(args[0]), int(args[1]))
        return f"{cc} {rc}"
    if op in ("CMIT", "BACK", "DISC"):
        call = {"CMIT": mq.mqcmit, "BACK": mq.mqback, "DISC": mq.mqdisc}[op]
        cc, rc = call(int(args[0]))
        return f"{cc} {rc}"
    raise ValueError(f"unknown operation {op}")
