"""JCL scanner: jobs, procedures, steps, DD statements, symbols, includes, utilities and compile/link steps.

Operates on one file at a time with no outside expansion: a step that runs a cataloged procedure is an ``executes``
reference to that procedure (resolved later against the procedure members in the estate), and symbols are substituted
only from values visible in the same file (``SET``, ``PROC`` defaults, ``EXEC`` parameters).  A name that still
contains an unresolved symbol is reported as dynamic, never guessed.
"""

from __future__ import annotations

import re

from .findings import Fact, FileScan, Ref, ScanProblem, detail
from .jcl_syntax import Statement, operand, parse_operands, read_statements, split_top, substitute, unquote
from .jcl_utils import (
    SYSTEM_PROGRAMS,
    analyse_cics_csd,
    analyse_db2_utility,
    analyse_idcams,
    analyse_mq_utility,
    analyse_sort,
    analyse_tso,
    ims_parameters,
)

__all__ = ["scan_jcl", "scan_control_text"]

_COBOL_COMPILERS = frozenset({"IGYCRCTL", "ELAXF"})
_COMPILE_PROCS = re.compile(r"^(IGYW|IGYC|DFHYI|DFHEI|DSNHI|DSNHCOB|ELAX|IGYR)", re.IGNORECASE)
_LINKERS = frozenset({"IEWL", "HEWL", "IEWBLINK", "HEWLH096"})
_LIBRARY_DDS = {"STEPLIB": "steplib", "JOBLIB": "joblib", "SYSLIB": "syslib", "DFSRESLB": "ims-reslib", "ISPPLIB": "panel",
                "SYSLMOD": "load-library", "SYSPROC": "clist", "PROCLIB": "proclib", "SYSIN": ""}
_DSN_RE = re.compile(r"^[A-Za-z0-9#@$][A-Za-z0-9#@$-]{0,7}(?:\.[A-Za-z0-9#@$][A-Za-z0-9#@$-]{0,7})*$")
_UTILITY_BODIES = {
    "IDCAMS": "idcams", "SORT": "sort", "ICEMAN": "sort", "SYNCSORT": "sort", "DFSORT": "sort", "ICETOOL": "sort",
    "ICEGENER": "sort", "IKJEFT01": "tso", "IKJEFT1A": "tso", "IKJEFT1B": "tso", "DSNUTILB": "db2-utility",
    "DFHCSDUP": "csd", "CSQUTIL": "mq", "CSQBBATCH": "mq",
}


class _Ctx:
    def __init__(self, path: str, scan: FileScan, stem: str) -> None:
        self.path, self.scan, self.stem = path, scan, stem
        self.job = ""
        self.proc = ""
        self.step = ""
        self.step_program = ""
        self.step_is_proc = False
        self.symbols: dict[str, str] = {}
        self.step_ddnames: dict[str, str] = {}
        self.has_job = False
        self.in_proc = False

    @property
    def owner(self) -> str:
        scope = f"proc:{self.proc}" if self.in_proc else (f"job:{self.job}" if self.job else f"proc:{self.stem.upper()}")
        return f"{scope}/{self.step}" if self.step else scope

    def fact(self, st: Statement, category: str, name: str, **info: object) -> None:
        self.scan.facts.append(Fact(self.path, st.line, 1, category, name, self.owner, detail(**info)))

    def ref(self, st: Statement, relation: str, kind: str, target: str, clause: str, **kw: object) -> None:
        self.scan.refs.append(Ref(self.path, st.line, 1, relation, kind, target, self.owner, clause, **kw))  # type: ignore[arg-type]


def scan_jcl(path: str, text: str) -> FileScan:
    """Scan a JCL job or procedure member."""
    scan = FileScan(path=path, line_count=text.count("\n") + (0 if text.endswith("\n") or not text else 1))
    stem = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    statements, comments, problems = read_statements(text)
    ctx = _Ctx(path, scan, stem)
    for number, message in problems:
        scan.problems.append(ScanProblem(path, number, "JCL_BAD_NAME", message))
    if not statements:
        scan.problems.append(ScanProblem(path, 1, "JCL_NO_STATEMENTS", "no JCL statements were found"))
    for st in statements:
        _statement(ctx, st)
    scan.facts.append(Fact(path, 1, 1, "jcl-summary", stem, "", detail(statements=len(statements), comment_lines=comments,
                                                                      jobs=1 if ctx.has_job else 0)))
    return scan.sorted()


