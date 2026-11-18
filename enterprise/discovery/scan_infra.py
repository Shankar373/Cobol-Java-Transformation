"""Scanners for the non-COBOL, non-JCL artefacts of an estate: BMS maps, SQL DDL, build and runtime configuration,
and the other legacy languages a COBOL program may call (assembler, PL/I, REXX, CLIST).

Build and runtime scripts are read line by line for compiler invocations (``cobc``, ``mfcob``, ``ocesql``, ``mvn``,
...), copybook/library search paths, ``COB_*`` environment settings and declared Java dependencies.  Nothing is run.
"""

from __future__ import annotations

import re
import shlex

from .findings import Fact, FileScan, Ref, ScanProblem, detail

__all__ = ["scan_bms", "scan_sql", "scan_build", "scan_other_language"]

_COBOL_SOURCE = re.compile(r"[\w./\\${}()-]+\.(?:cbl|cob|cobol|pco|sqlcbl|cpy)\b", re.IGNORECASE)
_TOOLS = ("cobc", "cob", "mfcob", "cobol", "cobrun", "runcbl", "ocesql", "esql", "dbpre", "cicsprep", "dfhcob", "mvn",
          "gradle", "gradlew", "ant", "javac", "java", "make", "docker", "db2", "ocdb2", "isql", "psql", "cobcrun")
_ENV = re.compile(r"^\s*(?:export\s+|set\s+|ENV\s+|\$env:)?((?:COB[A-Z_]*|COBPATH|COBCPY|COBDIR|DD_[A-Za-z0-9_]+|"
                  r"dd_[A-Za-z0-9_]+|DB2[A-Z_]*|PGHOST|PGDATABASE|PGPORT|JAVA_HOME|CLASSPATH|SPRING_[A-Z_]+))\s*[=:]\s*(.+?)\s*$")


def _line_col(text: str, offset: int) -> tuple[int, int]:
    line = text.count("\n", 0, offset) + 1
    return line, offset - (text.rfind("\n", 0, offset) + 1) + 1


# --- BMS -----------------------------------------------------------------------------------------------------------

_BMS_LINE = re.compile(r"^([A-Za-z#@$][A-Za-z0-9#@$]*)?\s+(DFHMSD|DFHMDI|DFHMDF)\b(.*)$", re.IGNORECASE)


def scan_bms(path: str, text: str) -> FileScan:
    scan = FileScan(path=path, line_count=text.count("\n") + 1)
    mapset, current, fields = "", "", 0
    for number, raw in enumerate(text.splitlines(), start=1):
        if raw.startswith("*"):
            continue
        match = _BMS_LINE.match(raw.rstrip()[:71])
        if not match:
            continue
        label, macro, args = (match.group(1) or "").upper(), match.group(2).upper(), match.group(3)
        if macro == "DFHMSD":
            if "TYPE=FINAL" in args.upper().replace(" ", ""):
                continue
            mapset = label or mapset
            scan.facts.append(Fact(path, number, 1, "bms-mapset", mapset, f"file:{path}",
                                   detail(mode=_arg(args, "MODE"), language=_arg(args, "LANG"), ctrl=_arg(args, "CTRL"))))
        elif macro == "DFHMDI":
            current = label
            scan.facts.append(Fact(path, number, 1, "bms-map", f"{mapset}.{label}" if mapset else label, f"file:{path}",
                                   detail(size=_arg(args, "SIZE"), mapset=mapset)))
            scan.refs.append(Ref(path, number, 1, "defines-resource", "bms-map", label, f"bms-mapset:{mapset}",
                                 "DFHMDI", detail=detail(mapset=mapset)))
        elif macro == "DFHMDF":
            fields += 1
            if label:
                scan.facts.append(Fact(path, number, 1, "bms-field", label, f"bms-map:{current}",
                                       detail(position=_arg(args, "POS"), length=_arg(args, "LENGTH"))))
    if mapset:
        scan.refs.append(Ref(path, 1, 1, "defines-resource", "bms-mapset", mapset, f"file:{path}", "DFHMSD",
                             detail=detail(fields=fields)))
    else:
        scan.problems.append(ScanProblem(path, 1, "BMS_NO_MAPSET", "no DFHMSD mapset definition was found"))
    return scan.sorted()


