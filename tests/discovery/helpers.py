"""Shared builders for the discovery tests: hostile ZIPs, directory trees and a representative COBOL estate."""

from __future__ import annotations

import json
import zipfile
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

FIXED_ZIP_TIME = (2020, 1, 2, 3, 4, 6)
REPO_ROOT = Path(__file__).resolve().parents[2]


def write_tree(root: Path, files: Mapping[str, str | bytes]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for relative, content in files.items():
        target = root / Path(*relative.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
    return root


def make_zip(path: Path, entries: Iterable[Any]) -> Path:
    """Entries are ``(name, data)`` or mappings with ``name``, ``raw_name``, ``data``, ``mode``, ``compress_type``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        for entry in entries:
            if isinstance(entry, Mapping):
                info = zipfile.ZipInfo(entry["name"], date_time=entry.get("date_time", FIXED_ZIP_TIME))
                info.external_attr = int(entry.get("mode", 0o100644)) << 16
                info.compress_type = entry.get("compress_type", zipfile.ZIP_DEFLATED)
                if entry.get("raw_name") is not None:
                    info.filename = entry["raw_name"]
                archive.writestr(info, entry.get("data", b""))
            else:
                info = zipfile.ZipInfo(entry[0], date_time=FIXED_ZIP_TIME)
                info.external_attr = 0o100644 << 16
                archive.writestr(info, entry[1])
    return path


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def codes_of(exc: BaseException) -> list[str]:
    out: list[str] = []
    for cls in type(exc).__mro__:
        code = cls.__dict__.get("code")
        if isinstance(code, str) and code not in out:
            out.append(code)
    code = getattr(exc, "code", None)
    if isinstance(code, str) and code not in out:
        out.append(code)
    return out


def expect_refusal(fn, *args: Any, **kwargs: Any) -> str:
    """Call ``fn``; assert it raised a typed refusal; return its code."""
    from enterprise.discovery.errors import IngestionError

    try:
        fn(*args, **kwargs)
    except IngestionError as exc:
        return str(exc.code)
    raise AssertionError(f"{getattr(fn, '__name__', fn)} accepted hostile input without raising an IngestionError")


def _fixed(*lines: str) -> str:
    """Fixed-format COBOL: statements start in column 8; a leading ``*`` makes a comment line."""
    return "\n".join(("      " + line if line.startswith("*") else "       " + line) if line else "" for line in lines) + "\n"


COBOL_ESTATE: dict[str, str] = {
    "README.md": "# Payroll estate\n",
    "src/cobol/PAYROLL.cbl": _fixed(
        "IDENTIFICATION DIVISION.",
        "PROGRAM-ID. PAYROLL.",
        "ENVIRONMENT DIVISION.",
        "INPUT-OUTPUT SECTION.",
        "FILE-CONTROL.",
        "    SELECT EMP-FILE ASSIGN TO EMPFILE",
        "        ORGANIZATION IS INDEXED ACCESS MODE IS DYNAMIC",
        "        RECORD KEY IS EMP-ID FILE STATUS IS WS-FS.",
        "    SELECT RPT-FILE ASSIGN TO UT-S-REPORT.",
        "DATA DIVISION.",
        "FILE SECTION.",
        "FD  EMP-FILE.",
        "    COPY EMPREC.",
        "WORKING-STORAGE SECTION.",
        "01  WS-TAX-PGM   PIC X(8) VALUE 'TAXCALC'.",
        "01  WS-FS        PIC XX.",
        "    EXEC SQL INCLUDE SQLCA END-EXEC.",
        "    EXEC SQL INCLUDE EMPDCL END-EXEC.",
        "PROCEDURE DIVISION.",
        "    CALL 'AUDITLOG' USING WS-FS.",
        "    CALL WS-TAX-PGM USING WS-FS.",
        "    CALL 'MISSING1' USING WS-FS.",
        "    EXEC SQL SELECT NAME INTO :N FROM HR.EMPLOYEE END-EXEC.",
        "    EXEC SQL UPDATE HR.PAYSTUB SET GROSS = 0 END-EXEC.",
        "    GOBACK.",
    ),
    "src/cobol/TAXCALC.cbl": _fixed(
        "IDENTIFICATION DIVISION.", "PROGRAM-ID. TAXCALC.", "PROCEDURE DIVISION.", "    GOBACK."),
    "src/cobol/AUDITLOG.cbl": _fixed(
        "IDENTIFICATION DIVISION.", "PROGRAM-ID. AUDITLOG.", "PROCEDURE DIVISION.",
        "    CALL 'CBLTDLI' USING FUNC-ISRT PCB-AUDIT IO-AREA.",
        "    CALL 'MQPUT' USING HCONN HOBJ MD PMO LEN BUF CC RC.",
        "    GOBACK."),
    "src/cobol/ORDERS.cbl": _fixed(
        "IDENTIFICATION DIVISION.", "PROGRAM-ID. ORDERS.", "PROCEDURE DIVISION.",
        "    EXEC CICS RECEIVE MAP('ORDMAP') MAPSET('ORDSET') END-EXEC.",
        "    EXEC CICS READ FILE('ORDFILE') INTO(WS-REC) RIDFLD(WS-KEY) END-EXEC.",
        "    EXEC CICS LINK PROGRAM('PAYROLL') END-EXEC.",
        "    EXEC CICS RETURN TRANSID('ORD1') END-EXEC."),
    "cpy/EMPREC.cpy": _fixed(
        "01  EMP-REC.", "    05  EMP-ID    PIC 9(6).", "    05  EMP-NAME  PIC X(30).",
        "    COPY AUDITCPY."),
    "cpy/AUDITCPY.cpy": _fixed("05  AUDIT-FLAG PIC X.", "05  AUDIT-DATE PIC 9(8)."),
    "cpy/EMPDCL.cpy": _fixed("01  DCLEMPLOYEE.", "    10 EMP-NO PIC S9(9) COMP."),
    "jcl/PAYJOB.jcl": (
        "//PAYJOB   JOB (ACCT),'PAYROLL',CLASS=A,MSGCLASS=X\n"
        "//JOBLIB   DD DSN=PROD.LOADLIB,DISP=SHR\n"
        "//STEP1    EXEC PGM=IDCAMS\n"
        "//SYSIN    DD *\n"
        "  DEFINE CLUSTER (NAME(PROD.EMP.KSDS) INDEXED KEYS(6 0) RECORDSIZE(40 40))\n"
        "/*\n"
        "//STEP2    EXEC PGM=PAYROLL\n"
        "//EMPFILE  DD DSN=PROD.EMP.KSDS,DISP=SHR\n"
        "//REPORT   DD SYSOUT=*\n"
        "//STEP3    EXEC PROC=NOPROC\n"
        "//STEP4    EXEC PGM=GHOSTPGM\n"),
    "jcl/proclib/SORTPROC.prc": (
        "//SORTPROC PROC\n"
        "//SORT     EXEC PGM=SORT\n"
        "//SYSIN    DD *\n"
        "  SORT FIELDS=(1,6,CH,A)\n"
        "/*\n"
        "//        PEND\n"),
    "db/schema.sql": (
        "CREATE TABLE HR.EMPLOYEE (EMP_NO INTEGER NOT NULL, NAME VARCHAR(30));\n"
        "CREATE INDEX HR.EMPIX ON HR.EMPLOYEE (EMP_NO);\n"),
    "bms/ORDSET.bms": (
        "ORDSET   DFHMSD TYPE=&SYSPARM,MODE=INOUT,LANG=COBOL\n"
        "ORDMAP   DFHMDI SIZE=(24,80)\n"
        "ORDNO    DFHMDF POS=(1,1),LENGTH=6\n"
        "         DFHMSD TYPE=FINAL\n"),
    "build/Makefile": (
        "all: payroll\n"
        "payroll: src/cobol/PAYROLL.cbl\n"
        "\tcobc -x -free -I cpy -o payroll src/cobol/PAYROLL.cbl\n"),
    "asm/ASMUTIL.asm": "ASMUTIL  CSECT\n         BR    14\n         END\n",
}


def write_cobol_estate(root: Path, extra: Mapping[str, str | bytes] | None = None) -> Path:
    files: dict[str, str | bytes] = dict(COBOL_ESTATE)
    files.update(extra or {})
    return write_tree(root, files)


write_enterprise_app = write_cobol_estate
