"""JCL job -> Java batch orchestrator (roadmap units 6 and 8).

A JCL job is a sequence of steps; each step runs a program with its DD statements bound
to datasets. ``plan_job`` turns a parsed job into a ``JobPlan`` and ``render_runner``
writes ``JclJobRunner.java``: a plain-Java launcher that runs the steps in order, binding
each step's DD names through ``DD_<name>`` environment variables (the ddname resolution
certified in unit 4 against GnuCOBOL), keeping each step's return code, applying
``COND=(code,op[,step])`` bypass rules, and exiting with the highest return code.

Datasets are files under a data directory: ``HR.MASTER`` -> ``<data>/HR.MASTER``,
``&&WORK`` -> ``<data>/_tmp/WORK``, generation ``HR.GDG(+1)`` -> ``<data>/HR.GDG.G0002V00``.
Dispositions are honoured: a dataset that is NEW and not catalogued or kept is deleted at the
end of the step, OLD/SHR must exist, an allocated-but-unwritten NEW,CATLG dataset exists
(empty) after the step.

Unit 8 adds, run natively by the launcher (no program of the application involved):

- ``IEFBR14`` (allocation/deletion by disposition only),
- ``IEBGENER`` (copy ``SYSUT1`` to ``SYSUT2``),
- ``IDCAMS`` with an inline ``SYSIN``: ``DELETE``, ``DEFINE GDG (NAME LIMIT)``,
  ``REPRO INFILE OUTFILE`` and ``SET MAXCC``,
- GDG relative generations ``(0)``, ``(-n)`` and ``(+1)`` against a catalogue entry created
  by ``DEFINE GDG``; the oldest generation rolls off when the limit is exceeded,
- inline ``DD *`` data, written to a temporary file for the step.

No IBM utility or JES is available as an oracle: these behaviours are implemented from the
documented semantics and tested against them (``SIMULATOR``-grade evidence, not a mainframe
equivalence claim). Nothing is guessed: a job that uses anything outside this subset gets
``refusals`` and no runner (fail closed): other utilities or IDCAMS commands, ``COND=ONLY`` /
``EVEN`` combinations, unparsable COND, PDS members, ``(+2)`` and later generations, a job
still carrying unexpanded procedures, IF blocks or JOBLIB datasets, DD names the lowering
does not certify. Abends are not modelled: a step "fails" by returning a non-zero code, and
a JCL error (missing OLD dataset, duplicate NEW,CATLG, unknown generation) ends the job with
exit status 255.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from engine.transformation.ir import JclApplication, JclDD, JclJob

_OPERATORS = frozenset({"GT", "GE", "EQ", "NE", "LT", "LE"})
_DDNAME = re.compile(r"[A-Z][A-Z0-9-]{0,29}")
_GENERATION = re.compile(r"([A-Z0-9#$@.-]+)\(([+-]?\d+)\)")
_COND_TEST = re.compile(r"\(\s*(\d+)\s*,\s*([A-Za-z]{2})\s*(?:,\s*([A-Za-z0-9#$@.]+)\s*)?\)")
UTILITIES = frozenset({"IEFBR14", "IEBGENER", "IDCAMS"})


@dataclass(frozen=True)
class CondTest:
    code: int
    op: str
    step: str = ""  # empty: every preceding step


@dataclass(frozen=True)
class DdPlan:
    name: str
    path: str = ""  # dataset path relative to the data directory
    gdg_base: str = ""  # set for a relative generation reference
    gdg_rel: int = 0
    status: str = "NEW"  # NEW | OLD | SHR | MOD
    normal: str = "DELETE"  # disposition at normal step end: KEEP | DELETE | CATLG | PASS
    inline: tuple[str, ...] | None = None
    dummy: bool = False


@dataclass(frozen=True)
class StepPlan:
    name: str
    program: str
    main_class: str  # "" for a utility
    dds: tuple[DdPlan, ...]
    conds: tuple[CondTest, ...] = ()
    utility: str = ""
    commands: tuple[tuple[str, ...], ...] = ()  # IDCAMS commands


@dataclass(frozen=True)
class JobPlan:
    job: str
    steps: tuple[StepPlan, ...] = ()
    refusals: tuple[str, ...] = ()

    @property
    def runnable(self) -> bool:
        return not self.refusals and bool(self.steps)

    @property
    def gdg_bases(self) -> tuple[str, ...]:
        return tuple(sorted({d.gdg_base for s in self.steps for d in s.dds if d.gdg_base}))


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


def parse_disposition(text: str) -> tuple[str, str]:
    """``(status, normal)`` of a DISP value, with the JCL defaults (NEW; deleted unless kept)."""
    body = (text or "").strip()
    if body.startswith("(") and body.endswith(")"):
        body = body[1:-1]
    parts = [p.strip().upper() for p in body.split(",")]
    status = parts[0] or "NEW"
    normal = parts[1] if len(parts) > 1 and parts[1] else ("DELETE" if status == "NEW" else "KEEP")
    return status, normal


def parse_idcams(records: tuple[str, ...]) -> tuple[tuple[tuple[str, ...], ...], list[str]]:
    """Commands and refusals of an IDCAMS ``SYSIN`` stream."""
    text = re.sub(r"/\*.*?\*/", " ", "\n".join(records), flags=re.S)
    commands: list[tuple[str, ...]] = []
    refusals: list[str] = []
    joined = re.sub(r"[-+]\s*\n", " ", text)  # continuation: a trailing '-' or '+'
    for raw in joined.splitlines():
        line = " ".join(raw.split())
        if not line:
            continue
        upper = line.upper()
        if m := re.fullmatch(r"DELETE\s+\(?\s*([A-Z0-9#$@.]+)\s*\)?((?:\s+[A-Z]+)*)", upper):
            flags = m.group(2).split()
            extra = [f for f in flags if f not in {
                "PURGE", "SCRATCH", "NOSCRATCH", "NONVSAM", "CLUSTER", "GDG", "FORCE"}]
            if extra:
                refusals.append(f"IDCAMS DELETE option {extra[0]} is not supported")
            else:
                commands.append(("DELETE", m.group(1)))
        elif m := re.fullmatch(
                r"DEFINE\s+GDG\s*\(\s*NAME\s*\(\s*([A-Z0-9#$@.]+)\s*\)\s*LIMIT\s*\(\s*(\d+)\s*\)"
                r"((?:\s+(?:NOEMPTY|SCRATCH|NOSCRATCH))*)\s*\)", upper):
            limit = int(m.group(2))
            if not 1 <= limit <= 255:
                refusals.append(f"IDCAMS DEFINE GDG LIMIT({limit}) is outside 1..255")
            else:
                commands.append(("DEFINE_GDG", m.group(1), str(limit)))
        elif m := re.fullmatch(
                r"REPRO\s+INFILE\s*\(\s*([A-Z][A-Z0-9-]*)\s*\)\s+OUTFILE\s*\(\s*([A-Z][A-Z0-9-]*)\s*\)",
                upper):
            commands.append(("REPRO", m.group(1), m.group(2)))
        elif m := re.fullmatch(r"SET\s+MAXCC\s*=\s*(\d+)", upper):
            commands.append(("SET_MAXCC", m.group(1)))
        else:
            refusals.append(f"IDCAMS command is outside the supported subset: {line}")
    if not commands and not refusals:
        refusals.append("IDCAMS SYSIN carries no command")
    return tuple(commands), refusals


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
        utility = program if program in UTILITIES else ""
        main_class = "" if utility else program_classes.get(program, "")
        if not utility and not main_class:
            refusals.append(
                f"{where}: program {program} is neither a COBOL program of the application "
                f"nor a supported utility ({', '.join(sorted(UTILITIES))})")
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
        dds: list[DdPlan] = []
        for dd in step.dd_statements:
            bound = _bind(dd, where, bool(utility), refusals)
            if bound:
                dds.append(bound)
        commands: tuple[tuple[str, ...], ...] = ()
        if utility:
            commands = _check_utility(utility, step, dds, where, refusals)
        steps.append(StepPlan(step.name, program, main_class, tuple(dds), conds, utility, commands))
    if not steps:
        refusals.append("the job has no steps")
    return JobPlan(job.name, tuple(steps), tuple(refusals))


def _check_utility(utility, step, dds, where, refusals) -> tuple[tuple[str, ...], ...]:
    names = {d.name for d in dds}
    if utility == "IEBGENER":
        for needed in ("SYSUT1", "SYSUT2"):
            if needed not in names:
                refusals.append(f"{where}: IEBGENER needs a {needed} DD")
        return ()
    if utility == "IDCAMS":
        sysin = next((dd for dd in step.dd_statements if dd.name.upper() == "SYSIN"), None)
        if sysin is None or not sysin.is_inline:
            refusals.append(f"{where}: IDCAMS needs an inline SYSIN (DD *)")
            return ()
        commands, problems = parse_idcams(sysin.inline_data)
        refusals.extend(f"{where}: {p}" for p in problems)
        for command in commands:
            if command[0] == "REPRO":
                for ddname in command[1:]:
                    if ddname not in names:
                        refusals.append(f"{where}: REPRO names DD {ddname}, which the step lacks")
        return commands
    return ()


def _bind(dd: JclDD, where: str, utility: bool, refusals: list[str]) -> DdPlan | None:
    if dd.sysout:
        return None  # program output goes to stdout
    name = dd.name.upper()
    if dd.is_dummy:
        if not utility:
            refusals.append(f"{where}: DD {name} DUMMY on a program step is not supported")
            return None
        return DdPlan(name, dummy=True)
    if not _DDNAME.fullmatch(name):
        refusals.append(f"{where}: DD name {name} is not a certified plain ddname")
        return None
    if dd.is_inline:
        return DdPlan(name, inline=tuple(dd.inline_data), status="OLD", normal="DELETE")
    if not dd.dataset:
        refusals.append(f"{where}: DD {name} names no dataset")
        return None
    status, normal = parse_disposition(dd.disposition)
    if status not in {"NEW", "OLD", "SHR", "MOD"}:
        refusals.append(f"{where}: DD {name} has disposition status {status}")
        return None
    generation = _GENERATION.fullmatch(dd.dataset.upper())
    if "(" in dd.dataset and not generation:
        refusals.append(f"{where}: DD {name} uses a PDS member ({dd.dataset})")
        return None
    if generation:
        relative = int(generation.group(2))
        if relative > 1:
            refusals.append(f"{where}: DD {name} uses generation ({relative:+d}); only (+1) is supported")
            return None
        return DdPlan(name, gdg_base=generation.group(1), gdg_rel=relative, status=status, normal=normal)
    return DdPlan(name, path=dataset_path(dd.dataset), status=status, normal=normal)


def _java(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _java_dd(dd: DdPlan) -> str:
    inline = "null" if dd.inline is None else (
        "new String[] {" + ", ".join(_java(r) for r in dd.inline) + "}")
    return (
        f"new Dd({_java(dd.name)}, {_java(dd.path)}, {_java(dd.gdg_base)}, {dd.gdg_rel}, "
        f"{_java(dd.status)}, {_java(dd.normal)}, {inline}, {'true' if dd.dummy else 'false'})")


def render_runner(plan: JobPlan, class_name: str = "JclJobRunner") -> str:
    """Java source of the launcher for ``plan`` (raises ``ValueError`` if refused)."""
    if not plan.runnable:
        raise ValueError(f"job {plan.job} is not runnable: " + "; ".join(plan.refusals))
    rows = []
    for step in plan.steps:
        dds = ", ".join(_java_dd(d) for d in step.dds)
        conds = ", ".join(
            f"new Cond({c.code}, {_java(c.op)}, {_java(c.step)})" for c in step.conds)
        commands = ", ".join(
            "{" + ", ".join(_java(p) for p in command) + "}" for command in step.commands)
        rows.append(
            f"        new Step({_java(step.name)}, {_java(step.main_class)}, {_java(step.utility)}, "
            f"new Dd[] {{{dds}}}, new Cond[] {{{conds}}}, new String[][] {{{commands}}})")
    bases = ", ".join(_java(b) for b in plan.gdg_bases)
    return (_TEMPLATE.replace("__CLASS__", class_name).replace("__JOB__", _java(plan.job))
            .replace("__STEPS__", ",\n".join(rows)).replace("__BASES__", bases))


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
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Runs the steps of JCL job __JOB__ in order. Program steps run one JVM each with DD names
 * bound through DD_<name> environment variables; IEFBR14, IEBGENER and IDCAMS run natively.
 * Datasets live under the data directory. Usage: java __CLASS__ [dataDir [classesDir]]
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

    static final class Dd {
        final String name;
        final String path;
        final String gdgBase;
        final int gdgRel;
        final String status;
        final String normal;
        final String[] inline;
        final boolean dummy;

        Dd(String name, String path, String gdgBase, int gdgRel, String status, String normal,
                String[] inline, boolean dummy) {
            this.name = name;
            this.path = path;
            this.gdgBase = gdgBase;
            this.gdgRel = gdgRel;
            this.status = status;
            this.normal = normal;
            this.inline = inline;
            this.dummy = dummy;
        }
    }

    static final class Step {
        final String name;
        final String main;
        final String utility;
        final Dd[] dds;
        final Cond[] conds;
        final String[][] commands;

        Step(String name, String main, String utility, Dd[] dds, Cond[] conds, String[][] commands) {
            this.name = name;
            this.main = main;
            this.utility = utility;
            this.dds = dds;
            this.conds = conds;
            this.commands = commands;
        }
    }

    /** A JCL error ends the job (exit status 255). */
    static final class JclError extends RuntimeException {
        JclError(String message) {
            super(message);
        }
    }

    static final Step[] STEPS = new Step[] {
__STEPS__
    };
    static final String[] GDG_BASES = new String[] {__BASES__};

    static Path data;
    /** Latest generation of each GDG base when the job started: (0), (-n) and (+1) are relative to it. */
    static final Map<String, Integer> LATEST = new HashMap<>();

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

    // ---- generation data groups ------------------------------------------------------------

    static Path catalog(String base) {
        return data.resolve("_catalog").resolve(base + ".gdg");
    }

    static Path generation(String base, int number) {
        return data.resolve(String.format("%s.G%04dV00", base, number));
    }

    static List<Integer> generations(String base) throws IOException {
        List<Integer> found = new ArrayList<>();
        Pattern pattern = Pattern.compile(Pattern.quote(base) + "\\\\.G(\\\\d{4})V00");
        if (Files.isDirectory(data)) {
            try (java.util.stream.Stream<Path> list = Files.list(data)) {
                for (Path p : (Iterable<Path>) list::iterator) {
                    Matcher m = pattern.matcher(p.getFileName().toString());
                    if (m.matches()) {
                        found.add(Integer.parseInt(m.group(1)));
                    }
                }
            }
        }
        Collections.sort(found);
        return found;
    }

    static int limit(String base) throws IOException {
        for (String line : Files.readAllLines(catalog(base))) {
            if (line.startsWith("LIMIT=")) {
                return Integer.parseInt(line.substring(6).trim());
            }
        }
        throw new JclError("catalog entry of " + base + " carries no LIMIT");
    }

    /** Remove the oldest generations beyond the base's limit (NOEMPTY roll-off). */
    static void rollOff(String base) throws IOException {
        List<Integer> all = generations(base);
        int max = limit(base);
        while (all.size() > max) {
            Files.deleteIfExists(generation(base, all.remove(0)));
        }
    }

    static Path resolve(Dd dd) throws IOException {
        if (dd.gdgBase.isEmpty()) {
            return data.resolve(dd.path);
        }
        Integer latest = LATEST.get(dd.gdgBase);
        int number = latest + dd.gdgRel;
        if (dd.gdgRel <= 0 && (number < 1 || !Files.exists(generation(dd.gdgBase, number)))) {
            throw new JclError("generation " + dd.gdgBase + "(" + dd.gdgRel + ") does not exist");
        }
        return generation(dd.gdgBase, number);
    }

    // ---- utilities -------------------------------------------------------------------------

    static int runUtility(Step step, Map<String, Path> files) throws IOException {
        switch (step.utility) {
            case "IEFBR14":
                return 0;
            case "IEBGENER": {
                Path in = files.get("SYSUT1");
                Path out = files.get("SYSUT2");
                if (in == null || out == null || !Files.exists(in)) {
                    return 12;
                }
                Files.createDirectories(out.getParent());
                Files.copy(in, out, StandardCopyOption.REPLACE_EXISTING);
                return 0;
            }
            case "IDCAMS":
                return idcams(step, files);
            default:
                throw new IllegalArgumentException(step.utility);
        }
    }

    static int idcams(Step step, Map<String, Path> files) throws IOException {
        int maxcc = 0;
        for (String[] command : step.commands) {
            int rc = 0;
            switch (command[0]) {
                case "DELETE": {
                    String name = command[1];
                    if (Files.exists(catalog(name))) {
                        for (int n : generations(name)) {
                            Files.deleteIfExists(generation(name, n));
                        }
                        Files.delete(catalog(name));
                    } else if (Files.exists(data.resolve(name))) {
                        Files.delete(data.resolve(name));
                    } else {
                        rc = 8;
                    }
                    break;
                }
                case "DEFINE_GDG":
                    if (Files.exists(catalog(command[1]))) {
                        rc = 12;
                    } else {
                        Files.createDirectories(catalog(command[1]).getParent());
                        Files.write(catalog(command[1]), ("LIMIT=" + command[2] + "\\n").getBytes());
                    }
                    break;
                case "REPRO": {
                    Path in = files.get(command[1]);
                    Path out = files.get(command[2]);
                    if (in == null || out == null || !Files.exists(in)) {
                        rc = 12;
                    } else {
                        Files.createDirectories(out.getParent());
                        Files.copy(in, out, StandardCopyOption.REPLACE_EXISTING);
                    }
                    break;
                }
                case "SET_MAXCC":
                    maxcc = Integer.parseInt(command[1]);
                    continue;
                default:
                    throw new IllegalArgumentException(command[0]);
            }
            maxcc = Math.max(maxcc, rc);
        }
        return maxcc;
    }

    // ---- job -------------------------------------------------------------------------------

    static void deleteTree(Path root) throws IOException {
        if (Files.isDirectory(root)) {
            try (java.util.stream.Stream<Path> walk = Files.walk(root)) {
                walk.sorted(java.util.Comparator.reverseOrder()).forEach(p -> p.toFile().delete());
            }
        }
    }

    static int runStep(Step step, String classes) throws IOException, InterruptedException {
        Map<String, Path> files = new HashMap<>();
        List<Path> inlineFiles = new ArrayList<>();
        for (Dd dd : step.dds) {
            if (dd.dummy) {
                continue;
            }
            Path file;
            if (dd.inline != null) {
                file = data.resolve("_tmp").resolve("inline-" + step.name + "-" + dd.name);
                Files.createDirectories(file.getParent());
                Files.write(file, (String.join("\\n", dd.inline) + "\\n").getBytes());
                inlineFiles.add(file);
            } else {
                file = resolve(dd);
                if ((dd.status.equals("OLD") || dd.status.equals("SHR")) && !Files.exists(file)) {
                    throw new JclError("dataset " + file.getFileName() + " (DD " + dd.name + ") not found");
                }
                if (dd.status.equals("NEW") && dd.normal.equals("CATLG") && Files.exists(file)) {
                    throw new JclError("dataset " + file.getFileName() + " (DD " + dd.name + ") already exists");
                }
                Files.createDirectories(file.getParent());
            }
            files.put(dd.name, file);
        }
        int rc;
        if (!step.utility.isEmpty()) {
            rc = runUtility(step, files);
        } else {
            ProcessBuilder pb = new ProcessBuilder("java", "-cp", classes, step.main);
            pb.inheritIO();
            for (Map.Entry<String, Path> e : files.entrySet()) {
                pb.environment().put("DD_" + e.getKey(), e.getValue().toString());
            }
            rc = pb.start().waitFor();
        }
        for (Dd dd : step.dds) {
            if (dd.dummy || dd.inline != null) {
                continue;
            }
            Path file = files.get(dd.name);
            if (dd.normal.equals("DELETE")) {
                Files.deleteIfExists(file);
            } else if (dd.status.equals("NEW") && !Files.exists(file)) {
                Files.createFile(file);  // allocated, never written: an empty dataset
            }
        }
        for (Path file : inlineFiles) {
            Files.deleteIfExists(file);
        }
        return rc;
    }

    public static void main(String[] args) throws Exception {
        data = Paths.get(args.length > 0 ? args[0] : "data").toAbsolutePath();
        String classes = args.length > 1 ? args[1] : "classes";
        Map<String, Integer> codes = new HashMap<>();
        List<Integer> all = new ArrayList<>();
        int max = 0;
        try {
            for (String base : GDG_BASES) {
                if (!Files.exists(catalog(base))) {
                    throw new JclError("GDG base " + base + " is not defined");
                }
                List<Integer> existing = generations(base);
                LATEST.put(base, existing.isEmpty() ? 0 : existing.get(existing.size() - 1));
            }
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
                int rc = runStep(step, classes);
                codes.put(step.name, rc);
                all.add(rc);
                max = Math.max(max, rc);
                System.out.println("JCL step " + step.name + " RC=" + rc);
                System.out.flush();
            }
            for (String base : GDG_BASES) {
                rollOff(base);
            }
        } catch (JclError e) {
            System.out.println("JCL ERROR " + e.getMessage());
            System.out.flush();
            deleteTree(data.resolve("_tmp"));
            System.exit(255);
        }
        deleteTree(data.resolve("_tmp"));
        System.out.println("JCL job " + __JOB__ + " MAXRC=" + max);
        System.out.flush();
        System.exit(max);
    }
}
"""