def _arg(args: str, key: str) -> str:
    match = re.search(rf"{key}\s*=\s*(\([^)]*\)|[^,\s]+)", args, re.IGNORECASE)
    return match.group(1).upper() if match else ""


# --- SQL DDL ---------------------------------------------------------------------------------------------------------

_STRIP = re.compile(r"--[^\n]*|/\*.*?\*/", re.DOTALL)
_CREATE = re.compile(r"\bCREATE\s+(?:UNIQUE\s+)?(?:GLOBAL\s+TEMPORARY\s+)?(TABLE|INDEX|VIEW|TABLESPACE|DATABASE|SEQUENCE|"
                     r"PROCEDURE|FUNCTION|TRIGGER|ALIAS|SYNONYM)\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z0-9_$#@.\"]+)", re.IGNORECASE)
_ON = re.compile(r"\bON\s+([A-Za-z0-9_$#@.\"]+)", re.IGNORECASE)
_FROM = re.compile(r"\b(?:FROM|JOIN)\s+([A-Za-z0-9_$#@.\"]+)", re.IGNORECASE)
_ALTER = re.compile(r"\bALTER\s+TABLE\s+([A-Za-z0-9_$#@.\"]+)", re.IGNORECASE)
_REFERENCES = re.compile(r"\bREFERENCES\s+([A-Za-z0-9_$#@.\"]+)", re.IGNORECASE)


def _blank_comments(text: str) -> str:
    return _STRIP.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)


def scan_sql(path: str, text: str) -> FileScan:
    scan = FileScan(path=path, line_count=text.count("\n") + 1)
    clean = _blank_comments(text)
    owner = f"file:{path}"
    matches = list(_CREATE.finditer(clean))
    for index, match in enumerate(matches):
        kind, name = match.group(1).upper(), match.group(2).strip('"').upper()
        line, col = _line_col(clean, match.start())
        end = matches[index + 1].start() if index + 1 < len(matches) else len(clean)
        body = clean[match.end():end]
        scan.facts.append(Fact(path, line, col, "sql-definition", f"{kind} {name}", owner, detail(kind=kind)))
        if kind == "TABLE":
            scan.refs.append(Ref(path, line, col, "defines-table", "table", name, owner, "CREATE TABLE"))
            for ref in _REFERENCES.finditer(body):
                scan.refs.append(Ref(path, *_line_col(clean, match.end() + ref.start()), "accesses-table", "table",
                                     ref.group(1).strip('"').upper(), owner, "FOREIGN KEY REFERENCES",
                                     detail=detail(operation="REFERENCES")))
        elif kind == "INDEX":
            on = _ON.search(body)
            if on:
                scan.refs.append(Ref(path, line, col, "accesses-table", "table", on.group(1).strip('"').upper(), owner,
                                     "CREATE INDEX ON", detail=detail(operation="INDEX", index=name)))
        elif kind == "VIEW":
            for source in _FROM.finditer(body):
                scan.refs.append(Ref(path, *_line_col(clean, match.end() + source.start()), "accesses-table", "table",
                                     source.group(1).strip('"').upper(), owner, "CREATE VIEW FROM",
                                     detail=detail(operation="VIEW", view=name)))
    for alter in _ALTER.finditer(clean):
        scan.refs.append(Ref(path, *_line_col(clean, alter.start()), "accesses-table", "table",
                             alter.group(1).strip('"').upper(), owner, "ALTER TABLE", detail=detail(operation="ALTER")))
    if not matches and not _ALTER.search(clean):
        scan.facts.append(Fact(path, 1, 1, "sql-script", path.rsplit("/", 1)[-1], owner, detail(definitions=0)))
    return scan.sorted()


