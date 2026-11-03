"""Deterministic JCL preprocessing: PROC expansion, symbolic parameters and SET.

Before this module a job that invoked a procedure (``//S1 EXEC PAYPROC``) parsed as a
step with no program, and ``&SYMBOL`` references were never substituted, so DD names,
datasets and programs inside procedures were invisible to discovery. ``expand`` rewrites
the JCL text into the statements the job stream would execute:

- in-stream procedures (``//NAME PROC`` ... ``// PEND``) and library procedures (another
  member whose file stem, or whose ``PROC`` statement, carries the name) are expanded in
  place; expanded step names are ``<calling step>.<proc step>``;
- ``&NAME`` and ``&NAME.`` are replaced from, in order, the EXEC overrides, the
  procedure defaults and the job's ``SET`` values; ``&&`` (a temporary dataset) is kept;
- ``//procstep.DDNAME DD ...`` statements after the EXEC override (or add to) the
  procedure step's DD, parameter by parameter.

Nothing is guessed. Anything outside this subset - nested procedures, ``PARM.step``
overrides, a missing procedure, an unresolved symbol - is returned as an issue so the
semantic builder can refuse the job instead of modelling it wrongly.

Expansion is textual and executes nothing; IF/THEN/ELSE/ENDIF statements pass through
unchanged (the parser records them, nothing evaluates them).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: EXEC keywords that are execution parameters, not symbolic-parameter overrides.
_EXEC_KEYWORDS = frozenset({
    "PARM", "REGION", "TIME", "COND", "ACCT", "ADDRSPC", "DPRTY", "DYNAMNBR",
    "PERFORM", "RD", "CCSID", "MEMLIMIT",
})
_SYMBOL = re.compile(r"&&|&([A-Za-z#$@][A-Za-z0-9#$@]*)\.?")


@dataclass(frozen=True)
class ExpansionIssue:
    """A construct the preprocessor cannot expand faithfully."""

    code: str  # UNRESOLVED_SYMBOL | UNSUPPORTED_PROCEDURE
    message: str
    line: int = 0


@dataclass(frozen=True)
class Expansion:
    text: str
    issues: tuple[ExpansionIssue, ...] = ()
    #: ``CALLER -> PROC`` for every expanded invocation, in order.
    expanded: tuple[tuple[str, str], ...] = ()
    #: SET / procedure-default symbols that were substituted, for the ledger and tests.
    symbols: dict[str, str] = field(default_factory=dict)


@dataclass
class _Stmt:
    name: str
    op: str
    operands: str
    comment: str
    line: int
    raw: list[str]


def split_top(text: str, sep: str = ",") -> list[str]:
    """Split ``text`` at ``sep`` outside quotes and parentheses."""
    parts: list[str] = []
    depth, quote, start = 0, False, 0
    for i, ch in enumerate(text):
        if ch == "'":
            quote = not quote
        elif quote:
            continue
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == sep and depth == 0:
            parts.append(text[start:i])
            start = i + 1
    parts.append(text[start:])
    return parts


def _fields(body: str) -> tuple[str, str, str, str]:
    """``(name, operation, operands, comment)`` of a statement without its ``//``."""
    name = ""
    if body and not body[0].isspace():
        head, _, body = body.partition(" ")
        name = head
    body = body.lstrip()
    op, _, rest = body.partition(" ")
    rest = rest.lstrip()
    # The operand field ends at the first blank outside quotes and parentheses.
    depth, quote, end = 0, False, len(rest)
    for i, ch in enumerate(rest):
        if ch == "'":
            quote = not quote
        elif quote:
            continue
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch.isspace() and depth == 0:
            end = i
            break
    return name, op.upper(), rest[:end], rest[end:].strip()


