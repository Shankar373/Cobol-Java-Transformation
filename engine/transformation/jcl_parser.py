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

from engine.transformation.ir import (
    JclApplication,
    JclCondition,
    JclDD,
    JclDependency,
    JclExec,
    JclJob,
    JclStep,
    JclSymbol,
)


class JclParseError(Exception):
    """Raised when JCL parsing encounters unrecoverable syntax."""


class JclParser:
    """Parse JCL source text into JCL IR.

    Usage:
        parser = JclParser()
        job = parser.parse(jcl_text)
    """

    def parse(self, source: str) -> JclJob:
        """Parse JCL source text into a JclJob IR.

        Args:
            source: JCL source text

        Returns:
            JclJob with parsed steps, DDs, and conditions
        """
        lines = source.splitlines()
        return self._parse_lines(lines)

    def parse_application(self, sources: dict[str, str]) -> JclApplication:
        """Parse multiple JCL sources into a JclApplication.

        Args:
            sources: dict mapping filename to JCL source text

        Returns:
            JclApplication with all jobs and dependencies
        """
        jobs: list[JclJob] = []
        for filename, source in sources.items():
            job = self.parse(source)
            jobs.append(JclJob(
                name=job.name,
                parameters=job.parameters,
                steps=job.steps,
                comments=job.comments,
                source_path=filename,
            ))

        dependencies = self._build_all_dependencies(jobs)

        return JclApplication(
            jobs=tuple(jobs),
            dependencies=tuple(dependencies),
        )

    def _parse_lines(self, lines: list[str]) -> JclJob:
        """Parse JCL lines into a JclJob."""
        job_name = ""
        job_params: dict[str, str] = {}
        steps: list[JclStep] = []
        comments: list[str] = []
        symbols: list[JclSymbol] = []

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
                job_name, job_params, i = self._parse_job(rest, i)
                continue

            # Check for EXEC
            if " EXEC " in rest or rest.upper().startswith("EXEC "):
                step, i = self._parse_exec(rest, i, lines)
                steps.append(step)
                continue

            # Check for DD
            if " DD " in rest or rest.upper().startswith("DD "):
                # This DD belongs to the current step
                if steps:
                    dd, i = self._parse_dd(rest, i, lines)
                    steps[-1] = JclStep(
                        name=steps[-1].name,
                        exec_=steps[-1].exec_,
                        dd_statements=steps[-1].dd_statements + (dd,),
                        condition=steps[-1].condition,
                        comments=steps[-1].comments,
                    )
                else:
                    i += 1
                continue

            # Check for SET
            if rest.upper().startswith("SET ") or " SET " in rest:
                symbol = self._parse_set(rest)
                if symbol:
                    symbols.append(symbol)
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

        return JclJob(
            name=job_name,
            parameters=job_params if job_params else None,
            steps=tuple(steps),
            comments=tuple(comments),
        )

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
                    dd, i = self._parse_dd(content, i, lines)
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

    def _parse_dd(self, line: str, start_idx: int, lines: list[str]) -> tuple[JclDD, int]:
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
        sysin = False
        is_temporary = False
        is_inline = False

        if dd_str == "*" or dd_str.upper() == "DATA":
            is_inline = True
        elif dd_str.upper().startswith("*"):
            is_inline = True
        elif dd_str.upper().startswith("SYSOUT"):
            sysout_match = re.search(r"SYSOUT=(\S+)", dd_str, re.IGNORECASE)
            if sysout_match:
                sysout = sysout_match.group(1).rstrip(",")
        else:
            # Parse DSN, DISP, etc.
            # Split by comma first, then parse each part
            parts = re.split(r",(?=(?:[^']*\'[^']*\')*[^']*$)", dd_str)

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
                sysin=sysin,
                is_temporary=is_temporary,
                is_inline=is_inline,
            ),
            start_idx + 1,
        )

    def _parse_set(self, line: str) -> JclSymbol | None:
        """Parse a SET statement for symbolic parameters."""
        match = re.search(
            r"SET\s+(\S+)=([^,\s]+)",
            line, re.IGNORECASE,
        )
        if not match:
            return None

        name = match.group(1)
        value = match.group(2)

        return JclSymbol(
            name=name,
            value=value,
            is_resolved=True,
        )

    def _parse_parameters(self, param_str: str) -> dict[str, str]:
        """Parse comma-separated parameters.

        Handles parentheses in values like COND=(0,NE).
        """
        params: dict[str, str] = {}

        # Split by comma, but handle parentheses and quoted strings
        # This regex respects parentheses depth and quoted strings
        parts: list[str] = []
        depth = 0
        current: list[str] = []
        in_quote = False
        quote_char = ""

        for ch in param_str:
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
                depth -= 1
                current.append(ch)
            elif ch == "," and depth == 0:
                parts.append("".join(current))
                current = []
            else:
                current.append(ch)

        if current:
            parts.append("".join(current))

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

    def _build_step_dependencies(
        self,
        jobs: list[JclJob],
    ) -> list[JclDependency]:
        """Build step execution order dependencies.

        Steps within a job execute in source order unless conditioned.
        """
        dependencies: list[JclDependency] = []

        for job in jobs:
            for i in range(len(job.steps) - 1):
                current = job.steps[i]
                next_step = job.steps[i + 1]

                # Unconditional step order
                if current.condition is None:
                    dependencies.append(JclDependency(
                        source=current.name,
                        target=next_step.name,
                        dependency_type="JCL_STEP_ORDER",
                        metadata=f"job={job.name}",
                    ))

        return dependencies

    def _build_all_dependencies(
        self,
        jobs: list[JclJob],
    ) -> list[JclDependency]:
        """Build all dependencies from parsed jobs."""
        dependencies: list[JclDependency] = []

        for job in jobs:
            # Step order dependencies
            for i in range(len(job.steps) - 1):
                current = job.steps[i]
                next_step = job.steps[i + 1]

                if current.condition is None:
                    dependencies.append(JclDependency(
                        source=current.name,
                        target=next_step.name,
                        dependency_type="JCL_STEP_ORDER",
                        metadata=f"job={job.name}",
                    ))

            # EXEC program references
            for step in job.steps:
                if step.exec_ and step.exec_.program:
                    dependencies.append(JclDependency(
                        source=f"{job.name}.{step.name}",
                        target=step.exec_.program,
                        dependency_type="JCL_EXEC",
                        metadata=f"job={job.name}",
                    ))

            # DD dataset references
            for step in job.steps:
                for dd in step.dd_statements:
                    if dd.dataset:
                        dependencies.append(JclDependency(
                            source=f"{job.name}.{step.name}.{dd.name}",
                            target=dd.dataset,
                            dependency_type="JCL_DD",
                            metadata=f"disp={dd.disposition}" if dd.disposition else "",
                        ))

        return dependencies
