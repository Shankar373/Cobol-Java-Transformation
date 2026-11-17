"""Control statements inside JCL ``SYSIN``/``SYSTSIN`` data: IDCAMS (VSAM), SORT/ICETOOL, TSO/DB2, IMS and MQ.

Each analyser receives the in-stream body as ``[(line, text)]`` and returns refs and facts anchored at the line the
statement was written on.  Nothing is executed; an unrecognised control statement is recorded, not ignored.
"""

from __future__ import annotations

import re

from .findings import Fact, Ref, detail

SYSTEM_PROGRAMS = frozenset({
    "IEFBR14", "IEBGENER", "IEBCOPY", "IEBCOMPR", "IEBUPDTE", "IEBPTPCH", "IEHLIST", "IEHPROGM", "IEHMOVE", "IDCAMS",
    "SORT", "ICEMAN", "ICETOOL", "ICEGENER", "SYNCSORT", "IKJEFT01", "IKJEFT1A", "IKJEFT1B", "DFSRRC00", "DSNUTILB",
    "DSNTEP2", "DSNTEP4", "DSNTIAD", "DSNTIAUL", "IEWL", "HEWL", "IEWBLINK", "HEWLH096", "IGYCRCTL", "ELAXF", "ASMA90",
    "IEV90", "ADRDSSU", "FTP", "DFHCSDUP", "CSQUTIL", "CSQBBATCH", "CSQBDEFV", "BPXBATCH", "IRXJCL", "IEFBR15",
    "AMASPZAP", "IFASMFDP", "DFSORT", "DFHMAPS", "DFHEAP1$", "DFHECP1$", "DFHEXP1$", "DSNHPC", "DSNHPC7", "IGYCRCTL",
    "IGZCBSN", "IGZCBSO", "IEBDG", "ISRSUPC", "SDSF", "EDCCOMP", "CCNDRVR", "IEFIIC", "GIMSMP", "AMBLIST",
})
IDCAMS_TYPES = {"INDEXED": "KSDS", "NONINDEXED": "ESDS", "NUMBERED": "RRDS", "LINEAR": "LDS", "RRDS": "RRDS"}
_COMMENT = re.compile(r"/\*.*?\*/")


