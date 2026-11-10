"""Reference driver for a JCL job: the same job as shell steps over GnuCOBOL-compiled programs (roadmap unit 40).

The generated Java runner (``engine.jcl.orchestrator``) runs the job on generated Java. This module writes the
*reference* of that run: a POSIX shell script that performs the same job with the COBOL programs compiled by GnuCOBOL,
so the job lane can compare the two. The script implements the documented JCL semantics independently of the Java
template (dataset allocation and disposition, ``COND`` bypass, return codes, ``IEFBR14`` / ``IEBGENER``, inline ``DD *``
data, JCL errors with exit status 255); only the job plan (steps, ddnames, dataset paths, ``COND`` tests) is shared.

Fail closed: a job the reference cannot reproduce (``IDCAMS``, generation datasets) raises
:class:`ReferenceUnavailable`; such a job is never reported as verified.

Usage of the script: ``sh reference.sh <data dir> <dir of the compiled programs>``.
"""

from __future__ import annotations

import shlex

from engine.jcl.orchestrator import DdPlan, JobPlan, StepPlan


class ReferenceUnavailable(ValueError):
    """The reference driver cannot reproduce the job; ``reasons`` says why."""

    def __init__(self, reasons: tuple[str, ...]) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = reasons


def _reasons(plan: JobPlan) -> tuple[str, ...]:
    reasons: list[str] = []
    if plan.gdg_bases:
        reasons.append("generation data groups are not reproduced by the reference driver")
    for step in plan.steps:
        if step.utility == "IDCAMS":
            reasons.append(f"step {step.name}: IDCAMS is not reproduced by the reference driver")
    return tuple(reasons)


def _q(text: str) -> str:
    return shlex.quote(text)


def _dd_var(step_index: int, dd_index: int) -> str:
    return f"F_{step_index}_{dd_index}"


def _dd_lines(step: StepPlan, step_index: int) -> list[str]:
    lines: list[str] = []
    for dd_index, dd in enumerate(step.dds):
        if dd.dummy:
            continue
        var = _dd_var(step_index, dd_index)
        if dd.inline is not None:
            lines.append(f'{var}="$DATA/_tmp/inline-{step.name}-{dd.name}"')
            lines.append('mkdir -p "$(dirname "$' + var + '")"')
            rows = " ".join(_q(row) for row in dd.inline)
            lines.append(f"printf '%s\\n' {rows} > \"${var}\"")
            continue
        lines.append(f'{var}="$DATA/"{_q(dd.path)}')
        base = dd.path.rsplit("/", 1)[-1]
        if dd.status in ("OLD", "SHR"):
            lines.append(
                f'[ -e "${var}" ] || jerr {_q(f"dataset {base} (DD {dd.name}) not found")}')
        if dd.status == "NEW" and dd.normal == "CATLG":
            lines.append(
                f'[ ! -e "${var}" ] || jerr {_q(f"dataset {base} (DD {dd.name}) already exists")}')
        lines.append(f'mkdir -p "$(dirname "${var}")"')
    return lines


def _dd_by_name(step: StepPlan, step_index: int) -> dict[str, str]:
    return {
        dd.name: _dd_var(step_index, dd_index)
        for dd_index, dd in enumerate(step.dds)
        if not dd.dummy
    }


def _run_lines(step: StepPlan, step_index: int) -> list[str]:
    files = _dd_by_name(step, step_index)
    if step.utility == "IEFBR14":
        return ["rc=0"]
    if step.utility == "IEBGENER":
        if "SYSUT1" not in files or "SYSUT2" not in files:
            return ["rc=12"]
        src, dst = files["SYSUT1"], files["SYSUT2"]
        return [
            f'if [ ! -e "${src}" ]; then rc=12; else mkdir -p "$(dirname "${dst}")"; cp -f "${src}" "${dst}"; rc=0; fi'
        ]
    env = " ".join(f'DD_{name}="${var}"' for name, var in files.items())
    return [f'env {env} "$BIN/{step.program}"'.replace("env  ", "env "), "rc=$?"]


def _post_lines(step: StepPlan, step_index: int) -> list[str]:
    lines: list[str] = []
    inline: list[str] = []
    for dd_index, dd in enumerate(step.dds):
        if dd.dummy:
            continue
        var = _dd_var(step_index, dd_index)
        if dd.inline is not None:
            inline.append(var)
        elif dd.normal == "DELETE":
            lines.append(f'rm -f "${var}"')
        elif dd.status == "NEW":
            lines.append(f'[ -e "${var}" ] || : > "${var}"')
    lines.extend(f'rm -f "${var}"' for var in inline)
    return lines


def _cond_lines(step: StepPlan, index_of: dict[str, int], step_index: int) -> list[str]:
    lines: list[str] = []
    for cond in step.conds:
        test = f"holds {cond.code} {cond.op}"
        if not cond.step:
            lines.append(f'for rc in $ALL; do if {test} "$rc"; then bypass=1; fi; done')
        elif cond.step in index_of and index_of[cond.step] < step_index:
            var = f"RC_{index_of[cond.step]}"
            lines.append(f'if [ -n "${{{var}+x}}" ] && {test} "${var}"; then bypass=1; fi')
    return lines


def render_reference(plan: JobPlan) -> str:
    """The reference shell script of ``plan`` (raises :class:`ReferenceUnavailable` or ``ValueError``)."""
    if not plan.runnable:
        raise ValueError(f"job {plan.job} is not runnable: " + "; ".join(plan.refusals))
    reasons = _reasons(plan)
    if reasons:
        raise ReferenceUnavailable(reasons)
    index_of: dict[str, int] = {}
    out = [
        "#!/bin/sh",
        f"# reference run of JCL job {plan.job}: the job's steps over GnuCOBOL-compiled programs",
        'DATA="$1"; BIN="$2"',
        'mkdir -p "$DATA"',
        'MAX=0; ALL=""',
        'jerr() { echo "JCL ERROR $1"; rm -rf "$DATA/_tmp"; exit 255; }',
        "holds() {",
        '  case "$2" in',
        '    GT) [ "$1" -gt "$3" ];; GE) [ "$1" -ge "$3" ];; EQ) [ "$1" -eq "$3" ];;',
        '    NE) [ "$1" -ne "$3" ];; LT) [ "$1" -lt "$3" ];; LE) [ "$1" -le "$3" ];;',
        "  esac",
        "}",
    ]
    for step_index, step in enumerate(plan.steps):
        out.append(f"# step {step.name}")
        out.append("bypass=0")
        out.extend(_cond_lines(step, index_of, step_index))
        out.append('if [ "$bypass" = 1 ]; then')
        out.append(f'  echo "JCL step {step.name} BYPASSED"')
        out.append("else")
        for line in (*_dd_lines(step, step_index), *_run_lines(step, step_index), *_post_lines(step, step_index)):
            out.append("  " + line)
        out.append(f"  RC_{step_index}=$rc")
        out.append('  ALL="$ALL $rc"')
        out.append('  [ "$rc" -le "$MAX" ] || MAX=$rc')
        out.append(f'  echo "JCL step {step.name} RC=$rc"')
        out.append("fi")
        index_of[step.name] = step_index
    out.append('rm -rf "$DATA/_tmp"')
    out.append(f'echo "JCL job {plan.job} MAXRC=$MAX"')
    out.append('exit "$MAX"')
    return "\n".join(out) + "\n"


__all__ = ["DdPlan", "ReferenceUnavailable", "render_reference"]