# --- build / runtime configuration ---------------------------------------------------------------------------------

_MAKE_TARGET = re.compile(r"^([A-Za-z0-9_./${}()-]+)\s*:(?!=)\s*(.*)$")
_DEP_TAG = re.compile(r"<(groupId|artifactId|version)>\s*([^<]+?)\s*</\1>")
_GRADLE_DEP = re.compile(r"^\s*(?:implementation|api|compileOnly|runtimeOnly|testImplementation)\s*[(\s]['\"]([^'\"]+)['\"]")


def scan_build(path: str, text: str) -> FileScan:
    scan = FileScan(path=path, line_count=text.count("\n") + 1)
    owner = f"file:{path}"
    name = path.rsplit("/", 1)[-1].lower()
    if name == "pom.xml" or name.endswith(".pom"):
        _pom(scan, path, text, owner)
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith(("#", "//", "REM ", "rem ", "::", "<!--")):
            continue
        gradle = _GRADLE_DEP.match(raw)
        if gradle:
            scan.facts.append(Fact(path, number, 1, "java-dependency", gradle.group(1), owner, detail(source="gradle")))
        env = _ENV.match(raw)
        if env:
            _environment(scan, path, number, env.group(1), env.group(2).strip().strip("'\""), owner)
        target = _MAKE_TARGET.match(line) if name in ("makefile", "gnumakefile") or name.endswith(".mk") else None
        if target and not line.startswith(("\t", "export", "ifeq", ".")):
            deps = target.group(2).split()
            scan.facts.append(Fact(path, number, 1, "build-target", target.group(1), owner, detail(dependencies=len(deps))))
            for dep in deps:
                if _COBOL_SOURCE.fullmatch(dep):
                    scan.refs.append(Ref(path, number, 1, "builds", "source-file", dep, owner, f"make target {target.group(1)}"))
        _invocation(scan, path, number, line, owner)
    return scan.sorted()


def _environment(scan: FileScan, path: str, number: int, key: str, value: str, owner: str) -> None:
    scan.facts.append(Fact(path, number, 1, "runtime-setting", key, owner, detail(value=value[:120])))
    if key in ("COBPATH", "COBCPY", "COB_LIBRARY_PATH", "COB_COPY_DIR", "COBDIR", "CLASSPATH"):
        for item in _split_path_list(value):
            if item.strip():
                scan.refs.append(Ref(path, number, 1, "uses-library", "directory", item.strip(), owner, f"env {key}",
                                     detail=detail(purpose="copybook-path" if key in ("COBCPY", "COB_COPY_DIR") else "library-path")))
    if key.upper().startswith("DD_"):
        scan.refs.append(Ref(path, number, 1, "binds-ddname", "dd", key[3:].upper(), owner, f"env {key}",
                             detail=detail(path=value[:120])))


def _split_path_list(value: str) -> list[str]:
    """Split a ``;`` or ``:`` separated path list, keeping a leading Windows drive letter (``C:\\x``) intact."""
    if ";" in value:
        return value.split(";")
    parts: list[str] = []
    for part in value.split(":"):
        if len(parts) == 1 and len(parts[0]) == 1 and parts[0].isalpha() and part[:1] in ("\\", "/"):
            parts[0] += ":" + part
        else:
            parts.append(part)
    return parts


