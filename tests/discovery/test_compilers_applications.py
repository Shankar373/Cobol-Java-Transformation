"""Compiler/toolchain discovery, application and entry-point discovery, and the readiness decision."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

from enterprise.discovery.applications import build_applications
from enterprise.discovery.classify import classify
from enterprise.discovery.compilers import (
    FEATURE_CATALOG,
    VERDICTS,
    CompilerBackend,
    ToolProbe,
    assess_compatibility,
    probe_toolchain,
    select_backend,
    toolchain_requirements,
)
from enterprise.discovery.discover import scan_file
from enterprise.discovery.inventory import FileRecord
from enterprise.discovery.readiness import describe_blockers, evaluate_readiness
from enterprise.discovery.resolve import build_graph
from tests.discovery.helpers import _fixed
from tests.discovery.test_resolve_graph import program


def records(files: dict[str, str]) -> list[FileRecord]:
    out = []
    for path, text in files.items():
        cls = classify(path, text).cls
        scan = scan_file(path, cls, text)
        out.append(FileRecord(path, hashlib.sha256(text.encode()).hexdigest(), len(text), cls, source_format=scan.source_format if scan else "",
                              scan=scan))
    return out


class FakeCobc:
    """A stand-in for ``cobc -fsyntax-only``: errors on a ``BADSYNTAX`` line, warns on ``WARNME``; records every command."""

    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def __call__(self, command, timeout):
        if command[-1] == "--version":
            return subprocess.CompletedProcess([], 0, "cobc (GnuCOBOL) 3.2.0\n", "")
        self.commands.append(list(command))
        if command[0] == "docker":
            return self._container(command)
        path = Path(command[-1])
        return self._check(str(path), path.read_text(encoding="utf-8"))

    @staticmethod
    def _check(name: str, text: str):
        lines = text.splitlines()
        for number, line in enumerate(lines, start=1):
            if "BADSYNTAX" in line:
                return subprocess.CompletedProcess([], 1, "", f"{name}:{number}: error: syntax error, unexpected BADSYNTAX\n")
            if "WARNME" in line:
                return subprocess.CompletedProcess([], 0, "", f"{name}:{number}: warning: something questionable\n")
        return subprocess.CompletedProcess([], 0, "", "")

    def _container(self, command):
        script = command[-1]
        root = Path(command[command.index("-v") + 1].split(":/src")[0])
        out = []
        for line in script.splitlines():
            target = [word.strip("'") for word in line.split() if word.strip("'").startswith("/src/")][-1]
            done = self._check(target, (root / target[len("/src/"):]).read_text(encoding="utf-8"))
            out.append(done.stderr + f"@@COBC-RESULT:{done.returncode}\n")
        return subprocess.CompletedProcess([], 0, "".join(out), "")


LOCAL = CompilerBackend("local", "3.1.2.0")


def assess(files: dict[str, str], tmp_path: Path, backend: CompilerBackend = LOCAL, runner=None, **kwargs):
    root = tmp_path / "src"
    for path, text in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    recs = records(files)
    graph = build_graph(recs).graph
    return assess_compatibility(recs, graph, root, backend, runner=runner or FakeCobc(), **kwargs)


def verdicts(report) -> dict[str, str]:
    return {p["file"]: p["verdict"] for p in report["programs"]}


# --- compatibility verdicts -----------------------------------------------------------------------------------------------


def test_verdicts_cover_compiles_errors_warnings_and_map_diagnostics_to_lines(tmp_path: Path) -> None:
    report = assess({"a/OK.cbl": program("OK"), "a/BAD.cbl": program("BAD", "BADSYNTAX HERE."), "a/WARN.cbl": program("WARN", "WARNME.")},
                    tmp_path)
    assert verdicts(report) == {"a/BAD.cbl": "COMPILE_ERRORS", "a/OK.cbl": "COMPILES", "a/WARN.cbl": "COMPILES_WITH_WARNINGS"}
    bad = next(p for p in report["programs"] if p["file"] == "a/BAD.cbl")
    assert bad["diagnostics"][0]["line"] == 4 and bad["diagnostics"][0]["severity"] == "error" and bad["diagnostics"][0]["file"] == "a/BAD.cbl"
    assert report["summary"] == {"COMPILES": 1, "COMPILES_WITH_WARNINGS": 1, "COMPILE_ERRORS": 1}
    assert set(verdicts(report).values()) <= set(VERDICTS)


def test_proprietary_constructs_are_reported_by_name_and_never_attempted(tmp_path: Path) -> None:
    runner = FakeCobc()
    files = {"a/CICS.cbl": program("CICS", "EXEC CICS RETURN END-EXEC."), "a/IMS.cbl": program("IMS", "CALL 'CBLTDLI' USING A B."),
             "a/DB2.cbl": program("DB2", "EXEC SQL SELECT 1 FROM T END-EXEC."), "a/MQ.cbl": program("MQ", "CALL 'MQOPEN' USING A."),
             "a/LE.cbl": program("LE", "CALL 'CEEDATE' USING A.")}
    report = assess(files, tmp_path, runner=runner)
    assert verdicts(report) == {"a/CICS.cbl": "NOT_ATTEMPTED_PROPRIETARY", "a/DB2.cbl": "NOT_ATTEMPTED_SQL_PRECOMPILER",
                                "a/IMS.cbl": "NOT_ATTEMPTED_PROPRIETARY", "a/LE.cbl": "COMPILES", "a/MQ.cbl": "COMPILES"}
    features = {p["file"]: [f["feature"] for f in p["unsupported_features"]] for p in report["programs"]}
    assert features["a/CICS.cbl"] == ["exec-cics"] and features["a/IMS.cbl"] == ["exec-dli"] and features["a/MQ.cbl"] == ["ibm-mq"]
    assert features["a/LE.cbl"] == ["language-environment"] and features["a/DB2.cbl"] == ["exec-sql-db2"]
    checked = {Path(c[-1]).name for c in runner.commands}
    assert checked == {"MQ.cbl", "LE.cbl"}, "proprietary programs must not be sent to the compiler"
    cics = next(p for p in report["programs"] if p["file"] == "a/CICS.cbl")
    assert "no open-source translator" in cics["reason"] and cics["unsupported_features"][0]["evidence"][0]["line"] == 4


def test_exec_sql_is_never_syntax_checked_even_when_ocesql_is_installed(tmp_path: Path) -> None:
    probes = [ToolProbe("ocesql", True, "", "local")]
    report = assess({"a/SQL.cbl": program("SQL", "EXEC SQL SELECT 1 FROM T END-EXEC.")}, tmp_path, probes=probes)
    assert verdicts(report) == {"a/SQL.cbl": "NOT_ATTEMPTED_SQL_PRECOMPILER"}


def test_a_program_with_a_missing_copybook_is_not_given_a_misleading_compile_result(tmp_path: Path) -> None:
    report = assess({"a/P.cbl": program("P", "COPY GONE."), "a/Q.cbl": program("Q")}, tmp_path)
    assert verdicts(report) == {"a/P.cbl": "NOT_ATTEMPTED_BLOCKED_DEPENDENCY", "a/Q.cbl": "COMPILES"}


def test_mixed_and_variable_reference_formats_are_refused_by_name_never_misflagged(tmp_path: Path) -> None:
    """A file the lane's single -free/-fixed flag cannot represent is refused by name, never checked and never COMPILE_ERRORS."""
    mixed = _fixed("IDENTIFICATION DIVISION.", "PROGRAM-ID. MIXED.", "PROCEDURE DIVISION.",
                   "DISPLAY 'X'.") + ">>SOURCE FORMAT FREE\nGOBACK.\n"
    variable = '$SET SOURCEFORMAT"VARIABLE"\n' + program("VAR")
    report = assess({"a/MIXED.cbl": mixed, "a/VAR.cbl": variable, "a/OK.cbl": program("OK")}, tmp_path)
    assert verdicts(report) == {"a/MIXED.cbl": "NOT_ATTEMPTED_REFERENCE_FORMAT",
                                "a/VAR.cbl": "NOT_ATTEMPTED_REFERENCE_FORMAT", "a/OK.cbl": "COMPILES"}
    mixed_row = next(p for p in report["programs"] if p["file"] == "a/MIXED.cbl")
    var_row = next(p for p in report["programs"] if p["file"] == "a/VAR.cbl")
    assert mixed_row["source_format"] == "mixed" and "line 5" in mixed_row["reason"]
    assert var_row["source_format"] == "variable" and "VARIABLE" in var_row["reason"]
    assert report["summary"] == {"COMPILES": 1, "NOT_ATTEMPTED_REFERENCE_FORMAT": 2}
    assert set(verdicts(report).values()) <= set(VERDICTS)


