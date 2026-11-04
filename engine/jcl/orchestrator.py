"""JCL job -> Java batch orchestrator (roadmap unit 6).

A JCL job is a sequence of steps; each step runs a program with its DD statements bound
to datasets. ``plan_job`` turns a parsed job into a ``JobPlan`` and ``render_runner``
writes ``JclJobRunner.java``: a plain-Java launcher that runs the steps in order, one
JVM per step, binding each step's DD names through ``DD_<name>`` environment variables
(the ddname resolution certified in unit 4 against GnuCOBOL), keeping each step's return
code, applying ``COND=(code,op[,step])`` bypass rules, and exiting with the highest
return code.

Datasets map to files under a data directory: ``HR.MASTER`` -> ``<data>/HR.MASTER``,
``&&WORK`` -> ``<data>/_tmp/WORK``. Nothing is guessed: a job that uses anything outside
this subset gets ``refusals`` and no runner (fail closed):

- a step that is not a COBOL program of the application (utilities are roadmap unit 8),
- inline ``DD *``, GDG generations or PDS members, DD names the lowering does not certify,
- ``COND=ONLY`` / ``EVEN`` combinations and COND text that is not ``(code,op[,step])``,
- a job still carrying unexpanded procedures, IF blocks or JOBLIB/STEPLIB datasets.

Abends are not modelled: a step "fails" by returning a non-zero code. SYSOUT DDs are not
bound (the program's own output goes to the process stdout).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from engine.transformation.ir import JclApplication, JclDD, JclJob

_OPERATORS = frozenset({"GT", "GE", "EQ", "NE", "LT", "LE"})
_DDNAME = re.compile(r"[A-Z][A-Z0-9-]{0,29}")
_GDG_OR_MEMBER = re.compile(r"\(.*\)")
_COND_TEST = re.compile(r"\(\s*(\d+)\s*,\s*([A-Za-z]{2})\s*(?:,\s*([A-Za-z0-9#$@.]+)\s*)?\)")


@dataclass(frozen=True)
class CondTest:
    code: int
    op: str
    step: str = ""  # empty: every preceding step


@dataclass(frozen=True)
class StepPlan:
    name: str
    program: str
    main_class: str
    dds: tuple[tuple[str, str], ...]  # (ddname, path relative to the data directory)
    conds: tuple[CondTest, ...] = ()


@dataclass(frozen=True)
class JobPlan:
    job: str
    steps: tuple[StepPlan, ...] = ()
    refusals: tuple[str, ...] = ()

    @property
    def runnable(self) -> bool:
        return not self.refusals and bool(self.steps)


def dataset_path(dsn: str) -> str:
    """Path of a dataset under the data directory (``&&NAME`` is job-temporary)."""
    return f"_tmp/{dsn[2:]}" if dsn.startswith("&&") else dsn


def parse_cond(text: str) -> tuple[CondTest, ...] | None:
    """``(4,LT)`` / ``((4,LT),(8,EQ,STEP1))`` -> tests; ``None`` when not in that form."""
    body = text.strip()
    if body.startswith("(") and body.endswith(")") and body.count("(") > 1:
        body = body[1:-1]  # ((a,b),(c,d)) -> (a,b),(c,d)
    pieces = _COND_TEST.findall(body)
    rebuilt = ",".join(f"({c},{o}" + (f",{s}" if s else "") + ")" for c, o, s in pieces)
    if not pieces or re.sub(r"\s+", "", body) != rebuilt.replace(" ", ""):
        return None
    tests = tuple(CondTest(int(c), o.upper(), s.upper()) for c, o, s in pieces)
    return None if any(t.op not in _OPERATORS for t in tests) else tests


def plan_job(job: JclJob, program_classes: dict[str, str]) -> JobPlan:
    """Plan ``job``; ``program_classes`` maps PROGRAM-ID (upper case) to its main class."""
    refusals: list[str] = []
    if job.job_dd_statements:
        refusals.append("job-level DD statements (JOBLIB/JOBCAT) are not modelled")
    steps: list[StepPlan] = []
    for step in job.steps:
        where = f"step {step.name}"
        exec_ = step.exec_
        program = (exec_.program if exec_ else "").upper()
        if not program:
            refusals.append(f"{where}: no PGM= (unexpanded procedure or empty EXEC)")
            continue
        main_class = program_classes.get(program, "")
        if not main_class:
            refusals.append(f"{where}: program {program} is not a COBOL program of the application")
        condition = step.condition
        conds: tuple[CondTest, ...] = ()
        if condition is not None and condition.condition_type == "IF":
            refusals.append(f"{where}: IF/THEN/ELSE blocks are not evaluated")
        elif condition is not None:
            parsed = parse_cond(condition.code)
            if parsed is None:
                refusals.append(
                    f"{where}: COND={condition.code} is outside the supported (code,op[,step]) form")
            else:
                conds = parsed
        dds: list[tuple[str, str]] = []
        for dd in step.dd_statements:
            bound = _bind(dd, where, refusals)
            if bound:
                dds.append(bound)
        steps.append(StepPlan(step.name, program, main_class, tuple(dds), conds))
    if not steps:
        refusals.append("the job has no steps")
    return JobPlan(job.name, tuple(steps), tuple(refusals))


def _bind(dd: JclDD, where: str, refusals: list[str]) -> tuple[str, str] | None:
    if dd.sysout:
        return None  # program output goes to stdout
    name = dd.name.upper()
    if dd.is_inline:
        refusals.append(f"{where}: inline data (DD {name} *) is not supported")
        return None
    if not dd.dataset:
        refusals.append(f"{where}: DD {name} names no dataset")
        return None
    if _GDG_OR_MEMBER.search(dd.dataset):
        refusals.append(f"{where}: DD {name} uses a GDG generation or PDS member ({dd.dataset})")
        return None
    if not _DDNAME.fullmatch(name):
        refusals.append(f"{where}: DD name {name} is not a certified plain ddname")
        return None
    return name, dataset_path(dd.dataset)


def _java(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render_runner(plan: JobPlan, class_name: str = "JclJobRunner") -> str:
    """Java source of the launcher for ``plan`` (raises ``ValueError`` if refused)."""
    if not plan.runnable:
        raise ValueError(f"job {plan.job} is not runnable: " + "; ".join(plan.refusals))
    rows = []
    for step in plan.steps:
        dds = ", ".join(f"{{{_java(n)}, {_java(p)}}}" for n, p in step.dds)
        conds = ", ".join(
            f"new Cond({c.code}, {_java(c.op)}, {_java(c.step)})" for c in step.conds)
        rows.append(
            f"        new Step({_java(step.name)}, {_java(step.main_class)}, "
            f"new String[][] {{{dds}}}, new Cond[] {{{conds}}})")
    table = ",\n".join(rows)
    return _TEMPLATE.replace("__CLASS__", class_name).replace(
        "__JOB__", _java(plan.job)).replace("__STEPS__", table)


@dataclass(frozen=True)
class OrchestrationResult:
    plans: tuple[JobPlan, ...]
    files: dict[str, str]  # runner class name -> Java source, runnable jobs only


def orchestrate(app: JclApplication, program_classes: dict[str, str]) -> OrchestrationResult:
    """Plan every job of ``app``; render a runner for each job that can be run."""
    plans = tuple(plan_job(job, program_classes) for job in app.jobs)
    files: dict[str, str] = {}
    for plan in plans:
        if plan.runnable:
            name = "Job" + re.sub(r"[^A-Za-z0-9]", "", plan.job.title()) + "Runner"
            files[name] = render_runner(plan, name)
    return OrchestrationResult(plans, files)


_TEMPLATE = """\
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Runs the steps of JCL job __JOB__ in order, one JVM per step. DD names are bound
 * through DD_<name> environment variables; datasets live under the data directory.
 * Usage: java __CLASS__ [dataDir [classesDir]]
 */