def _invocation(scan: FileScan, path: str, number: int, line: str, owner: str) -> None:
    try:
        words = shlex.split(line, comments=True, posix=False)
    except ValueError:
        words = line.split()
    for index, word in enumerate(words):
        tool = word.strip('"\'').replace("\\", "/").rsplit("/", 1)[-1].lower().removesuffix(".exe").removesuffix(".cmd")
        if tool not in _TOOLS:
            continue
        args = [w.strip('"\'') for w in words[index + 1:]]
        flags = sorted({a for a in args if a.startswith("-") and not a.startswith("-I") and len(a) < 40})
        scan.facts.append(Fact(path, number, 1, "build-invocation", tool, owner,
                               detail(flags=" ".join(flags)[:120], format="free" if "-free" in args else
                                      ("fixed" if "-fixed" in args else ""),
                                      standard=next((a for a in args if a.startswith("-std=")), ""),
                                      output=_after(args, "-o"))))
        include_position = 0
        for position, arg in enumerate(args):
            if arg.startswith("-I") and len(arg) > 2:
                include_position += 1
                scan.refs.append(Ref(path, number, 1, "uses-library", "directory", arg[2:], owner, f"{tool} -I",
                                     detail=detail(purpose="copybook-path", position=str(include_position))))
            elif arg == "-I" and position + 1 < len(args):
                include_position += 1
                scan.refs.append(Ref(path, number, 1, "uses-library", "directory", args[position + 1], owner, f"{tool} -I",
                                     detail=detail(purpose="copybook-path", position=str(include_position))))
            elif _COBOL_SOURCE.fullmatch(arg):
                scan.refs.append(Ref(path, number, 1, "builds", "source-file", arg.replace("\\", "/"), owner,
                                     f"{tool} source", detail=detail(tool=tool)))
        return


def _after(args: list[str], flag: str) -> str:
    return args[args.index(flag) + 1] if flag in args and args.index(flag) + 1 < len(args) else ""


def _pom(scan: FileScan, path: str, text: str, owner: str) -> None:
    for block in re.finditer(r"<dependency>(.*?)</dependency>", text, re.DOTALL):
        values = {tag: value for tag, value in _DEP_TAG.findall(block.group(1))}
        if "artifactId" in values:
            line, col = _line_col(text, block.start())
            name = f"{values.get('groupId', '')}:{values['artifactId']}" + (f":{values['version']}" if "version" in values else "")
            scan.facts.append(Fact(path, line, col, "java-dependency", name, owner, detail(source="maven")))


# --- other legacy languages ------------------------------------------------------------------------------------------

_CSECT = re.compile(r"^([A-Za-z#@$][A-Za-z0-9#@$]*)\s+(?:CSECT|START)\b", re.MULTILINE | re.IGNORECASE)
_PLI_PROC = re.compile(r"^\s*([A-Za-z#@$][A-Za-z0-9#@$_]*)\s*:\s*(?:PROC|PROCEDURE)\b[^;]*", re.MULTILINE | re.IGNORECASE)


def scan_other_language(path: str, text: str, language: str) -> FileScan:
    """Entry names of an assembler/PL-I/REXX/CLIST member so a COBOL ``CALL`` or JCL ``EXEC`` can resolve to it."""
    scan = FileScan(path=path, line_count=text.count("\n") + 1)
    stem = path.rsplit("/", 1)[-1].rsplit(".", 1)[0].upper()
    owner = f"file:{path}"
    names: list[tuple[str, int]] = []
    if language == "assembler":
        names = [(m.group(1).upper(), _line_col(text, m.start())[0]) for m in _CSECT.finditer(text)]
    elif language == "pli":
        names = [(m.group(1).upper(), _line_col(text, m.start())[0]) for m in _PLI_PROC.finditer(text)
                 if "MAIN" in m.group(0).upper() or not names][:5]
    names = names or [(stem, 1)]
    for name, line in names:
        scan.facts.append(Fact(path, line, 1, "program-id", name, owner, detail(kind=f"{language}-entry", language=language)))
    if stem not in {n for n, _ in names}:
        scan.facts.append(Fact(path, 1, 1, "program-id", stem, owner, detail(kind=f"{language}-member", language=language)))
    for match in re.finditer(r"\bCALL\s+['\"]?([A-Za-z#@$][A-Za-z0-9#@$_]*)", text, re.IGNORECASE):
        if language in ("pli", "rexx", "clist"):
            scan.refs.append(Ref(path, *_line_col(text, match.start()), "calls", "program", match.group(1).upper(), owner,
                                 "CALL", detail=detail(language=language)))
    return scan.sorted()