def test_a_mixed_format_program_is_unverified_not_ready(tmp_path: Path) -> None:
    mixed = _fixed("IDENTIFICATION DIVISION.", "PROGRAM-ID. MIXED.", "PROCEDURE DIVISION.",
                   "DISPLAY 'X'.") + ">>SOURCE FORMAT FREE\nGOBACK.\n"
    gate = evaluate_readiness(report_for({"a/M.cbl": mixed}, LOCAL, tmp_path))
    assert gate["status"] == "NOT_SUPPORTED" and gate["allowed"] is True
    assert gate["unverified"] == [{"file": "a/M.cbl", "reason": "NOT_ATTEMPTED_REFERENCE_FORMAT"}]


def test_no_compiler_is_a_recorded_limitation_and_every_program_is_still_listed(tmp_path: Path) -> None:
    report = assess({"a/P.cbl": program("P"), "a/C.cbl": program("C", "EXEC CICS RETURN END-EXEC.")}, tmp_path,
                    backend=CompilerBackend("none", reason="no cobc on PATH"))
    assert verdicts(report) == {"a/C.cbl": "NOT_ATTEMPTED_PROPRIETARY", "a/P.cbl": "NOT_ATTEMPTED_NO_COMPILER"}
    assert report["backend"]["kind"] == "none" and "no cobc" in report["backend"]["reason"]
    assert next(p for p in report["programs"] if p["file"] == "a/P.cbl")["reason"] == "no cobc on PATH"