def scan_control_text(path: str, kind: str, text: str) -> FileScan:
    """Scan a standalone control file (IDCAMS/SORT/TSO) as if it were SYSIN data."""
    scan = FileScan(path=path, line_count=text.count("\n") + 1)
    body = [(n, line) for n, line in enumerate(text.splitlines(), start=1)]
    owner = f"file:{path}"
    if kind == "idcams":
        refs, facts = analyse_idcams(path, body, owner)
    else:
        refs, facts = analyse_sort(path, body, owner, "SORT")
    scan.refs, scan.facts = list(refs), list(facts)
    return scan.sorted()


def _statement(ctx: _Ctx, st: Statement) -> None:
    op = st.op
    if op == "JOB":
        ctx.has_job = True
        ctx.job, ctx.in_proc, ctx.step = st.name.upper(), False, ""
        ctx.symbols = {}
        operands = parse_operands(st.operands)
        ctx.fact(st, "jcl-job", st.name.upper(), job_class=operand(operands, "CLASS"), msgclass=operand(operands, "MSGCLASS"))
    elif op == "PROC":
        ctx.in_proc, ctx.proc, ctx.step = True, (st.name.upper() or ctx.stem.upper()), ""
        defaults = {k: unquote(v) for k, v in parse_operands(st.operands) if k}
        ctx.symbols.update(defaults)
        ctx.fact(st, "jcl-proc", ctx.proc, parameters=",".join(sorted(defaults)))
    elif op == "PEND":
        ctx.in_proc, ctx.step = False, ""
    elif op == "SET":
        for key, value in parse_operands(st.operands):
            if key:
                resolved, _ = substitute(unquote(value), ctx.symbols)
                ctx.symbols[key] = resolved
        ctx.fact(st, "jcl-set", st.operands[:60])
    elif op == "EXEC":
        _exec(ctx, st)
    elif op == "DD":
        _dd(ctx, st)
    elif op == "INCLUDE":
        member = operand(parse_operands(st.operands), "MEMBER")
        if member:
            ctx.ref(st, "includes", "jcl-member", member.upper(), "JCL INCLUDE")
    elif op == "JCLLIB":
        for library in _list(operand(parse_operands(st.operands), "ORDER")):
            ctx.ref(st, "uses-library", "dataset", library.upper(), "JCLLIB ORDER", detail=detail(purpose="procedure-library"))
    elif op in ("IF", "ELSE", "ENDIF", "THEN"):
        ctx.fact(st, "jcl-condition", op, text=(st.name + " " + st.operands)[:80])
    elif op in ("OUTPUT", "XMIT", "COMMAND", "SCHEDULE", "NOTIFY", "CNTL", "ENDCNTL", "EXPORT"):
        ctx.fact(st, "jcl-statement", op)
    elif op:
        ctx.fact(st, "jcl-statement", op, recognised="no")
        ctx.scan.problems.append(ScanProblem(ctx.path, st.line, "JCL_UNKNOWN_STATEMENT", f"unrecognised JCL operation {op}"))


def _list(value: str) -> list[str]:
    value = value.strip()
    if value.startswith("(") and value.endswith(")"):
        value = value[1:-1]
    return [unquote(item) for item in split_top(value) if item]