def _joined(body: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Statements of a control body: strips ``/* */`` comments and folds ``-``/``+`` continuation lines."""
    out: list[tuple[int, str]] = []
    pending: tuple[int, str] | None = None
    for number, text in body:
        if len(text) >= 80 and text[72:80].strip().isdigit():
            text = text[:72]  # card image: columns 73-80 are a sequence number
        text = _COMMENT.sub(" ", text).rstrip()
        if not text.strip():
            continue
        if pending:
            number, text = pending[0], pending[1] + " " + text.strip()
            pending = None
        if text.endswith(("-", "+")) and not text.endswith("--"):
            pending = (number, text[:-1].rstrip())
            continue
        out.append((number, text.strip()))
    if pending:
        out.append(pending)
    return out


def _paren(text: str, key: str) -> str:
    match = re.search(rf"\b{key}\s*\(\s*([^()]*(?:\([^()]*\)[^()]*)*)\)", text, re.IGNORECASE)
    return match.group(1).strip().strip("'\"") if match else ""


def _names(text: str, key: str) -> list[str]:
    value = _paren(text, key)
    return [item.strip().strip("'\"").upper() for item in re.split(r"[,\s]+", value) if item.strip()] if value else []


def analyse_idcams(path: str, body: list[tuple[int, str]], owner: str) -> tuple[list[Ref], list[Fact]]:
    refs: list[Ref] = []
    facts: list[Fact] = []
    for number, text in _joined(body):
        upper = text.upper()
        command = upper.split(None, 2)
        verb = " ".join(command[:2]) if command and command[0] == "DEFINE" and len(command) > 1 else \
            (command[0] if command else "")
        if verb.startswith("DEFINE"):
            kind = command[1].split("(")[0] if len(command) > 1 else ""
            name = _paren(upper, "NAME")
            if not name:
                continue
            if kind == "CLUSTER":
                organization = next((v for k, v in IDCAMS_TYPES.items() if re.search(rf"\b{k}\b", upper)), "KSDS")
                keys = _paren(upper, "KEYS")
                size = _paren(upper, "RECORDSIZE") or _paren(upper, "RECORDSIZE ")
                facts.append(Fact(path, number, 1, "vsam-cluster", name, owner,
                                  detail(organization=organization, keys=" ".join(keys.split()),
                                         record_size=" ".join(size.split()), defined_by="IDCAMS DEFINE CLUSTER")))
                refs.append(Ref(path, number, 1, "defines-dataset", "vsam-cluster", name, owner, "IDCAMS DEFINE CLUSTER",
                                detail=detail(organization=organization)))
                for component in ("DATA", "INDEX"):
                    sub = re.search(rf"\b{component}\s*\(\s*NAME\s*\(\s*([^)\s]+)", upper)
                    if sub:
                        facts.append(Fact(path, number, 1, "vsam-component", sub.group(1).strip("'"), owner,
                                          detail(cluster=name, component=component)))
            elif kind == "AIX":
                relate = _paren(upper, "RELATE")
                facts.append(Fact(path, number, 1, "vsam-aix", name, owner, detail(base=relate, keys=_paren(upper, "KEYS"))))
                refs.append(Ref(path, number, 1, "defines-dataset", "vsam-cluster", name, owner, "IDCAMS DEFINE AIX",
                                detail=detail(base=relate, organization="AIX")))
            elif kind == "PATH":
                facts.append(Fact(path, number, 1, "vsam-path", name, owner, detail(entry=_paren(upper, "PATHENTRY"))))
            elif kind in ("GDG", "GENERATIONDATAGROUP"):
                facts.append(Fact(path, number, 1, "gdg-base", name, owner, detail(limit=_paren(upper, "LIMIT"))))
                refs.append(Ref(path, number, 1, "defines-dataset", "dataset", name, owner, "IDCAMS DEFINE GDG"))
            else:
                facts.append(Fact(path, number, 1, "idcams-command", f"DEFINE {kind}", owner, detail(name=name)))
        elif verb in ("REPRO", "PRINT", "VERIFY", "EXPORT", "IMPORT"):
            for key, direction in (("INFILE", "read"), ("INDATASET", "read"), ("IFILE", "read"), ("OUTFILE", "write"),
                                   ("OUTDATASET", "write"), ("OFILE", "write"), ("DATASET", "read")):
                value = _paren(upper, key)
                if value:
                    is_dd = key.endswith("FILE")
                    refs.append(Ref(path, number, 1, "binds-ddname" if is_dd else "uses-dataset",
                                    "dd" if is_dd else "dataset", value, owner, f"IDCAMS {verb} {key}",
                                    detail=detail(direction=direction)))
            facts.append(Fact(path, number, 1, "idcams-command", verb, owner))
        elif verb in ("DELETE", "LISTCAT", "ALTER", "SET", "IF", "ELSE", "END", "CHECK"):
            target = command[1].split("(")[0] if len(command) > 1 else ""
            facts.append(Fact(path, number, 1, "idcams-command", verb, owner, detail(target=target.strip("'\"")[:60])))
        else:
            facts.append(Fact(path, number, 1, "idcams-command", verb or "(blank)", owner, detail(recognised="no")))
    return refs, facts


_SORT_KEYWORDS = ("SORT", "MERGE", "INCLUDE", "OMIT", "INREC", "OUTREC", "OUTFIL", "SUM", "OPTION", "RECORD", "MODS",
                  "COPY", "COUNT", "SELECT", "OCCUR", "DISPLAY", "UNIQUE", "RANGE", "SPLICE", "STATS", "SORTDD")


def analyse_sort(path: str, body: list[tuple[int, str]], owner: str, program: str) -> tuple[list[Ref], list[Fact]]:
    refs: list[Ref] = []
    facts: list[Fact] = []
    for number, text in _joined(body):
        word = text.split(None, 1)[0].upper().rstrip("=") if text.split() else ""
        keyword = next((k for k in _SORT_KEYWORDS if word == k or word.startswith(k)), "")
        facts.append(Fact(path, number, 1, "sort-control", keyword or word[:20], owner,
                          detail(utility=program, text=" ".join(text.split())[:80], recognised="yes" if keyword else "no")))
        for key in ("FROM", "TO", "USING", "FNAMES", "SAVE"):
            for value in _names(text.upper(), key):
                refs.append(Ref(path, number, 1, "binds-ddname", "dd", value, owner, f"{program} {key}",
                                detail=detail(utility=program)))
    return refs, facts


def analyse_tso(path: str, body: list[tuple[int, str]], owner: str) -> tuple[list[Ref], list[Fact]]:
    refs: list[Ref] = []
    facts: list[Fact] = []
    for number, text in _joined(body):
        upper = text.upper()
        head = upper.split(None, 1)[0] if upper.split() else ""
        if head == "DSN":
            system = _paren(upper, "SYSTEM")
            if system:
                refs.append(Ref(path, number, 1, "uses-db2", "db2-subsystem", system, owner, "TSO DSN SYSTEM"))
        elif head == "RUN":
            program, plan = _paren(upper, "PROGRAM"), _paren(upper, "PLAN")
            library = _paren(text, "LIB")
            if program:
                refs.append(Ref(path, number, 1, "executes", "program", program, owner, "TSO DSN RUN PROGRAM",
                                detail=detail(plan=plan, library=library, via="DSN")))
            if plan:
                refs.append(Ref(path, number, 1, "uses-db2", "db2-plan", plan, owner, "TSO DSN RUN PLAN"))
        elif head == "BIND":
            facts.append(Fact(path, number, 1, "db2-bind", " ".join(upper.split()[:2]), owner,
                              detail(plan=_paren(upper, "PLAN"), package=_paren(upper, "PACKAGE"))))
            for member in _names(upper, "MEMBER"):
                refs.append(Ref(path, number, 1, "binds", "dbrm", member, owner, "DB2 BIND MEMBER"))
            for plan in _names(upper, "PLAN"):
                refs.append(Ref(path, number, 1, "uses-db2", "db2-plan", plan, owner, "DB2 BIND PLAN"))
        elif head in ("END", "SUBCOM", "FREE", "REBIND", "DSNH", "CALL", "EX", "EXEC", "ALLOC", "ALLOCATE"):
            facts.append(Fact(path, number, 1, "tso-command", head, owner))
        else:
            facts.append(Fact(path, number, 1, "tso-command", head or "(blank)", owner, detail(recognised="no")))
    return refs, facts


def analyse_db2_utility(path: str, body: list[tuple[int, str]], owner: str) -> tuple[list[Ref], list[Fact]]:
    refs: list[Ref] = []
    facts: list[Fact] = []
    for number, text in _joined(body):
        upper = text.upper()
        facts.append(Fact(path, number, 1, "db2-utility", upper.split(None, 1)[0][:20] if upper.split() else "", owner))
        for match in re.finditer(r"\b(?:INTO\s+TABLE|TABLESPACE|FROM\s+TABLE)\s+([A-Z0-9_$#@.]+)", upper):
            refs.append(Ref(path, number, 1, "accesses-table", "table", match.group(1), owner, "DB2 utility",
                            detail=detail(operation="UTILITY")))
    return refs, facts


def analyse_cics_csd(path: str, body: list[tuple[int, str]], owner: str) -> tuple[list[Ref], list[Fact]]:
    refs: list[Ref] = []
    facts: list[Fact] = []
    for number, text in _joined(body):
        upper = text.upper()
        match = re.match(r"\s*(DEFINE|ALTER)\s+(PROGRAM|TRANSACTION|FILE|MAPSET|TDQUEUE|TSMODEL)\s*\(\s*([^)\s]+)", upper)
        if not match:
            continue
        kind = {"PROGRAM": "program", "TRANSACTION": "transaction", "FILE": "cics-file", "MAPSET": "bms-mapset",
                "TDQUEUE": "cics-queue", "TSMODEL": "cics-queue"}[match.group(2)]
        facts.append(Fact(path, number, 1, "cics-resource-definition", f"{match.group(2)} {match.group(3)}", owner,
                          detail(group=_paren(upper, "GROUP"), program=_paren(upper, "PROGRAM"))))
        refs.append(Ref(path, number, 1, "defines-resource", kind, match.group(3), owner, f"DFHCSDUP {match.group(1)}"))
        program = _paren(upper, "PROGRAM") if match.group(2) == "TRANSACTION" else ""
        if program:
            refs.append(Ref(path, number, 1, "executes", "program", program, owner, "CICS TRANSACTION PROGRAM"))
    return refs, facts


def analyse_mq_utility(path: str, body: list[tuple[int, str]], owner: str) -> tuple[list[Ref], list[Fact]]:
    refs: list[Ref] = []
    facts: list[Fact] = []
    for number, text in _joined(body):
        upper = text.upper()
        match = re.match(r"\s*(DEFINE|ALTER|DELETE)\s+(QLOCAL|QREMOTE|QALIAS|QMODEL|CHANNEL|PROCESS|NAMELIST)\s*\(\s*['\"]?([^'\")\s]+)",
                         upper)
        if match:
            kind = "mq-queue" if match.group(2).startswith("Q") else "mq-object"
            facts.append(Fact(path, number, 1, "mq-definition", f"{match.group(2)} {match.group(3)}", owner))
            refs.append(Ref(path, number, 1, "defines-queue" if kind == "mq-queue" else "defines-resource", kind,
                            match.group(3), owner, f"MQSC {match.group(1)} {match.group(2)}"))
    return refs, facts


def ims_parameters(parm: str) -> list[str]:
    """Positional values of a DFSRRC00 ``PARM`` (``DLI,PROG,PSB,...`` possibly parenthesised or quoted)."""
    text = parm.strip().strip("()").strip("'")
    return [item.strip().upper() for item in text.split(",")]
