"""JCL parser for generic supported constructs.

Parses JCL source into the JCL IR. This is NOT a general-purpose JCL parser.
It handles only the supported constructs:

- //JOB JOB
- //STEP EXEC PGM=...
- //STEP EXEC PROC=...
- //DD DSN=...,DISP=...
- //DD SYSOUT=...
- //DD * (inline data)
- //* comments
- COND parameter
- SET symbolic parameters
- Step ordering (source order preserved)

Unsupported constructs produce minimal IR without error.
JCL parsing is discovery and modeling only — no execution semantics.
"""

from __future__ import annotations

import re
from dataclasses import replace

from engine.transformation.ir import (
    JclApplication,
    JclCondition,
    JclDD,
    JclExec,
    JclJob,
    JclStep,
)
from engine.transformation.jcl_dependencies import build_all_dependencies


class JclParser:
    """Parse JCL source text into JCL IR.

    Usage:
        parser = JclParser()
        job = parser.parse(jcl_text)
    """

    def parse(self, source: str) -> JclJob:
        """Parse JCL source text into a JclJob IR.

        Multi-job sources (several ``JOB`` statements in one file) are
        split by :meth:`parse_jobs`; this single-job convenience returns
        the **first** job of the source.

        Args:
            source: JCL source text

        Returns:
            JclJob with parsed steps, DDs, and conditions
        """
        jobs = self.parse_jobs(source)
        if jobs:
            return jobs[0]
        return JclJob(name="")

    def parse_jobs(self, source: str) -> tuple[JclJob, ...]:
        """Parse JCL source text into every JOB it declares, in source order.

        Each ``JOB`` statement starts a new :class:`JclJob`; statements
        stay attributed to the job they follow (no merging, no silent
        loss).

        Args:
            source: JCL source text

        Returns:
            One ``JclJob`` per JOB statement; empty tuple only when the
            source carries no statements at all.
        """
        return tuple(self._parse_lines(source.splitlines()))

    def parse_application(self, sources: dict[str, str]) -> JclApplication:
        """Parse multiple JCL sources into a JclApplication.

        Args:
            sources: dict mapping filename to JCL source text

        Returns:
            JclApplication with all jobs and dependencies
        """
        jobs: list[JclJob] = []
        for filename, source in sources.items():
            for job in self.parse_jobs(source):
                # replace() keeps every job field (including fields added
                # later) without a hand-maintained copy list.
                jobs.append(replace(job, source_path=filename))

        dependencies = build_all_dependencies(jobs)

        return JclApplication(
            jobs=tuple(jobs),
            dependencies=tuple(dependencies),
        )

    def _parse_lines(self, lines: list[str]) -> list[JclJob]:
        """Parse JCL lines into one JclJob per JOB statement."""
        jobs: list[JclJob] = []
        job_name = ""
        job_params: dict[str, str] = {}
        steps: list[JclStep] = []
        comments: list[str] = []
        job_level_dds: list[JclDD] = []
        job_seen = False

        def flush() -> None:
            """Append the job accumulated so far and reset the buffers."""
            nonlocal job_name, job_params, steps, comments, job_level_dds
            jobs.append(JclJob(
                name=job_name,
                parameters=job_params if job_params else None,
                steps=tuple(steps),
                comments=tuple(comments),
                job_dd_statements=tuple(job_level_dds),
            ))
            job_name = ""
            job_params = {}
            steps = []
            comments = []
            job_level_dds = []

        i = 0
        while i < len(lines):
            line = lines[i]

            # Skip empty lines
            if not line.strip():
                i += 1
                continue

            # Comment lines
            if line.startswith("//*"):
                comments.append(line[3:].strip())
                i += 1
                continue

            # Must start with //
            if not line.startswith("//"):
                i += 1
                continue

            # Parse the //NAME field
            rest = line[2:].strip()

            # Check for JOB
            if " JOB " in rest or rest.upper().startswith("JOB "):
                # A second JOB statement closes the job accumulated so far
                # instead of absorbing its steps.
                if job_seen:
                    flush()
                job_seen = True
                job_name, job_params, i = self._parse_job(rest, i)
                continue

            # Check for EXEC
            if " EXEC " in rest or rest.upper().startswith("EXEC "):
                step, i = self._parse_exec(rest, i, lines)
                steps.append(step)
                continue

            # Check for DD
            if " DD " in rest or rest.upper().startswith("DD "):
                dd, i = self._parse_dd(rest, i)
                if steps:
                    # This DD belongs to the current step
                    steps[-1] = JclStep(
                        name=steps[-1].name,
                        exec_=steps[-1].exec_,
                        dd_statements=steps[-1].dd_statements + (dd,),
                        condition=steps[-1].condition,
                        comments=steps[-1].comments,
                    )
                else:
                    # DD before the first EXEC of this job: job-level
                    # (JOBLIB & co.) — preserved, never dropped
                    job_level_dds.append(dd)
                continue

            # Check for SET
            if rest.upper().startswith("SET ") or " SET " in rest:
                i += 1
                continue

            # Check for PROC
            if rest.upper().startswith("PROC ") or " PROC " in rest:
                # Cataloged procedure reference - skip for now
                i += 1
                continue

            # Check for PEND
            if rest.upper().strip() == "PEND":
                i += 1
                continue

            # Skip unrecognized lines
            i += 1

        if job_seen or steps or comments or job_params or job_name or job_level_dds:
            flush()

        return jobs

    def _parse_job(self, line: str, start_idx: int) -> tuple[str, dict[str, str], int]:
        """Parse a JOB statement.

        Returns:
            (job_name, parameters, next_line_index)
        """
        # Extract job name: //JOBNAME JOB ...
        match = re.match(
            r"(\S+)\s+JOB\s*(.*)",
            line, re.IGNORECASE,
        )
        if not match:
            return ("", {}, start_idx + 1)

        job_name = match.group(1)
        params_str = match.group(2).strip()

        # Parse JOB parameters
        params = self._parse_parameters(params_str)

        return (job_name, params, start_idx + 1)

    def _parse_exec(self, line: str, start_idx: int, lines: list[str]) -> tuple[JclStep, int]:
        """Parse an EXEC statement.

        Returns:
            (JclStep, next_line_index)
        """
        # Extract step name and EXEC content
        # //STEPNAME EXEC PGM=PROGRAM-A or //STEPNAME EXEC PROC=PROC-A
        match = re.match(
            r"(\S+)\s+EXEC\s+(.*)",
            line, re.IGNORECASE,
        )
        if not match:
            return (JclStep(name="UNKNOWN"), start_idx + 1)

        step_name = match.group(1)
        exec_str = match.group(2).strip()

        # Parse EXEC parameters
        exec_ = self._parse_exec_params(exec_str)

        # Check for COND parameter on EXEC line
        condition = None
        if exec_.parameters and "COND" in exec_.parameters:
            condition = JclCondition(
                condition_type="COND",
                code=exec_.parameters["COND"],
            )

        # Collect DD statements for this step
        dds: list[JclDD] = []
        i = start_idx + 1
        while i < len(lines):
            next_line = lines[i].strip()

            # Stop at next // that is not a DD
            if next_line.startswith("//") and not next_line.startswith("//*"):
                content = next_line[2:].strip()
                # Check if this is a DD statement
                if " DD " in content.upper() or content.upper().startswith("DD "):
                    dd, i = self._parse_dd(content, i)
                    dds.append(dd)
                    continue
                else:
                    # Next statement (EXEC, JOB, etc.) - don't consume
                    break
            else:
                # Comment or non-JCL line - don't consume, let main loop handle
                break

        return (
            JclStep(
                name=step_name,
                exec_=exec_,
                dd_statements=tuple(dds),
                condition=condition,
            ),
            i,
        )

    def _parse_exec_params(self, exec_str: str) -> JclExec:
        """Parse EXEC parameters (PGM=, PROC=, PARM=, etc.)."""
        program = ""
        procedure = ""
        params: dict[str, str] = {}

        # Check for PGM=
        pgm_match = re.search(r"PGM=(\S+)", exec_str, re.IGNORECASE)
        if pgm_match:
            program = pgm_match.group(1).rstrip(",")

        # Check for PROC=
        proc_match = re.search(r"PROC=(\S+)", exec_str, re.IGNORECASE)
        if proc_match:
            procedure = proc_match.group(1).rstrip(",")

        # Parse other parameters
        other_params = self._parse_parameters(exec_str)
        params.update(other_params)

        return JclExec(
            program=program,
            procedure=procedure,
            parameters=params if params else None,
        )

    def _parse_dd(self, line: str, start_idx: int) -> tuple[JclDD, int]:
        """Parse a DD statement.

        Returns:
            (JclDD, next_line_index)
        """
        # Extract DD name and content
        # //INPUT DD DSN=INPUT.DATA,DISP=SHR
        match = re.match(
            r"(\S+)\s+DD\s+(.*)",
            line, re.IGNORECASE,
        )
        if not match:
            return (JclDD(name="UNKNOWN"), start_idx + 1)

        dd_name = match.group(1)
        dd_str = match.group(2).strip()

        # Parse DD parameters
        dataset = ""
        disposition = ""
        space = ""
        unit = ""
        dcb = ""
        vol = ""
        sysout = ""
        is_temporary = False
        is_inline = False

        if dd_str.upper() == "DATA":
            is_inline = True
        elif dd_str.upper().startswith("*"):
            is_inline = True
        elif dd_str.upper().startswith("SYSOUT"):
            sysout_match = re.search(r"SYSOUT=(\S+)", dd_str, re.IGNORECASE)
            if sysout_match:
                sysout = sysout_match.group(1).rstrip(",")
        else:
            # Parse DSN, DISP, etc.
            # Split by comma, respecting parenthesis depth and quotes so
            # compound values like DISP=(NEW,CATLG,DELETE) or
            # SPACE=(TRK,(10,5)) stay single parameters.
            parts = self._split_parameters(dd_str)

            for part in parts:
                part = part.strip()
                if not part:
                    continue

                part_upper = part.upper()
                if part_upper.startswith("DSN="):
                    dataset = part[4:].strip().strip("'\"")
                elif part_upper.startswith("DISP="):
                    disposition = part[5:].strip().strip("'\"")
                elif part_upper.startswith("SPACE="):
                    space = part[6:].strip().strip("'\"")
                elif part_upper.startswith("UNIT="):
                    unit = part[5:].strip().strip("'\"")
                elif part_upper.startswith("DCB="):
                    dcb = part[4:].strip().strip("'\"")
                elif part_upper.startswith("VOL="):
                    vol = part[4:].strip().strip("'\"")

        # Check for temporary dataset
        if dataset.startswith("&&") or sysout:
            is_temporary = True

        return (
            JclDD(
                name=dd_name,
                dataset=dataset,
                disposition=disposition,
                space=space,
                unit=unit,
                dcb=dcb,
                vol=vol,
                sysout=sysout,
                is_temporary=is_temporary,
                is_inline=is_inline,
            ),
            start_idx + 1,
        )


    @staticmethod
    def _split_parameters(text: str) -> list[str]:
        """Split comma-separated JCL parameters.

        Commas inside parentheses (``DISP=(NEW,CATLG,DELETE)``,
        ``SPACE=(TRK,(10,5))``) and inside quoted strings
        (``DSN='A,B'``) do not separate parameters; only top-level
        commas do.
        """
        parts: list[str] = []
        current: list[str] = []
        depth = 0
        in_quote = False
        quote_char = ""

        for ch in text:
            if in_quote:
                current.append(ch)
                if ch == quote_char:
                    in_quote = False
                continue

            if ch in ("'", '"'):
                in_quote = True
                quote_char = ch
                current.append(ch)
                continue

            if ch == "(":
                depth += 1
                current.append(ch)
            elif ch == ")":
                depth = max(0, depth - 1)
                current.append(ch)
            elif ch == "," and depth == 0:
                parts.append("".join(current))
                current = []
            else:
                current.append(ch)

        if current:
            parts.append("".join(current))
        return parts

    def _parse_parameters(self, param_str: str) -> dict[str, str]:
        """Parse comma-separated parameters.

        Handles parentheses in values like COND=(0,NE).
        """
        params: dict[str, str] = {}

        parts = self._split_parameters(param_str)

        for part in parts:
            part = part.strip()
            if not part:
                continue

            # Check for KEY=VALUE
            kv_match = re.match(r"(\S+?)=(.+)", part)
            if kv_match:
                key = kv_match.group(1).upper()
                value = kv_match.group(2).strip().strip("'\"")
                params[key] = value

        return params