def test_budget_and_tool_failures_are_reported_not_hidden(tmp_path: Path) -> None:
    ticks = iter(range(0, 1000, 100))
    report = assess({"a/A.cbl": program("A"), "a/B.cbl": program("B")}, tmp_path, budget_seconds=150, clock=lambda: next(ticks))
    assert sorted(verdicts(report).values()) == ["COMPILES", "NOT_ATTEMPTED_BUDGET"]

    def timeout(command, seconds):
        raise subprocess.TimeoutExpired(command, seconds)

    assert set(verdicts(assess({"a/A.cbl": program("A")}, tmp_path / "t", runner=timeout)).values()) == {"NOT_ATTEMPTED_TOOL_FAILURE"}

    def broken(command, seconds):
        raise FileNotFoundError("cobc")

    assert set(verdicts(assess({"a/A.cbl": program("A")}, tmp_path / "u", runner=broken)).values()) == {"NOT_ATTEMPTED_TOOL_FAILURE"}

    def silent(command, seconds):
        return subprocess.CompletedProcess([], 3, "", "")

    result = assess({"a/A.cbl": program("A")}, tmp_path / "v", runner=silent)
    assert set(verdicts(result).values()) == {"NOT_ATTEMPTED_TOOL_FAILURE"}


def test_dialect_format_and_copybook_directories_become_compiler_flags(tmp_path: Path) -> None:
    runner = FakeCobc()
    files = {"src/IBM.cbl": "CBL SQL\n" + program("IBM"), "src/FREE.cbl": ">>SOURCE FORMAT FREE\nIDENTIFICATION DIVISION.\nPROGRAM-ID. FREE.\nPROCEDURE DIVISION.\nGOBACK.\n",
             "cpy/C.cpy": _fixed("01 A PIC X.")}
    assess(files, tmp_path, runner=runner, dialects={"src/IBM.cbl": "ibm-enterprise", "src/FREE.cbl": "gnucobol"})  # sources live under src/
    by_file = {Path(c[-1]).name: c for c in runner.commands}
    assert "-std=ibm" in by_file["IBM.cbl"] and "-fixed" in by_file["IBM.cbl"]
    assert "-std=default" in by_file["FREE.cbl"] and "-free" in by_file["FREE.cbl"]
    includes = [by_file["IBM.cbl"][i + 1] for i, word in enumerate(by_file["IBM.cbl"]) if word == "-I"]
    assert any(path.endswith("/cpy") for path in includes) and any(path.endswith("/src/src") for path in includes)
    assert "-fsyntax-only" in by_file["IBM.cbl"], "nothing may be built or executed"