def _exec(ctx: _Ctx, st: Statement) -> None:
    operands = parse_operands(st.operands)
    ctx.step = st.name.upper() or f"STEP{st.line}"
    ctx.step_ddnames = {}
    pgm, proc = operand(operands, "PGM"), operand(operands, "PROC")
    positional = next((v for k, v in operands if not k), "")
    overrides = {k: unquote(v) for k, v in operands if k and k not in ("PGM", "PROC", "PARM", "COND", "REGION", "TIME",
                                                                      "ACCT", "ADDRSPC", "DPRTY", "PERFORM", "RD", "DYNAMNBR",
                                                                      "CCSID", "MEMLIMIT", "TIME")}
    for key, value in overrides.items():
        ctx.symbols.setdefault(key, value)
    parm = unquote(operand(operands, "PARM")) if operand(operands, "PARM") else ""
    ctx.step_program = ""
    if pgm:
        program, missing = substitute(pgm, ctx.symbols)
        ctx.step_program = program.upper()
        ctx.step_is_proc = False
        dynamic = bool(missing)
        ctx.ref(st, "executes", "program", "" if dynamic else program.upper(), "EXEC PGM", dynamic=dynamic,
                variable=",".join(missing), detail=detail(parm=parm[:80], step=ctx.step))
        ctx.fact(st, "jcl-step", ctx.step, program=program.upper(), parm=parm[:80])
        _step_semantics(ctx, st, program.upper(), parm)
    else:
        name = proc or positional
        name, missing = substitute(name, ctx.symbols)
        ctx.step_is_proc = True
        ctx.ref(st, "executes", "proc", "" if missing else name.upper(), "EXEC PROC", dynamic=bool(missing),
                variable=",".join(missing), detail=detail(step=ctx.step, overrides=",".join(sorted(overrides))))
        ctx.fact(st, "jcl-step", ctx.step, procedure=name.upper(), parm=parm[:80])
        if _COMPILE_PROCS.match(name):
            ctx.fact(st, "compile-step", ctx.step, language="COBOL" if "YW" in name.upper() or "COB" in name.upper() else "",
                     procedure=name.upper())


def _step_semantics(ctx: _Ctx, st: Statement, program: str, parm: str) -> None:
    if program in _COBOL_COMPILERS:
        ctx.fact(st, "compile-step", ctx.step, language="COBOL", compiler=program, options=parm[:120])
    elif program in _LINKERS:
        ctx.fact(st, "link-step", ctx.step, linker=program, options=parm[:120])
    elif program == "DFSRRC00":
        values = ims_parameters(parm)
        region = values[0] if values else ""
        ctx.fact(st, "ims-region", ctx.step, region=region, program=values[1] if len(values) > 1 else "",
                 psb=values[2] if len(values) > 2 else "")
        if region in ("DLI", "DBB", "BMP", "MPP", "IFP") and len(values) > 1 and values[1]:
            ctx.ref(st, "executes", "program", values[1], "IMS region PARM", detail=detail(ims_region=region, via="DFSRRC00"))
        if len(values) > 2 and values[2]:
            ctx.ref(st, "uses-ims", "ims-psb", values[2], "IMS region PARM", detail=detail(ims_region=region))
    elif program in ("BPXBATCH", "IRXJCL", "FTP"):
        ctx.fact(st, "runtime-command", program, parm=parm[:120])


