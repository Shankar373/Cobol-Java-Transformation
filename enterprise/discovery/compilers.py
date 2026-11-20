"""Compiler and toolchain discovery: what the estate needs, what open-source tooling is available, and what it can check.

Three separate questions, never conflated:

1. **Required toolchains** (``toolchain_requirements``): derived from the estate itself (``CBL``/``PROCESS`` cards, ``$SET``,
   ``cobc`` invocations and flags, JCL compile and link steps, dialect signals).  Pure function of the scan findings.
2. **Available tools** (``probe_toolchain``): which *open-source* tools this host can run (GnuCOBOL ``cobc``, the GCC COBOL front end
   ``gcobol``, ``ocesql``, a JDK, Maven) and their versions, found locally or in the project's GnuCOBOL container image.  Nothing
   proprietary is looked for, installed or called.
3. **Compatibility** (``assess_compatibility``): a syntax-only GnuCOBOL check (``cobc -fsyntax-only``, nothing is built or run) of every
   COBOL program that open-source tooling can legitimately check, with compiler diagnostics mapped back to ``file:line``.  Programs that
   need a proprietary translator or runtime (``EXEC CICS``, ``EXEC DLI``, IBM MQ, Language Environment, ...) are *not attempted* and are
   reported by name with the reason; they never stop the rest of discovery.

A missing compiler is a recorded limitation (``NOT_ATTEMPTED_NO_COMPILER``), never an error and never a silent pass.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .graph import BLOCKING_REASONS, DependencyGraph
from .inventory import FileRecord

__all__ = [
    "VERDICTS", "FEATURE_CATALOG", "ToolProbe", "CompilerBackend", "Runner", "probe_toolchain", "toolchain_requirements",
    "assess_compatibility", "select_backend", "program_features", "DEFAULT_IMAGE", "ToolchainConfig", "default_runner",
]

DEFAULT_IMAGE = "gnucobol-ocesql:latest"
COBC_VERSION = re.compile(r"cobc \(GnuCOBOL\)\s+(\S+)")
GCOBOL_VERSION = re.compile(r"gcobol[^\n]*?(\d+\.\d+(?:\.\d+)?)", re.IGNORECASE)
DIAGNOSTIC = re.compile(r"^(?P<file>.+?):(?P<line>\d+): (?P<kind>error|warning): (?P<message>.*)$")
PROBE_TIMEOUT = 20
CHECK_TIMEOUT = 60

#: Closed set of per-program compatibility verdicts.
VERDICTS = (
    "COMPILES", "COMPILES_WITH_WARNINGS", "COMPILE_ERRORS", "NOT_ATTEMPTED_PROPRIETARY", "NOT_ATTEMPTED_SQL_PRECOMPILER",
    "NOT_ATTEMPTED_BLOCKED_DEPENDENCY", "NOT_ATTEMPTED_REFERENCE_FORMAT", "NOT_ATTEMPTED_NO_COMPILER", "NOT_ATTEMPTED_BUDGET",
    "NOT_ATTEMPTED_TOOL_FAILURE",
)

#: Proprietary or unsupported features, what open-source tooling can and cannot do about them, and whether they stop a syntax check.
#: ``stops_check`` features need a translator or runtime that has no open-source equivalent, so GnuCOBOL cannot meaningfully check
#: the source; the rest are recorded and the check continues.
FEATURE_CATALOG: dict[str, dict[str, object]] = {
    "exec-cics": {"label": "EXEC CICS", "stops_check": True,
                  "note": "needs the IBM CICS command-level translator; no open-source translator exists, so the program is not "
                          "syntax-checked and CICS stays simulator-only in this product"},
    "exec-dli": {"label": "EXEC DLI / IMS DL/I calls", "stops_check": True,
                 "note": "needs the IBM IMS DL/I translator and runtime; no open-source equivalent; simulator-only in this product"},
    "exec-sql-db2": {"label": "EXEC SQL (Db2 precompiler)", "stops_check": True,
                     "note": "the IBM Db2 precompiler is proprietary; ocesql (open source, PostgreSQL) is probed and reported but this "
                             "discovery does not run a precompile step, so EXEC SQL programs are never syntax-checked here"},
    "ibm-mq": {"label": "IBM MQ API calls", "stops_check": False,
               "note": "the program is checked, but the IBM MQ client libraries are proprietary and are not provided; MQ is simulator-only"},
    "language-environment": {"label": "IBM Language Environment callable services (CEE*)", "stops_check": False,
                             "note": "GnuCOBOL has no CEE* services; a call is recorded as an unsupported runtime dependency"},
    "ibm-compiler-options": {"label": "IBM compiler options", "stops_check": False,
                             "note": "options such as ARITH(EXTEND), TRUNC, NUMPROC, SSRANGE, DYNAM or CICS/SQL change semantics; "
                                     "GnuCOBOL -std=ibm approximates but does not reproduce IBM Enterprise COBOL"},
    "object-oriented-cobol": {"label": "Object-oriented COBOL (CLASS-ID, INVOKE)", "stops_check": True,
                              "note": "not supported by GnuCOBOL"},
    "microfocus-directives": {"label": "Micro Focus $SET directives", "stops_check": False,
                              "note": "partially honoured by cobc -std=mf; unsupported directives are reported as compiler diagnostics"},
    "assembler-called": {"label": "Called assembler program", "stops_check": False,
                         "note": "no open-source z/Architecture assembler is used; the called module is inventoried only"},
    "pli-or-rexx-called": {"label": "Called PL/I, REXX or CLIST", "stops_check": False,
                           "note": "no open-source PL/I or REXX translation is provided; the called member is inventoried only"},
}
_IBM_SEMANTIC_OPTIONS = frozenset({"ARITH", "TRUNC", "NUMPROC", "SSRANGE", "DYNAM", "NODYNAM", "OPT", "RENT", "CICS", "SQL", "LIB",
                                   "CODEPAGE", "NSYMBOL", "ADV", "AWO", "BLOCK0", "DBCS", "FLAG", "NUMCLS", "OPTIMIZE", "RMODE"})
_STD_BY_DIALECT = {"ibm-enterprise": "ibm", "microfocus": "mf", "legacy-cobol74": "cobol85", "cobol85": "cobol85",
                   "gnucobol": "default", "gnucobol-or-microfocus": "default"}


@dataclass(frozen=True)
class ToolchainConfig:
    """How discovery looks for and uses open-source compilers.  ``backend`` is ``auto``, ``local``, ``container`` or ``none``."""

    backend: str = "auto"
    budget_seconds: float = 240.0
    image: str = DEFAULT_IMAGE
    runner: Callable[[Sequence[str], float], "subprocess.CompletedProcess[str]"] | None = None
    which: Callable[[str], str | None] | None = None

    @classmethod
    def from_environment(cls) -> "ToolchainConfig":
        import os

        backend = os.environ.get("DISCOVERY_COMPILER_BACKEND", "auto").strip().lower()
        if backend not in ("auto", "local", "container", "none"):
            backend = "none"  # an unreadable setting never enables a tool
        try:
            budget = float(os.environ.get("DISCOVERY_COMPILE_BUDGET_SECONDS", "240"))
        except ValueError:
            budget = 240.0
        return cls(backend, budget, os.environ.get("DISCOVERY_COBC_IMAGE", DEFAULT_IMAGE))


@dataclass(frozen=True)
class ToolProbe:
    """One open-source tool this host can (or cannot) run."""

    tool: str
    available: bool
    version: str = ""
    via: str = ""  # "local" | "container:<image>" | ""
    reason: str = ""  # why unavailable
    license: str = ""

    def as_dict(self) -> dict[str, object]:
        out: dict[str, object] = {"available": self.available, "license": self.license, "tool": self.tool}
        for key in ("version", "via", "reason"):
            if getattr(self, key):
                out[key] = getattr(self, key)
        return out


Runner = Callable[[Sequence[str], float], "subprocess.CompletedProcess[str]"]


def default_runner(command: Sequence[str], timeout: float) -> "subprocess.CompletedProcess[str]":
    """Run a tool without a shell, with a clean environment and a hard timeout."""
    import os

    env = {key: value for key, value in os.environ.items()
           if key.upper() in ("PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "TMPDIR", "HOME", "USERPROFILE",
                              "DOCKER_HOST", "DOCKER_CONFIG", "LANG")}
    return subprocess.run(list(command), capture_output=True, text=True, timeout=timeout, env=env, check=False,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0)  # noqa: S603


# --- backends ---------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class CompilerBackend:
    """How ``cobc`` is run: directly, or inside the GnuCOBOL container image with the source mounted read-only and no network."""

    kind: str  # "local" | "container" | "none"
    version: str = ""
    cobc: str = "cobc"
    image: str = ""
    reason: str = ""

    def command(self, source_root: Path, relative: str, extra: Sequence[str]) -> list[str]:
        if self.kind == "container":
            return ["docker", "run", "--rm", "--network", "none", "--memory", "512m", "--pids-limit", "128", "-v",
                    f"{source_root}:/src:ro", "-w", "/tmp", self.image, "cobc", "-fsyntax-only", *extra, f"/src/{relative}"]
        return [self.cobc, "-fsyntax-only", *extra, str(source_root / relative)]

    def mount_prefix(self, source_root: Path) -> str:
        return "/src/" if self.kind == "container" else str(source_root).replace("\\", "/").rstrip("/") + "/"


def _version(pattern: re.Pattern[str], text: str) -> str:
    match = pattern.search(text)
    return match.group(1) if match else ""


def _probe_command(tool: str, command: Sequence[str], pattern: re.Pattern[str], license_name: str, runner: Runner) -> ToolProbe:
    try:
        done = runner(command, PROBE_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return ToolProbe(tool, False, reason=f"{type(exc).__name__} running {command[0]}", license=license_name)
    text = (done.stdout or "") + (done.stderr or "")
    if done.returncode != 0:
        return ToolProbe(tool, False, reason=f"{command[0]} exited {done.returncode}", license=license_name)
    first_line = text.strip().splitlines()[0][:60] if text.strip() else ""
    return ToolProbe(tool, True, _version(pattern, text) or first_line, "local", license=license_name)


def _container_cobc(image: str, runner: Runner) -> ToolProbe | None:
    try:
        inspect = runner(["docker", "image", "inspect", image, "--format", "{{.Id}}"], PROBE_TIMEOUT)
        if inspect.returncode != 0:
            return None
        ran = runner(["docker", "run", "--rm", "--network", "none", image, "cobc", "--version"], 60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    version = _version(COBC_VERSION, (ran.stdout or "") + (ran.stderr or ""))
    return ToolProbe("cobc", True, version, f"container:{image}", license="GPL-3.0-or-later (GnuCOBOL)") if ran.returncode == 0 and version \
        else None


def probe_toolchain(*, runner: Runner = default_runner, which: Callable[[str], str | None] = shutil.which,
                    image: str = DEFAULT_IMAGE, use_container: bool = True) -> list[ToolProbe]:
    """Probe the open-source tools relevant to COBOL modernization; always returns one entry per tool, sorted by name."""
    probes: list[ToolProbe] = []
    cobc_path = which("cobc")
    cobc = _probe_command("cobc", [cobc_path, "--version"], COBC_VERSION, "GPL-3.0-or-later (GnuCOBOL)", runner) if cobc_path else None
    if cobc is None or not cobc.available:
        local_reason = cobc.reason if cobc is not None else "no cobc on PATH"
        contained = _container_cobc(image, runner) if use_container and which("docker") else None
        cobc = contained or ToolProbe("cobc", False, reason=local_reason + ("; GnuCOBOL image not available" if use_container else ""),
                                      license="GPL-3.0-or-later (GnuCOBOL)")
    probes.append(cobc)
    gcobol_path = which("gcobol")
    probes.append(_probe_command("gcobol", [gcobol_path, "--version"], GCOBOL_VERSION, "GPL-3.0-or-later with GCC Runtime Library Exception",
                                 runner) if gcobol_path else ToolProbe("gcobol", False, reason="not on PATH (GCC COBOL front end, "
                                                                                              "GCC 15 or newer)",
                                                                       license="GPL-3.0-or-later with GCC Runtime Library Exception"))
    ocesql_path = which("ocesql")
    probes.append(ToolProbe("ocesql", True, "", "local", license="GPL-3.0-or-later / LGPL (Open Cobol ESQL)") if ocesql_path else
                  ToolProbe("ocesql", False, reason="not on PATH; Db2 precompilation is proprietary and is never attempted",
                            license="GPL-3.0-or-later / LGPL (Open Cobol ESQL)"))
    java_path = which("javac")
    probes.append(_probe_command("javac", [java_path, "-version"], re.compile(r"javac\s+(\S+)"), "GPL-2.0 with Classpath Exception (OpenJDK)",
                                 runner) if java_path else ToolProbe("javac", False, reason="no JDK on PATH",
                                                                     license="GPL-2.0 with Classpath Exception (OpenJDK)"))
    mvn_path = which("mvn")
    probes.append(_probe_command("mvn", [mvn_path, "--version"], re.compile(r"Apache Maven\s+(\S+)"), "Apache-2.0", runner)
                  if mvn_path else ToolProbe("mvn", False, reason="no Maven on PATH", license="Apache-2.0"))
    return sorted(probes, key=lambda p: p.tool)


def select_backend(probes: Sequence[ToolProbe], *, preference: str = "auto", image: str = DEFAULT_IMAGE) -> CompilerBackend:
    """The ``cobc`` backend to use: ``auto`` (local, else container), ``local``, ``container`` or ``none``."""
    cobc = next((p for p in probes if p.tool == "cobc"), None)
    if preference == "none":
        return CompilerBackend("none", reason="compiler checks disabled by configuration")
    if cobc is None or not cobc.available:
        return CompilerBackend("none", reason=cobc.reason if cobc else "no cobc probe")
    if cobc.via == "local" and preference in ("auto", "local"):
        return CompilerBackend("local", cobc.version)
    if cobc.via.startswith("container:") and preference in ("auto", "container"):
        return CompilerBackend("container", cobc.version, image=cobc.via.split(":", 1)[1])
    return CompilerBackend("none", reason=f"requested backend {preference!r} is not available")


# --- required toolchains ---------------------------------------------------------------------------------------------------


def toolchain_requirements(records: Sequence[FileRecord]) -> list[dict[str, object]]:
    """What the estate says it is built with: compiler families, versions, flags and directives, each with source positions."""
    found: dict[tuple[str, str], dict[str, Any]] = {}

    def note(family: str, kind: str, name: str, record: FileRecord, line: int, **detail: str) -> None:
        entry = found.setdefault((family, kind + ":" + name), {"detail": {}, "evidence": [], "family": family, "kind": kind, "name": name})
        entry["evidence"].append((record.path, line))
        entry["detail"].update({k: v for k, v in detail.items() if v})

    for record in sorted(records, key=lambda r: r.path):
        if record.scan is None:
            continue
        for fact in record.scan.facts:
            info = dict(fact.detail)
            if fact.category == "compiler-option":
                note("ibm-enterprise-cobol", "compiler-option", fact.name, record, fact.line, card=info.get("card", ""))
            elif fact.category == "compile-step":
                compiler = info.get("compiler") or info.get("procedure") or "COBOL compile step"
                note("ibm-enterprise-cobol", "jcl-compile-step", compiler, record, fact.line, options=info.get("options", ""))
            elif fact.category == "link-step":
                note("ibm-linkage-editor", "jcl-link-step", info.get("linker", fact.name), record, fact.line)
            elif fact.category == "build-invocation" and fact.name in ("cobc", "cob", "cobcrun"):
                note("gnucobol", "invocation", fact.name, record, fact.line, flags=info.get("flags", ""), standard=info.get("standard", ""),
                     format=info.get("format", ""))
            elif fact.category == "build-invocation" and fact.name in ("mfcob", "cobol", "runcbl"):
                note("microfocus-cobol", "invocation", fact.name, record, fact.line, flags=info.get("flags", ""))
            elif fact.category == "build-invocation" and fact.name in ("ocesql", "esql", "dbpre", "cicsprep", "dfhcob"):
                note("sql-or-cics-preprocessor", "invocation", fact.name, record, fact.line)
            elif fact.category == "build-invocation" and fact.name in ("mvn", "gradle", "gradlew", "javac", "java"):
                note("java", "invocation", fact.name, record, fact.line)
            elif fact.category == "directive" and fact.name.startswith("$SET"):
                note("microfocus-cobol", "directive", fact.name[:40], record, fact.line)
            elif fact.category == "directive" and fact.name.startswith(">>"):
                note("gnucobol", "directive", fact.name[:40], record, fact.line)
            elif fact.category == "runtime-setting" and fact.name.startswith(("COB_", "COBPATH", "COBCPY", "COBDIR")):
                note("gnucobol", "runtime-setting", fact.name, record, fact.line, value=info.get("value", ""))
    out = []
    for (_, _), entry in sorted(found.items()):
        evidence = sorted(set(entry["evidence"]))
        out.append({"detail": dict(sorted(entry["detail"].items())),
                    "evidence": [{"file": f, "line": ln} for f, ln in evidence[:25]], "evidence_count": len(evidence),
                    "family": entry["family"], "kind": entry["kind"], "name": entry["name"]})
    return out


# --- per-program features ---------------------------------------------------------------------------------------------------


def program_features(record: FileRecord) -> dict[str, list[tuple[str, int]]]:
    """Proprietary/unsupported features present in one COBOL file: ``feature id -> [(evidence label, line)]``."""
    features: dict[str, list[tuple[str, int]]] = {}
    if record.scan is None:
        return features

    def add(feature: str, label: str, line: int) -> None:
        features.setdefault(feature, []).append((label, line))

    for fact in record.scan.facts:
        info = dict(fact.detail)
        if fact.category == "cics-command":
            add("exec-cics", f"EXEC CICS {fact.name}", fact.line)
        elif fact.category == "dli-command":
            add("exec-dli", f"EXEC DLI {fact.name}", fact.line)
        elif fact.category in ("sql-statement", "sql-declare-table", "dynamic-sql"):
            add("exec-sql-db2", f"EXEC SQL {fact.name}", fact.line)
        elif fact.category == "compiler-option" and fact.name.split("(")[0] in _IBM_SEMANTIC_OPTIONS:
            add("ibm-compiler-options", f"CBL {fact.name}", fact.line)
        elif fact.category == "program-id" and info.get("kind") in ("CLASS-ID", "INTERFACE-ID"):
            add("object-oriented-cobol", info["kind"], fact.line)
        elif fact.category == "directive" and fact.name.startswith("$SET"):
            add("microfocus-directives", fact.name[:30], fact.line)
    for ref in record.scan.refs:
        if ref.relation == "uses-ims":
            add("exec-dli", f"IMS call {ref.target}", ref.line)
        elif ref.relation == "uses-mq":
            add("ibm-mq", f"MQ call {ref.target}", ref.line)
        elif ref.relation == "uses-runtime" and dict(ref.detail).get("subsystem") == "LE":
            add("language-environment", f"CALL {ref.target}", ref.line)
    return features


def _called_foreign_programs(record: FileRecord, graph: DependencyGraph, languages: Mapping[str, str]) -> dict[str, list[tuple[str, int]]]:
    out: dict[str, list[tuple[str, int]]] = {}
    for edge in graph.edges_in_file(record.path):
        if edge.relation != "calls" or edge.resolution != "resolved":
            continue
        node = graph.nodes.get(edge.dst)
        language = languages.get(node.path, "") if node else ""
        if language == "assembler":
            out.setdefault("assembler-called", []).append((f"CALL {edge.dst.split(':', 1)[-1]}", edge.line))
        elif language in ("pli", "rexx", "clist"):
            out.setdefault("pli-or-rexx-called", []).append((f"CALL {edge.dst.split(':', 1)[-1]}", edge.line))
    return out


# --- compatibility ------------------------------------------------------------------------------------------------------------


@dataclass
class _Plan:
    record: FileRecord
    std: str
    fmt: str
    includes: list[str] = field(default_factory=list)


def _std_for(record: FileRecord, dialect: Mapping[str, str]) -> str:
    return std_for_dialect(dialect.get(record.path, ""))


def std_for_dialect(dialect: str) -> str:
    """The GnuCOBOL ``-std`` value selected for a dialect (``"default"`` when undetermined).

    The one dialect→standard mapping: the ``DialectProfile`` builder and the check lane both call
    this instead of touching ``_STD_BY_DIALECT`` (layer model, contract 3).
    """
    return _STD_BY_DIALECT.get(dialect, "default")


def _includes(records: Sequence[FileRecord], own_dir: str) -> list[str]:
    directories = {r.path.rsplit("/", 1)[0] if "/" in r.path else "" for r in records if r.cls == "copybook"}
    return sorted(directories | {own_dir}, key=lambda d: (d != own_dir, d))


def _format_refusal_reason(record: FileRecord) -> str:
    """Why the check lane did not run on a ``mixed``/``variable`` reference format, in one honest sentence.

    The syntax-check lane flags a whole compilation unit with one ``-free``/``-fixed`` switch; a file that
    switches format mid-file (or asks for ``$SET SOURCEFORMAT VARIABLE``) cannot be represented by one flag,
    so it is refused by name instead of being checked under a flag that would misread part of it
    (Layer 4 acceptance criterion 2: never a misleading ``COMPILE_ERRORS``).
    """
    if record.source_format == "variable":
        return ("$SET SOURCEFORMAT VARIABLE is not supported by the check lane: one -free/-fixed flag cannot "
                "represent it, so no check is attempted (never a silent fixed read)")
    switches = record.scan.format_switches if record.scan else ()
    at = f" at line {switches[0][0]}" if switches else ""
    return (f"the reference format changes mid-file{at}, so one -free/-fixed flag cannot represent the file; "
            "the check lane does not guess a format per segment")


def assess_compatibility(records: Sequence[FileRecord], graph: DependencyGraph, source_root: Path, backend: CompilerBackend, *,
                         dialects: Mapping[str, str] | None = None, probes: Sequence[ToolProbe] = (), runner: Runner = default_runner,
                         budget_seconds: float = 240.0, clock: Callable[[], float] = time.monotonic) -> dict[str, object]:
    """Syntax-check every checkable COBOL program and report a verdict, diagnostics and unsupported features per program."""
    dialects = dialects or {}
    languages = {r.path: r.cls for r in records if r.cls in ("assembler", "pli", "rexx", "clist")}
    blocked_files = {e.file for e in graph.unresolved() if e.reason in BLOCKING_REASONS and e.relation in ("copies", "calls")}
    started = clock()
    rows: dict[str, dict[str, object]] = {}
    plans: list[_Plan] = []
    for record in sorted(records, key=lambda r: r.path):
        if record.cls != "cobol":
            continue
        features = program_features(record)
        for feature, items in _called_foreign_programs(record, graph, languages).items():
            features.setdefault(feature, []).extend(items)
        entry: dict[str, object] = {"diagnostics": [], "dialect": dialects.get(record.path, "undetermined"), "file": record.path,
                                    "source_format": record.source_format or "fixed",
                                    "unsupported_features": [_feature_row(f, items) for f, items in sorted(features.items())]}
        rows[record.path] = entry
        stopper = next((f for f in sorted(features) if FEATURE_CATALOG[f]["stops_check"]), "")
        if stopper:
            entry.update(verdict="NOT_ATTEMPTED_SQL_PRECOMPILER" if stopper == "exec-sql-db2" else "NOT_ATTEMPTED_PROPRIETARY",
                         reason=str(FEATURE_CATALOG[stopper]["note"]))
        elif record.path in blocked_files:
            entry.update(verdict="NOT_ATTEMPTED_BLOCKED_DEPENDENCY",
                         reason="a copybook or called program is missing from the upload, so a compile result would be misleading")
        elif record.source_format in ("mixed", "variable"):
            entry.update(verdict="NOT_ATTEMPTED_REFERENCE_FORMAT", reason=_format_refusal_reason(record))
        elif backend.kind == "none":
            entry.update(verdict="NOT_ATTEMPTED_NO_COMPILER", reason=backend.reason or "no open-source COBOL compiler is available")
        else:
            plans.append(_Plan(record, _std_for(record, dialects), "free" if record.source_format == "free" else "fixed"))
    _run_checks(rows, plans, backend, source_root, records, runner, budget_seconds, clock, started)
    programs = [rows[path] for path in sorted(rows)]
    summary: dict[str, int] = {v: 0 for v in VERDICTS}
    for program in programs:
        summary[str(program["verdict"])] += 1
    return {
        "backend": {"kind": backend.kind, "reason": backend.reason, "tool": "cobc" if backend.kind != "none" else "",
                    "version": backend.version, **({"image": backend.image} if backend.image else {})},
        "basis": "syntax-only check with GnuCOBOL (cobc -fsyntax-only); nothing is built or executed. A passing check shows the source is "
                 "acceptable to GnuCOBOL in the chosen dialect, not that it behaves like the customer's production compiler.",
        "feature_catalog": {k: {"label": v["label"], "note": v["note"], "stops_check": v["stops_check"]} for k, v in
                            sorted(FEATURE_CATALOG.items())},
        "programs": programs,
        "summary": {k: v for k, v in summary.items() if v},
        "tools": [p.as_dict() for p in probes],
    }


def _feature_row(feature: str, items: Sequence[tuple[str, int]]) -> dict[str, object]:
    unique = sorted(set(items), key=lambda x: (x[1], x[0]))
    return {"evidence": [{"label": label, "line": line} for label, line in unique[:10]], "evidence_count": len(unique), "feature": feature,
            "label": FEATURE_CATALOG[feature]["label"], "note": FEATURE_CATALOG[feature]["note"],
            "stops_check": FEATURE_CATALOG[feature]["stops_check"]}


BATCH_SIZE = 40
MARKER = "@@COBC-RESULT"


def _flags(plan: _Plan, prefix: str, records: Sequence[FileRecord]) -> list[str]:
    flags = [f"-std={plan.std}", "-free" if plan.fmt == "free" else "-fixed"]
    own_dir = plan.record.path.rsplit("/", 1)[0] if "/" in plan.record.path else ""
    for directory in _includes(records, own_dir):
        flags += ["-I", f"{prefix}{directory}".rstrip("/") if directory else prefix.rstrip("/")]
    return flags


def _run_checks(rows: dict[str, dict[str, object]], plans: list[_Plan], backend: CompilerBackend, source_root: Path,
                records: Sequence[FileRecord], runner: Runner, budget: float, clock: Callable[[], float], started: float) -> None:
    prefix = backend.mount_prefix(source_root)
    pending = list(plans)
    while pending:
        if clock() - started > budget:
            for plan in pending:
                rows[plan.record.path].update(verdict="NOT_ATTEMPTED_BUDGET", reason=f"the {int(budget)} s compile-check budget was used up")
            return
        batch, pending = (pending[:BATCH_SIZE], pending[BATCH_SIZE:]) if backend.kind == "container" else (pending[:1], pending[1:])
        outcomes = _execute(batch, backend, source_root, prefix, records, runner)
        for plan in batch:
            entry = rows[plan.record.path]
            entry["command_flags"] = [f"-std={plan.std}", "-free" if plan.fmt == "free" else "-fixed", "-I <estate directories>"]
            code, stderr, failure = outcomes.get(plan.record.path, (None, "", "the compiler produced no result"))
            if failure:
                entry.update(verdict="NOT_ATTEMPTED_TOOL_FAILURE", reason=failure)
                continue
            diagnostics = _parse(stderr, prefix, plan.record.path)
            entry["diagnostics"] = diagnostics
            errors = [d for d in diagnostics if d["severity"] == "error"]
            if code == 0 and not errors:
                entry["verdict"] = "COMPILES_WITH_WARNINGS" if diagnostics else "COMPILES"
            elif errors:
                entry["verdict"] = "COMPILE_ERRORS"
            else:
                entry.update(verdict="NOT_ATTEMPTED_TOOL_FAILURE", reason=f"the compiler exited {code} without a diagnostic")


def _execute(batch: list[_Plan], backend: CompilerBackend, source_root: Path, prefix: str, records: Sequence[FileRecord],
             runner: Runner) -> dict[str, tuple[int | None, str, str]]:
    """``{path: (exit code, stderr text, failure reason)}``; one process per file locally, one container per batch."""
    import shlex

    if backend.kind == "local":
        plan = batch[0]
        try:
            done = runner(backend.command(source_root, plan.record.path, _flags(plan, prefix, records)), CHECK_TIMEOUT)
        except subprocess.TimeoutExpired:
            return {plan.record.path: (None, "", f"the compiler did not finish within {CHECK_TIMEOUT} s")}
        except OSError as exc:
            return {plan.record.path: (None, "", f"the compiler could not be started ({type(exc).__name__})")}
        return {plan.record.path: (done.returncode, done.stderr or "", "")}
    lines = []
    for plan in batch:
        words = ["cobc", "-fsyntax-only", *_flags(plan, prefix, records), f"{prefix}{plan.record.path}"]
        lines.append(f"{' '.join(shlex.quote(w) for w in words)} 2>&1; echo \"{MARKER}:$?\"")
    command = ["docker", "run", "--rm", "--network", "none", "--memory", "512m", "--pids-limit", "128", "-v", f"{source_root}:/src:ro",
               "-w", "/tmp", backend.image, "sh", "-c", "\n".join(lines)]
    try:
        done = runner(command, min(900, 30 + 10 * len(batch)))
    except subprocess.TimeoutExpired:
        return {p.record.path: (None, "", "the compiler container did not finish in time") for p in batch}
    except OSError as exc:
        return {p.record.path: (None, "", f"the compiler container could not be started ({type(exc).__name__})") for p in batch}
    chunks = (done.stdout or "").split(f"{MARKER}:")
    outcomes: dict[str, tuple[int | None, str, str]] = {}
    previous_text = chunks[0] if chunks else ""
    for index, plan in enumerate(batch):
        if index + 1 >= len(chunks):
            outcomes[plan.record.path] = (None, "", "the compiler container stopped before checking this file")
            continue
        code_text, _, rest = chunks[index + 1].partition("\n")
        outcomes[plan.record.path] = (int(code_text) if code_text.strip().isdigit() else None, previous_text, "")
        previous_text = rest
    return outcomes


def _parse(stderr: str, prefix: str, own_path: str) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for raw in stderr.splitlines():
        match = DIAGNOSTIC.match(raw.strip())
        if not match:
            continue
        name = match.group("file").replace("\\", "/")
        relative = name[len(prefix):] if name.startswith(prefix) else name
        out.append({"file": relative or own_path, "line": int(match.group("line")),
                    "message": match.group("message")[:300], "severity": match.group("kind")})
    return sorted(out, key=lambda d: (str(d["file"]), int(str(d["line"])), str(d["severity"]), str(d["message"])))[:100]