def test_container_backend_checks_a_batch_in_one_container_and_parses_each_result(tmp_path: Path) -> None:
    runner = FakeCobc()
    files = {"a/OK.cbl": program("OK"), "a/BAD.cbl": program("BAD", "BADSYNTAX."), "a/WARN.cbl": program("WARN", "WARNME.")}
    report = assess(files, tmp_path, backend=CompilerBackend("container", "3.1.2.0", image="gnucobol-ocesql:latest"), runner=runner)
    assert verdicts(report) == {"a/BAD.cbl": "COMPILE_ERRORS", "a/OK.cbl": "COMPILES", "a/WARN.cbl": "COMPILES_WITH_WARNINGS"}
    assert len(runner.commands) == 1, "one container per batch, not per file"
    command = runner.commands[0]
    assert "--network" in command and command[command.index("--network") + 1] == "none"
    assert any(part.endswith(":/src:ro") for part in command), "the source is mounted read-only"
    bad = next(p for p in report["programs"] if p["file"] == "a/BAD.cbl")
    assert bad["diagnostics"][0]["file"] == "a/BAD.cbl" and bad["diagnostics"][0]["line"] == 4


def test_container_batch_cut_short_is_reported_per_file(tmp_path: Path) -> None:
    def truncated(command, seconds):
        return subprocess.CompletedProcess([], 0, "@@COBC-RESULT:0\n", "")

    report = assess({"a/A.cbl": program("A"), "a/B.cbl": program("B")}, tmp_path,
                    backend=CompilerBackend("container", "3.1.2.0", image="x"), runner=truncated)
    assert sorted(verdicts(report).values()) == ["COMPILES", "NOT_ATTEMPTED_TOOL_FAILURE"]


def test_every_feature_in_the_catalog_has_a_reason_and_only_open_source_alternatives(tmp_path: Path) -> None:
    for feature, info in FEATURE_CATALOG.items():
        assert info["label"] and len(str(info["note"])) > 20, feature
    text = " ".join(str(i["note"]) for i in FEATURE_CATALOG.values()).lower()
    assert "emulat" not in text and "pretend" not in text


def test_called_assembler_and_pli_members_are_listed_as_unsupported_but_do_not_stop_the_check(tmp_path: Path) -> None:
    files = {"a/M.cbl": program("M", "CALL 'ASMUTIL'.", "CALL 'PLISUB'."), "asm/ASMUTIL.asm": "ASMUTIL CSECT\n BR 14\n",
             "pli/PLISUB.pli": "PLISUB: PROC OPTIONS(MAIN);\n END PLISUB;\n"}
    report = assess(files, tmp_path)
    row = next(p for p in report["programs"] if p["file"] == "a/M.cbl")
    assert row["verdict"] == "COMPILES" and {f["feature"] for f in row["unsupported_features"]} == {"assembler-called", "pli-or-rexx-called"}


# --- probing ----------------------------------------------------------------------------------------------------------------


def which_of(*present: str):
    return lambda name: f"/usr/bin/{name}" if name in present else None


def runner_returning(outputs: dict[str, str]):
    def run(command, timeout):
        key = Path(command[0]).name if command[0] != "docker" else "docker " + " ".join(command[1:3])
        if key == "docker run":
            key = "docker run"
        text = outputs.get(key)
        if text is None:
            raise FileNotFoundError(command[0])
        return subprocess.CompletedProcess([], 0, text, "")
    return run


def test_probe_finds_local_gnucobol_gcobol_and_java_tools_with_versions() -> None:
    run = runner_returning({"cobc": "cobc (GnuCOBOL) 3.2.0\n", "gcobol": "gcobol (GCC) 15.1.0\n", "javac": "javac 21.0.2\n",
                            "mvn": "Apache Maven 3.9.9\n"})
    probes = {p.tool: p for p in probe_toolchain(runner=run, which=which_of("cobc", "gcobol", "javac", "mvn", "ocesql"), use_container=False)}
    assert (probes["cobc"].available, probes["cobc"].version, probes["cobc"].via) == (True, "3.2.0", "local")
    assert probes["gcobol"].version == "15.1.0" and probes["javac"].version == "21.0.2" and probes["mvn"].version == "3.9.9"
    assert probes["ocesql"].available
    assert all(p.license for p in probes.values()), "every probed tool carries its open-source licence"
    assert [p.tool for p in probe_toolchain(runner=run, which=which_of(), use_container=False)] == ["cobc", "gcobol", "javac", "mvn", "ocesql"]