def _dd(ctx: _Ctx, st: Statement) -> None:
    operands = parse_operands(st.operands)
    name = st.name.upper()
    ddname = name.rsplit(".", 1)[-1]
    override_step = name.rsplit(".", 1)[0] if "." in name else ""
    if st.data:
        _instream(ctx, st, ddname)
        ctx.ref(st, "uses-dataset", "instream", "(in-stream data)", "DD *", detail=detail(dd=ddname, step=ctx.step))
    dsn_raw = operand(operands, "DSN") or operand(operands, "DSNAME")
    first = operands[0] if operands else ("", "")
    if not dsn_raw and "DUMMY" in (first[1].upper(), operand(operands, "")):
        ctx.fact(st, "dd-dummy", ddname)
        ctx.ref(st, "uses-dataset", "dummy", "DUMMY", "DD DUMMY", detail=detail(dd=ddname, step=ctx.step))
        return
    if override_step:
        ctx.fact(st, "dd-override", ddname, step=override_step)
    if operand(operands, "SYSOUT") or any(k == "SYSOUT" for k, _ in operands):
        ctx.fact(st, "dd-sysout", ddname)
        ctx.ref(st, "uses-dataset", "sysout", "SYSOUT", "DD SYSOUT", detail=detail(dd=ddname, step=ctx.step))
        return
    path_value = operand(operands, "PATH")
    if path_value:
        ctx.ref(st, "uses-dataset", "uss-path", unquote(path_value), "DD PATH", detail=detail(dd=ddname, step=ctx.step))
        return
    if not dsn_raw:
        if st.data:
            return
        ctx.fact(st, "dd-no-dsn", ddname, operands=st.operands[:60])
        return
    ctx.step_ddnames[ddname] = dsn_raw
    value, missing = substitute(unquote(dsn_raw), ctx.symbols)
    disp = operand(operands, "DISP")
    disp_first = _list(disp)[0].upper() if disp and _list(disp) else (disp.upper() or "SHR")
    if value.startswith("*."):
        ctx.fact(st, "dd-referback", ddname, to=value, step=ctx.step)
        return
    if value.startswith("&&"):
        ctx.fact(st, "temporary-dataset", value, dd=ddname, step=ctx.step)
        return
    member = ""
    match = re.match(r"^(.*)\(([^)]*)\)$", value)
    if match:
        value, member = match.group(1), match.group(2).upper()
    purpose = _LIBRARY_DDS.get(ddname, "")
    is_symbolic = bool(missing)
    info = detail(dd=ddname, step=ctx.step, override=override_step, disp=disp_first, member=member, purpose=purpose,
                  amp="vsam-hint" if operand(operands, "AMP") else "",
                  generation="gdg" if re.search(r"\(([+-]?\d+)\)$", dsn_raw) else "",
                  symbolic_original=unquote(dsn_raw) if unquote(dsn_raw) != value and not match else "")
    if purpose and purpose != "":
        relation = "uses-library"
    elif disp_first == "NEW":
        relation = "creates-dataset"
    else:
        relation = "uses-dataset"
    kind = "dataset"
    target = value.upper()
    if is_symbolic:
        ctx.ref(st, relation, kind, "", "DD DSN", dynamic=True, variable=",".join(missing), detail=info)
        return
    if not _DSN_RE.match(target) and not purpose:
        ctx.scan.problems.append(ScanProblem(ctx.path, st.line, "JCL_BAD_DSN", f"dataset name {target[:50]!r} is not valid"))
    ctx.ref(st, relation, kind, target, "DD DSN", detail=info)
    if member and ctx.step_program in _COBOL_COMPILERS | {""} and ddname == "SYSIN":
        ctx.ref(st, "builds", "source-member", member, "compile SYSIN", detail=detail(library=target, step=ctx.step))
    if ddname == "SYSLMOD" and member:
        ctx.fact(st, "load-module", member, library=target, step=ctx.step)


def _instream(ctx: _Ctx, st: Statement, ddname: str) -> None:
    program = ctx.step_program
    body = st.data
    ctx.fact(st, "dd-instream", ddname, lines=len(body), step=ctx.step, program=program)
    kind = _UTILITY_BODIES.get(program, "")
    if ddname == "SYSLIN" or program in _LINKERS:
        _link_control(ctx, st, body)
        return
    if not kind:
        return
    owner = ctx.owner
    if kind == "idcams":
        refs, facts = analyse_idcams(ctx.path, body, owner)
    elif kind == "sort":
        refs, facts = analyse_sort(ctx.path, body, owner, program)
    elif kind == "tso":
        refs, facts = analyse_tso(ctx.path, body, owner)
    elif kind == "db2-utility":
        refs, facts = analyse_db2_utility(ctx.path, body, owner)
    elif kind == "csd":
        refs, facts = analyse_cics_csd(ctx.path, body, owner)
    else:
        refs, facts = analyse_mq_utility(ctx.path, body, owner)
    ctx.scan.refs.extend(refs)
    ctx.scan.facts.extend(facts)


def _link_control(ctx: _Ctx, st: Statement, body: list[tuple[int, str]]) -> None:
    for number, text in body:
        match = re.match(r"\s*NAME\s+([A-Za-z0-9#@$]+)", text, re.IGNORECASE)
        if match:
            ctx.scan.facts.append(Fact(ctx.path, number, 1, "load-module", match.group(1).upper(), ctx.owner,
                                       detail(step=ctx.step, source="linkage-editor NAME")))
        include = re.match(r"\s*INCLUDE\s+\w+\(([^)]+)\)", text, re.IGNORECASE)
        if include:
            ctx.scan.refs.append(Ref(ctx.path, number, 1, "links", "object-member", include.group(1).upper(), ctx.owner,
                                     "linkage-editor INCLUDE"))


def is_system_program(name: str) -> bool:
    return name.upper() in SYSTEM_PROGRAMS