public class __CLASS__ {
    static final class Cond {
        final int code;
        final String op;
        final String step;

        Cond(int code, String op, String step) {
            this.code = code;
            this.op = op;
            this.step = step;
        }
    }

    static final class Step {
        final String name;
        final String main;
        final String[][] dds;
        final Cond[] conds;

        Step(String name, String main, String[][] dds, Cond[] conds) {
            this.name = name;
            this.main = main;
            this.dds = dds;
            this.conds = conds;
        }
    }

    static final Step[] STEPS = new Step[] {
__STEPS__
    };

    /** COND=(code,op): the step is bypassed when "code op rc" holds. */
    static boolean holds(int code, String op, int rc) {
        switch (op) {
            case "GT": return code > rc;
            case "GE": return code >= rc;
            case "EQ": return code == rc;
            case "NE": return code != rc;
            case "LT": return code < rc;
            case "LE": return code <= rc;
            default: throw new IllegalArgumentException(op);
        }
    }

    public static void main(String[] args) throws Exception {
        Path data = Paths.get(args.length > 0 ? args[0] : "data").toAbsolutePath();
        String classes = args.length > 1 ? args[1] : "classes";
        Map<String, Integer> codes = new HashMap<>();
        List<Integer> all = new ArrayList<>();
        int max = 0;
        for (Step step : STEPS) {
            boolean bypass = false;
            for (Cond cond : step.conds) {
                if (cond.step.isEmpty()) {
                    for (int rc : all) {
                        if (holds(cond.code, cond.op, rc)) {
                            bypass = true;
                        }
                    }
                } else {
                    Integer rc = codes.get(cond.step);
                    if (rc != null && holds(cond.code, cond.op, rc)) {
                        bypass = true;
                    }
                }
            }
            if (bypass) {
                System.out.println("JCL step " + step.name + " BYPASSED");
                System.out.flush();
                continue;
            }
            ProcessBuilder pb = new ProcessBuilder("java", "-cp", classes, step.main);
            pb.inheritIO();
            for (String[] dd : step.dds) {
                Path file = data.resolve(dd[1]);
                Files.createDirectories(file.getParent());
                pb.environment().put("DD_" + dd[0], file.toString());
            }
            int rc = pb.start().waitFor();
            codes.put(step.name, rc);
            all.add(rc);
            max = Math.max(max, rc);
            System.out.println("JCL step " + step.name + " RC=" + rc);
            System.out.flush();
        }
        Path temp = data.resolve("_tmp");
        if (Files.isDirectory(temp)) {
            try (java.util.stream.Stream<Path> walk = Files.walk(temp)) {
                walk.sorted(java.util.Comparator.reverseOrder()).forEach(p -> p.toFile().delete());
            }
        }
        System.out.println("JCL job " + __JOB__ + " MAXRC=" + max);
        System.out.flush();
        System.exit(max);
    }
}
"""