def test_probe_falls_back_to_the_container_image_and_records_why_when_nothing_exists() -> None:
    def run(command, timeout):
        if command[:3] == ["docker", "image", "inspect"]:
            return subprocess.CompletedProcess([], 0, "sha256:abc", "")
        if command[0] == "docker" and command[1] == "run":
            return subprocess.CompletedProcess([], 0, "cobc (GnuCOBOL) 3.1.2.0\n", "")
        raise FileNotFoundError(command[0])

    cobc = next(p for p in probe_toolchain(runner=run, which=which_of("docker")) if p.tool == "cobc")
    assert cobc.available and cobc.via == "container:gnucobol-ocesql:latest" and cobc.version == "3.1.2.0"
    assert select_backend([cobc]).kind == "container"

    nothing = next(p for p in probe_toolchain(runner=run, which=which_of()) if p.tool == "cobc")
    assert not nothing.available and "no cobc" in nothing.reason
    backend = select_backend([nothing])
    assert backend.kind == "none" and "no cobc" in backend.reason


def test_a_broken_or_hanging_tool_is_unavailable_with_a_reason_not_an_exception() -> None:
    def hang(command, timeout):
        raise subprocess.TimeoutExpired(command, timeout)

    probes = probe_toolchain(runner=hang, which=which_of("cobc", "javac"), use_container=False)
    assert all(not p.available for p in probes if p.tool in ("cobc", "javac"))
    assert "TimeoutExpired" in next(p for p in probes if p.tool == "cobc").reason


def test_backend_preference_is_respected_and_none_disables_checks() -> None:
    local = ToolProbe("cobc", True, "3.2.0", "local")
    container = ToolProbe("cobc", True, "3.1.2.0", "container:img")
    assert select_backend([local]).kind == "local" and select_backend([container]).kind == "container"
    assert select_backend([local], preference="container").kind == "none"
    assert select_backend([local], preference="none").kind == "none"


# --- required toolchains ----------------------------------------------------------------------------------------------------


def test_required_toolchains_come_from_cards_makefiles_directives_and_jcl() -> None:
    recs = records({
        "src/IBM.cbl": "CBL SQL,ARITH(EXTEND)\n" + program("IBM"),
        "src/MF.cbl": "$SET SOURCEFORMAT\"FREE\"\n" + program("MF"),
        "build/Makefile": "all:\n\tcobc -x -std=ibm -free -I cpy src/IBM.cbl -o ibm\n\tmvn -q package\n",
        "jcl/BUILD.jcl": "//B JOB\n//C EXEC PGM=IGYCRCTL,PARM='LIB,SQL'\n//L EXEC PGM=IEWL\n",
        "run.sh": "#!/bin/sh\nexport COB_LIBRARY_PATH=/opt/lib\nmfcob -x prog.cbl\n"})
    required = {(t["family"], t["kind"], t["name"]) for t in toolchain_requirements(recs)}
    assert ("ibm-enterprise-cobol", "compiler-option", "SQL") in required and ("ibm-enterprise-cobol", "compiler-option", "ARITH(EXTEND)") in required
    assert ("gnucobol", "invocation", "cobc") in required and ("java", "invocation", "mvn") in required
    assert ("ibm-enterprise-cobol", "jcl-compile-step", "IGYCRCTL") in required and ("ibm-linkage-editor", "jcl-link-step", "IEWL") in required
    assert ("gnucobol", "runtime-setting", "COB_LIBRARY_PATH") in required and ("microfocus-cobol", "invocation", "mfcob") in required
    cobc = next(t for t in toolchain_requirements(recs) if t["name"] == "cobc")
    assert cobc["detail"]["standard"] == "-std=ibm" and cobc["detail"]["format"] == "free" and cobc["evidence"][0]["file"] == "build/Makefile"


# --- applications and entry points --------------------------------------------------------------------------------------


