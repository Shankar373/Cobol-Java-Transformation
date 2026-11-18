"""Classify every file of an estate by extension, location and content, with the evidence for the decision.

Mainframe exports rarely keep extensions (members are named ``PAYROLL``), so content decides when the name does
not: the first meaningful line of a JCL member, an ``IDENTIFICATION DIVISION``, a ``DFHMSD`` macro.  Every file gets
a class; ``unknown`` is a class, never a reason to drop a file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath

__all__ = ["Classification", "classify", "SOURCE_CLASSES", "COBOL_FAMILY", "JCL_FAMILY", "TEXT_SCANNED"]

COBOL_FAMILY = frozenset({"cobol", "copybook"})
JCL_FAMILY = frozenset({"jcl-job", "jcl-proc"})
SOURCE_CLASSES = frozenset({"cobol", "copybook", "jcl-job", "jcl-proc", "bms", "sql", "idcams", "sort-control",
                            "assembler", "pli", "rexx", "clist"})
#: Classes whose content is read by a scanner.
TEXT_SCANNED = frozenset({"cobol", "copybook", "jcl-job", "jcl-proc", "bms", "sql", "idcams", "sort-control",
                          "build-config", "script", "ci-config", "assembler", "pli", "rexx", "clist", "config"})

_EXTENSIONS = {
    ".cbl": "cobol", ".cob": "cobol", ".cobol": "cobol", ".pco": "cobol", ".sqlcbl": "cobol", ".cblle": "cobol",
    ".cbl85": "cobol", ".ccp": "cobol", ".cics": "cobol", ".sqb": "cobol",
    ".cpy": "copybook", ".copy": "copybook", ".cbk": "copybook", ".cpb": "copybook", ".cpl": "copybook",
    ".jcl": "jcl-job", ".job": "jcl-job", ".proc": "jcl-proc", ".prc": "jcl-proc", ".jclproc": "jcl-proc",
    ".bms": "bms", ".sql": "sql", ".ddl": "sql", ".dcl": "sql", ".db2": "sql",
    ".idcams": "idcams", ".idc": "idcams", ".sort": "sort-control", ".ctl": "sort-control",
    ".asm": "assembler", ".mac": "assembler", ".assemble": "assembler", ".s": "assembler",
    ".pli": "pli", ".pl1": "pli", ".rexx": "rexx", ".rex": "rexx", ".clist": "clist",
    ".mk": "build-config", ".gradle": "build-config", ".mfproj": "build-config", ".cblproj": "build-config",
    ".sh": "script", ".bash": "script", ".bat": "script", ".cmd": "script", ".ps1": "script", ".ksh": "script",
    ".json": "config", ".xml": "config", ".properties": "config", ".cfg": "config", ".ini": "config", ".conf": "config",
    ".env": "config", ".toml": "config", ".yml": "config", ".yaml": "config", ".cfg2": "config",
    ".md": "doc", ".txt": "doc", ".rst": "doc", ".pdf": "doc", ".doc": "doc", ".docx": "doc", ".html": "doc",
    ".dat": "data", ".csv": "data", ".ebc": "data", ".dta": "data", ".idx": "data", ".vsam": "data", ".unl": "data",
    ".zip": "archive", ".gz": "archive", ".tgz": "archive", ".tar": "archive", ".7z": "archive", ".rar": "archive",
    ".exe": "binary", ".dll": "binary", ".so": "binary", ".o": "binary", ".obj": "binary", ".class": "binary",
    ".jar": "binary", ".png": "binary", ".jpg": "binary", ".gif": "binary", ".bin": "binary", ".lst2": "binary",
    ".lst": "listing", ".lis": "listing", ".out": "listing", ".log": "listing",
}
#: Extensions whose class is decided by the extension alone (never by content sniffing).
_DEFINITIVE_SUFFIXES = {".java": "java-source", ".py": "other-source", ".js": "other-source", ".ts": "other-source", ".tsx": "other-source",
                        ".kt": "other-source", ".go": "other-source", ".rs": "other-source", ".cs": "other-source", ".c": "other-source",
                        ".h": "other-source", ".cpp": "other-source", ".md": "doc", ".rst": "doc", ".pdf": "doc", ".html": "doc"}
_BUILD_NAMES = {"makefile": "build-config", "gnumakefile": "build-config", "pom.xml": "build-config",
                "build.xml": "build-config", "build.gradle": "build-config", "build.gradle.kts": "build-config",
                "settings.gradle": "build-config", "cmakelists.txt": "build-config", "jenkinsfile": "ci-config",
                ".gitlab-ci.yml": "ci-config", "azure-pipelines.yml": "ci-config", "dockerfile": "build-config",
                "docker-compose.yml": "build-config", "bitbucket-pipelines.yml": "ci-config", "appveyor.yml": "ci-config"}
_DIRECTORY_HINTS = (
    (("copylib", "copybook", "copybooks", "copy", "cpy", "copylibs", "includes"), "copybook"),
    (("proclib", "procs", "proc", "procedures", "jclproc"), "jcl-proc"),
    (("jcl", "jobs", "jcllib"), "jcl-job"),
    (("cobol", "cbl", "src", "source", "sources", "programs", "pgm", "batch", "online"), "cobol"),
    (("bms", "maps", "mapsets"), "bms"),
    (("ddl", "sql", "db2", "dbrm"), "sql"),
)
_COBOL_MARKERS = re.compile(r"\b(IDENTIFICATION|ID)\s+DIVISION\b|\bPROGRAM-ID\b", re.IGNORECASE)
_PROCEDURE = re.compile(r"\bPROCEDURE\s+DIVISION\b|\bENVIRONMENT\s+DIVISION\b|\bWORKING-STORAGE\s+SECTION\b", re.IGNORECASE)
_DATA_ITEM = re.compile(r"^\s*(?:\d{6})?\s{1,8}(?:\d{2})\s+[A-Za-z0-9-]+(?:\s+(?:PIC|PICTURE|REDEFINES|OCCURS|VALUE|USAGE|COMP)|\s*\.)",
                        re.IGNORECASE | re.MULTILINE)
_JCL_JOB = re.compile(r"^//\S*\s+JOB\b", re.MULTILINE)
_JCL_STMT = re.compile(r"^//\S*\s+(?:EXEC|DD|PROC|SET|IF|INCLUDE)\b", re.MULTILINE)
_DFHMSD = re.compile(r"\bDFHMSD\b")
_CREATE = re.compile(r"\bCREATE\s+(?:TABLE|INDEX|VIEW|TABLESPACE|DATABASE)\b", re.IGNORECASE)
_IDCAMS = re.compile(r"^\s*(?:DEFINE\s+(?:CLUSTER|AIX|GDG|PATH)|REPRO\s|LISTCAT\s|DELETE\s+\S+\s+(?:CLUSTER|PURGE))",
                     re.IGNORECASE | re.MULTILINE)
_SORT = re.compile(r"^\s*(?:SORT|MERGE)\s+FIELDS\s*=", re.IGNORECASE | re.MULTILINE)
_SHEBANG = re.compile(r"^#!\s*/")
_COBC = re.compile(r"\b(?:cobc|cob|cobol|mfcob|cobrun|ocesql|runcbl|cobol2)\b")


@dataclass(frozen=True)
class Classification:
    cls: str
    evidence: tuple[str, ...]


def _by_directory(path: PurePosixPath) -> str:
    parts = [part.lower() for part in path.parts[:-1]]
    for names, cls in _DIRECTORY_HINTS:
        if any(part in names for part in parts):
            return cls
    return ""


def classify(path: str, text: str | None, *, binary: bool = False, ci_hint: bool = False) -> Classification:
    """Classify ``path``; ``text`` is the decoded content (``None`` for binary or oversized files)."""
    pure = PurePosixPath(path)
    name = pure.name.lower()
    suffix = pure.suffix.lower()
    evidence: list[str] = []
    ext_cls = _EXTENSIONS.get(suffix, "")
    if name in _BUILD_NAMES:
        return Classification(_BUILD_NAMES[name], (f"file name {pure.name}",))
    if ".github/workflows/" in path.lower() and suffix in (".yml", ".yaml") or ci_hint:
        return Classification("ci-config", ("CI workflow location",))
    if binary:
        cls = ext_cls if ext_cls in ("binary", "archive", "data") else "binary"
        return Classification(cls, ("binary content" + (f", extension {suffix}" if suffix else ""),))
    if ext_cls in ("binary", "archive"):
        return Classification(ext_cls, (f"extension {suffix}",))
    if suffix in _DEFINITIVE_SUFFIXES:
        # A Java, Python or Markdown file that merely *mentions* PROGRAM-ID or a JCL card is not a mainframe source member.
        return Classification(ext_cls or _DEFINITIVE_SUFFIXES[suffix], (f"extension {suffix}",))
    sniffed = _sniff(text or "")
    if sniffed:
        cls, why = sniffed
        if ext_cls and ext_cls != cls and ext_cls in SOURCE_CLASSES | {"build-config", "script"}:
            # An extension that says COBOL but content that says copybook (or vice versa) is settled by content.
            evidence.append(f"extension {suffix} suggests {ext_cls}")
        evidence.append(why)
        return Classification(cls, tuple(evidence))
    if ext_cls:
        evidence.append(f"extension {suffix}")
        if ext_cls == "script" and text and _COBC.search(text):
            evidence.append("invokes a COBOL compiler")
        if ext_cls == "config" and text and _COBC.search(text):
            evidence.append("mentions a COBOL tool")
        return Classification(ext_cls, tuple(evidence))
    hinted = _by_directory(pure)
    if hinted and text:
        return Classification("unknown", (f"directory suggests {hinted} but content does not match",))
    if not suffix and text is not None and not text.strip():
        return Classification("unknown", ("empty file",))
    return Classification("unknown", ("no recognised extension or content",))


def _sniff(text: str) -> tuple[str, str] | None:
    head = text[:200_000]
    if _JCL_JOB.search(head):
        return "jcl-job", "contains a JOB statement"
    if head.lstrip().startswith("//") and _JCL_STMT.search(head):
        return "jcl-proc", "JCL statements without a JOB card (procedure or include member)"
    if _DFHMSD.search(head):
        return "bms", "contains DFHMSD macros"
    if _COBOL_MARKERS.search(head):
        return "cobol", "contains IDENTIFICATION DIVISION / PROGRAM-ID"
    if _PROCEDURE.search(head) and re.search(r"\bPROCEDURE\s+DIVISION\b", head, re.IGNORECASE):
        return "cobol", "contains PROCEDURE DIVISION"
    if _CREATE.search(head):
        return "sql", "contains CREATE TABLE/INDEX/VIEW"
    if _IDCAMS.search(head):
        return "idcams", "contains IDCAMS control statements"
    if _SORT.search(head):
        return "sort-control", "contains SORT FIELDS control statements"
    lines = [line for line in head.splitlines() if line.strip()]
    if lines and not _SHEBANG.match(lines[0]):
        items = len(_DATA_ITEM.findall(head))
        if items >= 2 and items >= 0.5 * len([ln for ln in lines if not _is_comment(ln)]):
            return "copybook", "COBOL data descriptions without divisions"
    return None


def _is_comment(line: str) -> bool:
    return (len(line) > 6 and line[6] in "*/") or line.lstrip().startswith(("*>", "*"))