def _statements(text: str) -> list[_Stmt | str]:
    """Logical statements (continuations joined); everything else stays a raw line."""
    lines = text.splitlines()
    out: list[_Stmt | str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.startswith("//") or line.startswith("//*") or not line[2:].strip():
            out.append(line)
            i += 1
            continue
        name, op, operands, comment = _fields(line[2:].rstrip())
        raw = [line]
        start = i + 1
        while (
            operands.endswith(",") and i + 1 < len(lines)
            and lines[i + 1].startswith("//") and not lines[i + 1].startswith("//*")
            and lines[i + 1][2:3].isspace()
        ):
            i += 1
            raw.append(lines[i])
            _, _, more, _ = _fields("  " + lines[i][2:].strip())
            operands += more
        out.append(_Stmt(name, op, operands, comment, start, raw))
        i += 1
        if op == "DD" and (operands.startswith("*") or operands.upper().startswith("DATA")):
            while i < len(lines) and not lines[i].startswith(("/*", "//")):
                out.append(lines[i])
                i += 1
    return out


class _Expander:
    def __init__(self, library: dict[str, str]) -> None:
        self.issues: list[ExpansionIssue] = []
        self.expanded: list[tuple[str, str]] = []
        self.used: dict[str, str] = {}
        self.procs: dict[str, tuple[dict[str, str], list[_Stmt]]] = {}
        for member, source in library.items():
            self._register_member(member, source)

    # -- procedure catalogue ---------------------------------------------------------
    def _register_member(self, member: str, source: str) -> None:
        stmts = [s for s in _statements(source) if isinstance(s, _Stmt)]
        if any(s.op == "JOB" for s in stmts):
            return  # in-stream procedures belong to their own job only
        stem = re.sub(r"\.[^.]*$", "", member.replace("\\", "/").rsplit("/", 1)[-1]).upper()
        if stmts and stmts[0].op == "PROC":
            head, body = stmts[0], [s for s in stmts[1:] if s.op != "PEND"]
            self.procs.setdefault(head.name.upper() or stem, (self._defaults(head.operands), body))
        elif stmts:
            self.procs.setdefault(stem, ({}, stmts))

    def _register_instream(self, stmts: list[_Stmt]) -> list[_Stmt]:
        """Collect ``PROC``..``PEND`` blocks; return the statements outside them."""
        outside: list[_Stmt] = []
        i = 0
        while i < len(stmts):
            s = stmts[i]
            if s.op == "PROC":
                j = i + 1
                while j < len(stmts) and stmts[j].op != "PEND":
                    j += 1
                self.procs[s.name.upper()] = (self._defaults(s.operands), stmts[i + 1:j])
                i = j + 1
                continue
            outside.append(s)
            i += 1
        return outside

    @staticmethod
    def _defaults(operands: str) -> dict[str, str]:
        out: dict[str, str] = {}
        for part in split_top(operands):
            key, eq, value = part.partition("=")
            if eq and key.strip():
                out[key.strip().upper()] = value
        return out

    # -- substitution ----------------------------------------------------------------
    def _subst(self, text: str, symbols: dict[str, str], line: int) -> str:
        def repl(match: re.Match) -> str:
            if match.group(0) == "&&":
                return "&&"
            key = match.group(1).upper()
            if key in symbols:
                return symbols[key]
            self.issues.append(ExpansionIssue(
                "UNRESOLVED_SYMBOL", f"symbolic parameter &{match.group(1)} has no value", line))
            return match.group(0)

        return _SYMBOL.sub(repl, text)

    # -- main pass -------------------------------------------------------------------
    def run(self, source: str) -> str:
        items = _statements(source)
        stmts = [s for s in items if isinstance(s, _Stmt)]
        outside = {id(s) for s in self._register_instream(stmts)}
        out: list[str] = []
        sets: dict[str, str] = {}
        i = 0
        while i < len(items):
            item = items[i]
            if isinstance(item, str):
                out.append(item)
                i += 1
                continue
            if id(item) not in outside:  # inside an in-stream PROC definition
                i += 1
                continue
            if item.op == "SET":
                for part in split_top(self._subst(item.operands, sets, item.line)):
                    key, eq, value = part.partition("=")
                    if eq:
                        sets[key.strip().upper()] = value
                i += 1
                continue
            if item.op == "EXEC" and not re.match(r"PGM=", item.operands, re.IGNORECASE):
                i = self._expand_call(items, i, sets, outside, out)
                continue
            out.append(self._emit(item, sets))
            i += 1
        return "\n".join(out) + ("\n" if source.endswith("\n") else "")

    def _emit(self, s: _Stmt, symbols: dict[str, str], name: str | None = None) -> str:
        name = s.name if name is None else name
        text = f"//{name:<8} {s.op} {s.operands}".rstrip()
        text = self._subst(text, symbols, s.line)
        return f"{text} {s.comment}".rstrip() if s.comment else text

    def _expand_call(self, items, i: int, sets, outside, out: list[str]) -> int:
        call: _Stmt = items[i]
        i += 1
        params = split_top(call.operands)
        first = params[0].strip()
        proc_name = (first.split("=", 1)[1] if first.upper().startswith("PROC=") else first).upper()
        overrides: dict[str, str] = {}
        exec_params: list[str] = []
        for part in params[1:]:
            key, eq, value = part.partition("=")
            key_up = key.strip().upper()
            if "." in key_up:
                self.issues.append(ExpansionIssue(
                    "UNSUPPORTED_PROCEDURE",
                    f"{key_up}= overrides a parameter of one procedure step; only DD overrides are supported",
                    call.line))
            elif key_up in _EXEC_KEYWORDS:
                exec_params.append(part)
            elif eq:
                overrides[key_up] = self._subst(value, sets, call.line)
        # DD statements after the EXEC are overrides of the procedure's steps.
        dd_over: list[_Stmt] = []
        while i < len(items):
            nxt = items[i]
            if isinstance(nxt, str):
                if nxt.startswith("//*"):
                    i += 1
                    continue
                break
            if nxt.op != "DD" or id(nxt) not in outside:
                break
            dd_over.append(nxt)
            i += 1

        proc = self.procs.get(proc_name)
        if proc is None:
            self.issues.append(ExpansionIssue(
                "UNSUPPORTED_PROCEDURE",
                f"procedure {proc_name} is neither in the job stream nor in a member of the "
                "application", call.line))
            out.append(self._emit(call, sets))
            return i
        defaults, body = proc
        symbols = {**sets, **{k: v for k, v in defaults.items()}, **overrides}
        symbols = {k: self._subst(v, symbols, call.line) if "&" in v else v
                   for k, v in symbols.items()}
        caller = call.name or proc_name
        self.expanded.append((caller, proc_name))

        by_step: dict[str, dict[str, _Stmt]] = {}
        for dd in dd_over:
            step, dot, ddname = dd.name.partition(".")
            if not dot:
                self.issues.append(ExpansionIssue(
                    "UNSUPPORTED_PROCEDURE",
                    f"DD {dd.name} after EXEC {proc_name} names no procedure step (use step.ddname)",
                    dd.line))
                continue
            by_step.setdefault(step.upper(), {})[ddname.upper()] = dd

        current = ""
        emitted_dds: dict[str, set[str]] = {}
        pending_extra: dict[str, list[_Stmt]] = {}

        def flush_extra() -> None:
            for dd in pending_extra.pop(current, []):
                out.append(self._emit(dd, symbols, name=dd.name.partition(".")[2]))

        for stmt in body:
            if stmt.op == "EXEC":
                flush_extra()
                if not re.match(r"PGM=", stmt.operands, re.IGNORECASE):
                    self.issues.append(ExpansionIssue(
                        "UNSUPPORTED_PROCEDURE",
                        f"nested procedure call in {proc_name} step {stmt.name} is not expanded",
                        stmt.line))
                current = stmt.name.upper()
                emitted_dds[current] = set()
                pending_extra[current] = [
                    dd for ddname, dd in by_step.get(current, {}).items()]
                operands = stmt.operands
                if exec_params:  # PARM=, REGION= ... coded on the caller apply to each step
                    operands = self._merge_params(operands, ",".join(exec_params))
                out.append(self._emit(
                    _Stmt(stmt.name, "EXEC", operands, stmt.comment, stmt.line, []),
                    symbols, name=f"{caller}.{stmt.name}"))
            elif stmt.op == "DD":
                override = by_step.get(current, {}).get(stmt.name.upper())
                if override is not None:
                    pending_extra[current] = [
                        d for d in pending_extra[current] if d is not override]
                    merged = self._merge_params(stmt.operands, override.operands)
                    stmt = _Stmt(stmt.name, "DD", merged, stmt.comment, stmt.line, [])
                emitted_dds.setdefault(current, set()).add(stmt.name.upper())
                out.append(self._emit(stmt, symbols))
            else:
                out.append(self._emit(stmt, symbols))
        flush_extra()
        for step in by_step:
            if step not in emitted_dds:
                self.issues.append(ExpansionIssue(
                    "UNSUPPORTED_PROCEDURE",
                    f"DD override names step {step}, which {proc_name} does not contain",
                    call.line))
        return i

    @staticmethod
    def _merge_params(base: str, override: str) -> str:
        """Parameter-level merge: coded override parameters replace the procedure's.

        A keyword replaces the same keyword; a leading positional operand (``*``,
        ``DUMMY``) replaces the procedure's positional operand.
        """
        merged: dict[str, str] = {}
        order: list[str] = []
        for part in split_top(base) + split_top(override):
            key, eq, _ = part.partition("=")
            slot = key.strip().upper() if eq else "#positional"
            if slot not in merged:
                order.append(slot)
            merged[slot] = part
        return ",".join(merged[k] for k in order)


def expand(source: str, library: dict[str, str] | None = None) -> Expansion:
    """Expand procedures and symbolic parameters of ``source``.

    ``library`` maps member names to JCL text; a member supplies the procedure whose name
    is its file stem or the name on its ``PROC`` statement.
    """
    if "//" not in source:
        return Expansion(text=source)
    expander = _Expander(library or {})
    text = expander.run(source)
    return Expansion(
        text=text,
        issues=tuple(expander.issues),
        expanded=tuple(expander.expanded),
    )


_JOB = re.compile(r"^//\S*\s+JOB\b", re.MULTILINE)
_PROC = re.compile(r"^//\S*\s+PROC\b", re.MULTILINE)


def procedure_members(sources: dict[str, str]) -> frozenset[str]:
    """Members that only define a procedure (no ``JOB``): they are not job streams."""
    called = {
        proc for source in sources.values() if _JOB.search(source)
        for _, proc in expand(source, sources).expanded
    }
    members = set()
    for member, source in sources.items():
        if _JOB.search(source):
            continue
        stem = re.sub(r"\.[^.]*$", "", member.replace("\\", "/").rsplit("/", 1)[-1]).upper()
        if stem in called or _PROC.search(source):
            members.add(member)
    return frozenset(members)