ESTATE = {
    "pay/PAYROLL.cbl": program("PAYROLL", "CALL 'TAXCALC'.", "COPY SHARED.", "EXEC SQL SELECT A INTO :X FROM HR.EMP END-EXEC."),
    "pay/TAXCALC.cbl": program("TAXCALC"),
    "pay/PAYJOB.jcl": "//PAYJOB JOB\n//S1 EXEC PGM=PAYROLL\n//EMP DD DSN=PROD.EMP,DISP=SHR\n//SHARE DD DSN=PROD.SHARED.DATA,DISP=SHR\n",
    "hr/HRRPT.cbl": program("HRRPT", "COPY SHARED.", "EXEC SQL SELECT A INTO :X FROM HR.EMP END-EXEC."),
    "hr/HRJOB.jcl": "//HRJOB JOB\n//S1 EXEC PGM=HRRPT\n//SHARE DD DSN=PROD.SHARED.DATA,DISP=SHR\n",
    "ord/ORDERS.cbl": program("ORDERS", "EXEC CICS LINK PROGRAM('PRICING') END-EXEC."),
    "ord/PRICING.cbl": program("PRICING"),
    "ord/CSD.jcl": "//CSD JOB\n//S1 EXEC PGM=DFHCSDUP\n//SYSIN DD *\n  DEFINE TRANSACTION(ORD1) GROUP(G) PROGRAM(ORDERS)\n/*\n",
    "cpy/SHARED.cpy": _fixed("01 SHARED-REC.", "    05 S-A PIC X.", "    05 S-B PIC X."),
    "orphan/LONE.cbl": program("LONE"),
    "asm/ASMUTIL.asm": "ASMUTIL CSECT\n BR 14\n",
}


def apps_of(files: dict[str, str], tmp_path: Path | None = None):
    recs = records(files)
    graph = build_graph(recs).graph
    return build_applications(recs, graph), graph


def test_applications_are_connected_components_with_named_entry_points() -> None:
    result, _ = apps_of(ESTATE)
    by_name = {a["name"]: a for a in result["applications"]}
    assert set(by_name) == {"PAYJOB", "HRJOB", "ORDERS", "LONE"}, "a lone assembler member is not an application; a CICS program names its application"
    assert by_name["PAYJOB"]["programs"] == ["PAYROLL", "TAXCALC"] and by_name["PAYJOB"]["jobs"] == ["PAYJOB"]
    assert by_name["ORDERS"]["programs"] == ["ORDERS", "PRICING"]
    assert by_name["LONE"]["programs"] == ["LONE"]
    assert all(a["id"].startswith("APP-") and len(a["id"]) == 12 for a in result["applications"])


def test_entry_point_kinds() -> None:
    result, _ = apps_of(ESTATE)
    kinds = {e["program"]: e["kinds"] for e in result["entry_points"]}
    assert kinds["PAYROLL"] == ["batch-job-step"] and kinds["TAXCALC"] == ["called-subprogram"] and kinds["PRICING"] == ["called-subprogram"]
    assert kinds["ORDERS"] == ["cics-transaction-program"] and kinds["LONE"] == ["unreferenced-program"]
    payroll = next(e for e in result["entry_points"] if e["program"] == "PAYROLL")
    assert payroll["invoked_by"] == ["job:PAYJOB"] and payroll["file"] == "pay/PAYROLL.cbl"
    pay = next(a for a in result["applications"] if a["name"] == "PAYJOB")
    assert [e["program"] for e in pay["entry_points"]] == ["PAYROLL"]


def test_cross_application_relationships_through_shared_tables_datasets_and_copybooks() -> None:
    result, _ = apps_of(ESTATE)
    shared = {r["resource"]: {a["name"] for a in r["applications"]} for r in result["relationships"]}
    assert shared["table:HR.EMP"] == {"PAYJOB", "HRJOB"} and shared["dataset:PROD.SHARED.DATA"] == {"PAYJOB", "HRJOB"}
    assert shared["copybook:SHARED"] == {"PAYJOB", "HRJOB"}
    assert "dataset:PROD.EMP" not in shared, "a resource used by one application is not a relationship"


def test_application_readiness_reflects_blockers_unsupported_features_and_compile_errors(tmp_path: Path) -> None:
    files = {**ESTATE, "pay/EXTRA.cbl": program("EXTRA", "CALL 'MISSINGPGM'."), "pay/EXTRAJOB.jcl": "//EXTRAJOB JOB\n//S1 EXEC PGM=EXTRA\n"}
    recs = records(files)
    graph = build_graph(recs).graph
    root = tmp_path / "src"
    for path, text in files.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(text, encoding="utf-8")
    compat = assess_compatibility(recs, graph, root, LOCAL, runner=FakeCobc())
    states = {a["name"]: a["readiness"] for a in build_applications(recs, graph, compat)["applications"]}
    assert states["EXTRAJOB"] == "BLOCKED" and states["ORDERS"] == "NOT_SUPPORTED" and states["LONE"] == "READY"
    assert states["PAYJOB"] == "NOT_SUPPORTED", "Db2 SQL is a precompiler feature"


def test_application_ids_do_not_depend_on_input_order() -> None:
    first, _ = apps_of(ESTATE)
    second, _ = apps_of(dict(reversed(list(ESTATE.items()))))
    assert first == second


# --- readiness decision --------------------------------------------------------------------------------------------------------


def report_for(files: dict[str, str], backend: CompilerBackend, tmp_path: Path) -> dict:
    from enterprise.discovery.report import completeness

    recs = records(files)
    graph = build_graph(recs).graph
    for path, text in files.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text, encoding="utf-8")
    compat = assess_compatibility(recs, graph, tmp_path, backend, runner=FakeCobc())
    return {"completeness": completeness(recs, graph, checkpoint_ok=True, expected_files=len(recs)), "compatibility": compat,
            "applications": build_applications(recs, graph, compat)}


def test_readiness_is_blocked_not_supported_or_ready(tmp_path: Path) -> None:
    none = CompilerBackend("none", reason="x")
    blocked = evaluate_readiness(report_for({"a/P.cbl": program("P", "CALL 'GONE'.")}, none, tmp_path))
    assert blocked["status"] == "BLOCKED" and blocked["allowed"] is False
    assert blocked["blockers"][0]["id"] == "no-blocking-unresolved-references"
    assert "program:GONE at a/P.cbl:4" in describe_blockers(blocked)

    unsupported = evaluate_readiness(report_for({"a/P.cbl": program("P", "EXEC CICS RETURN END-EXEC.")}, none, tmp_path))
    assert unsupported["status"] == "NOT_SUPPORTED" and unsupported["allowed"] is True
    assert unsupported["unsupported"][0]["feature"] == "exec-cics" and unsupported["unsupported_total"] == 1

    ready = evaluate_readiness(report_for({"a/P.cbl": program("P")}, LOCAL, tmp_path))
    assert ready["status"] == "READY" and ready["allowed"] is True and ready["unsupported"] == [] and ready["unverified"] == []


def test_a_missing_compiler_never_blocks_and_never_pretends_ready_means_compiled(tmp_path: Path) -> None:
    report = report_for({"a/P.cbl": program("P")}, CompilerBackend("none", reason="no cobc on PATH"), tmp_path)
    gate = evaluate_readiness(report)
    assert gate["status"] == "NOT_SUPPORTED" and gate["allowed"] is True
    assert gate["unverified"] == [{"file": "a/P.cbl", "reason": "NOT_ATTEMPTED_NO_COMPILER"}]
    assert report["applications"]["applications"][0]["readiness"] == "NOT_SUPPORTED"
    assert report["compatibility"]["programs"][0]["verdict"] == "NOT_ATTEMPTED_NO_COMPILER"


def test_compile_errors_make_the_application_not_supported_with_the_diagnostics(tmp_path: Path) -> None:
    runner = FakeCobc()
    root = tmp_path / "s"
    files = {"a/BAD.cbl": program("BAD", "BADSYNTAX.")}
    (root / "a").mkdir(parents=True)
    (root / "a/BAD.cbl").write_text(files["a/BAD.cbl"], encoding="utf-8")
    recs = records(files)
    graph = build_graph(recs).graph
    compat = assess_compatibility(recs, graph, root, LOCAL, runner=runner)
    from enterprise.discovery.report import completeness

    report = {"completeness": completeness(recs, graph, checkpoint_ok=True, expected_files=1), "compatibility": compat,
              "applications": build_applications(recs, graph, compat)}
    readiness = evaluate_readiness(report)
    assert readiness["status"] == "NOT_SUPPORTED" and readiness["compile_errors"][0]["diagnostics"][0]["line"] == 4


def test_gnucobol_dialect_is_never_asserted_for_ibm_only_sources(tmp_path: Path) -> None:
    report = assess({"a/IBM.cbl": "CBL SQL\n" + program("IBM")}, tmp_path, dialects={"a/IBM.cbl": "ibm-enterprise"})
    assert report["programs"][0]["dialect"] == "ibm-enterprise" and "not that it behaves like the customer's production compiler" in report["basis"]
