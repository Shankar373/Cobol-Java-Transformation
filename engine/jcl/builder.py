"""Build a semantic JCL model from the discovery JCL IR.

The discovery parser (``engine.transformation.jcl_parser``) intentionally skips
unrecognized JCL. For a modernization profile that is not acceptable, so this
builder combines:

- the parsed ``JclApplication`` IR (authoritative for supported constructs), and
- the raw JCL source text (authoritative for detecting constructs outside the
  supported subset).

Every unsupported construct produces an explicit ``JclDiagnostic`` (ERROR by
default) instead of being silently dropped.
"""

from __future__ import annotations

import re
from itertools import pairwise

from engine.jcl.diagnostics import JclDiagnosticCode, JclDiagnosticCollector
from engine.jcl.model import (
    JclControl,
    JclControlKind,
    JclDatasetFlow,
    JclDatasetInventory,
    JclDatasetUse,
    JclDisposition,
    JclExec,
    JclExecMode,
    JclResource,
    JclResourceKind,
    JclSemanticJob,
    JclSemanticModel,
    JclSemanticStep,
    JclStepDependency,
)
from engine.transformation.ir import (
    JclApplication,
    JclCondition,
    JclDD,
    JclJob,
    JclStep,
)

_UNSUPPORTED_STATEMENTS = frozenset(
    {"JCLLIB", "INCLUDE", "OUTPUT", "XMIT", "TWRS", "CMPSC", "PROCESS", "NETVIEW"}
)


class JclSemanticBuilder:
    """Build a ``JclSemanticModel`` from a discovered JCL application.

    Diagnostics collected during the build are exposed on the ``diagnostics``
    collector attribute. Callers that need a single result surface should use
    the modernization facade, which aggregates builder and mapper diagnostics.
    """

    def __init__(self, diagnostics: JclDiagnosticCollector | None = None) -> None:
        self.diagnostics = diagnostics or JclDiagnosticCollector()

    def build(
        self,
        app: JclApplication,
        raw_sources: dict[str, str] | None = None,
    ) -> JclSemanticModel:
        """Build the semantic model for a JCL application.

        Args:
            app: parsed ``JclApplication`` from ``JclParser`` or ``JclDiscovery``.
            raw_sources: optional mapping of source filename to raw JCL text,
                used to detect unsupported constructs the parser skips.

        Returns:
            A ``JclSemanticModel`` for the supported subset.
        """
        jobs: list[JclSemanticJob] = []
        raw_sources = raw_sources or {}

        for job in app.jobs:
            raw_text = self._raw_for_job(job, raw_sources)
            if raw_text is not None:
                self._scan_unsupported(raw_text, job.name)

            jobs.append(self._build_job(job))

        inventory = self._build_dataset_inventory(jobs)

        return JclSemanticModel(
            jobs=tuple(jobs),
            dataset_inventory=inventory,
            source_path=app.source_path,
        )

    def _build_job(self, job: JclJob) -> JclSemanticJob:
        steps: list[JclSemanticStep] = []
        producers: dict[str, str] = {}
        consumers: dict[str, list[str]] = {}

        for index, step in enumerate(job.steps):
            semantic_step = self._build_step(step, index, job.name)
            steps.append(semantic_step)

            for resource in semantic_step.resources:
                if not resource.dataset:
                    continue
                if resource.dataset_use == JclDatasetUse.OUTPUT:
                    producers[resource.dataset] = step.name
                elif resource.dataset_use == JclDatasetUse.INPUT:
                    consumers.setdefault(resource.dataset, []).append(step.name)

        dataset_flows: list[JclDatasetFlow] = []
        all_datasets = set(producers) | set(consumers)
        for dataset in sorted(all_datasets):
            dataset_flows.append(
                JclDatasetFlow(
                    job=job.name,
                    dataset=dataset,
                    producer=producers.get(dataset, ""),
                    consumers=tuple(sorted(set(consumers.get(dataset, [])))),
                )
            )

        dependencies = self._build_step_dependencies(job.name, steps)

        return JclSemanticJob(
            name=job.name,
            source_path=job.source_path,
            parameters=job.parameters,
            steps=tuple(steps),
            dataset_flows=tuple(dataset_flows),
            dependencies=tuple(dependencies),
        )

    def _build_step(self, step: JclStep, index: int, job_name: str) -> JclSemanticStep:
        exec_ = self._build_exec(step, job_name)
        resources = tuple(
            self._build_resource(dd, step, job_name) for dd in step.dd_statements
        )
        control = self._build_control(step.condition, step, job_name)
        return JclSemanticStep(
            name=step.name,
            exec_=exec_,
            resources=resources,
            control=control,
            order_index=index,
            source_job=job_name,
        )

    def _build_exec(self, step: JclStep, job_name: str) -> JclExec | None:
        if step.exec_ is None:
            self.diagnostics.error(
                JclDiagnosticCode.STEP_NO_EXEC,
                f"Step {step.name} has no EXEC statement",
                job=job_name,
                step=step.name,
            )
            return None

        if step.exec_.program:
            mode = JclExecMode.PROGRAM
            target = step.exec_.program
            if "&" in target:
                self.diagnostics.warning(
                    JclDiagnosticCode.UNRESOLVED_SYMBOL,
                    f"Symbolic reference in PGM preserved unresolved: {target}",
                    job=job_name,
                    step=step.name,
                )
        elif step.exec_.procedure:
            mode = JclExecMode.PROCEDURE
            target = step.exec_.procedure
            self.diagnostics.error(
                JclDiagnosticCode.UNSUPPORTED_PROCEDURE,
                f"EXEC PROC={target} is outside the initial profile (PGM steps only)",
                job=job_name,
                step=step.name,
            )
        else:
            mode = JclExecMode.NONE
            target = ""
            self.diagnostics.error(
                JclDiagnosticCode.STEP_NO_EXEC,
                f"Step {step.name} EXEC has neither PGM nor PROC",
                job=job_name,
                step=step.name,
            )

        return JclExec(
            mode=mode,
            program=step.exec_.program,
            procedure=step.exec_.procedure,
            parameters=step.exec_.parameters,
        )

    def _build_resource(self, dd: JclDD, step: JclStep, job_name: str) -> JclResource:
        if dd.sysout:
            kind = JclResourceKind.SYSOUT
            norm_disp = JclDisposition.UNSPECIFIED
            dataset_use = JclDatasetUse.UNSPECIFIED
        elif dd.is_inline or (dd.name.upper() == "SYSIN" and dd.sysin):
            kind = JclResourceKind.SYSIN_INLINE
            norm_disp = JclDisposition.UNSPECIFIED
            dataset_use = JclDatasetUse.INPUT
        elif dd.is_temporary or dd.dataset.startswith("&&"):
            kind = JclResourceKind.TEMPORARY
            if dd.disposition:
                norm_disp = self._normalize_disposition(dd.disposition)
                dataset_use = self._dataset_use(norm_disp)
            else:
                norm_disp = JclDisposition.NEW
                dataset_use = JclDatasetUse.OUTPUT
        elif dd.dataset:
            kind = JclResourceKind.DATASET
            norm_disp = self._normalize_disposition(dd.disposition)
            dataset_use = self._dataset_use(norm_disp)
        else:
            kind = JclResourceKind.UNKNOWN
            norm_disp = JclDisposition.UNSPECIFIED
            dataset_use = JclDatasetUse.UNSPECIFIED
            self.diagnostics.warning(
                JclDiagnosticCode.DUMMY_RESOURCE,
                f"DD {dd.name} has no dataset, SYSOUT, or inline reference; "
                "mapped as an implicit resource",
                job=job_name,
                step=step.name,
            )

        return JclResource(
            name=dd.name,
            kind=kind,
            dataset=dd.dataset,
            disposition=dd.disposition,
            norm_disposition=norm_disp,
            dataset_use=dataset_use,
            is_temporary=dd.is_temporary or dd.dataset.startswith("&&"),
            sysout_target=dd.sysout,
            is_inline=dd.is_inline,
        )

    def _normalize_disposition(self, disposition: str) -> JclDisposition:
        raw = disposition.strip().upper()
        if not raw:
            return JclDisposition.UNSPECIFIED
        first = raw.lstrip("(").split(",")[0]
        for value in JclDisposition:
            if value.value == first:
                return value
        return JclDisposition.UNSPECIFIED

    def _dataset_use(self, disposition: JclDisposition) -> JclDatasetUse:
        if disposition in (JclDisposition.NEW, JclDisposition.MOD):
            return JclDatasetUse.OUTPUT
        if disposition in (JclDisposition.OLD, JclDisposition.SHR):
            return JclDatasetUse.INPUT
        return JclDatasetUse.UNSPECIFIED

    def _build_control(
        self,
        condition: JclCondition | None,
        step: JclStep,
        job_name: str,
    ) -> JclControl | None:
        if condition is None:
            return None

        raw = (condition.code or "").strip().upper()
        if raw == "EVEN":
            return JclControl(JclControlKind.EVEN, expression=raw, exit_status="ANY")
        if raw == "ONLY":
            return JclControl(JclControlKind.ONLY, expression=raw, exit_status="FAILED")
        if raw.startswith("("):
            self.diagnostics.warning(
                JclDiagnosticCode.PARTIAL_COND_SEMANTICS,
                f"COND={raw} represented as a declared gate; return-code scan "
                "semantics are not claimed equivalent to JES",
                job=job_name,
                step=step.name,
            )
            return JclControl(
                JclControlKind.RETURN_CODE,
                expression=raw,
                exit_status="CONDITIONAL",
            )
        self.diagnostics.warning(
            JclDiagnosticCode.PARTIAL_COND_SEMANTICS,
            f"COND={raw or '<empty>'} represented as a declared gate; "
            "execution semantics are outside the supported subset",
            job=job_name,
            step=step.name,
        )
        return JclControl(
            JclControlKind.UNSUPPORTED,
            expression=raw,
            exit_status="UNKNOWN",
        )

    def _build_step_dependencies(
        self,
        job_name: str,
        steps: list[JclSemanticStep],
    ) -> list[JclStepDependency]:
        dependencies: list[JclStepDependency] = []
        ordered = sorted(steps, key=lambda s: s.order_index)

        if not ordered:
            return dependencies

        dependencies.append(
            self._dependency(
                job_name, "", ordered[0].name, JclControlKind.SEQUENTIAL, "SUCCESS"
            )
        )
        for current, following in pairwise(ordered):
            control_kind, exit_status, raw = self._activation(following)
            dependencies.append(
                self._dependency(
                    job_name,
                    current.name,
                    following.name,
                    control_kind,
                    exit_status,
                    raw,
                )
            )

        return dependencies

    def _activation(self, step: JclSemanticStep) -> tuple[JclControlKind, str, str]:
        if step.control is None:
            return JclControlKind.SEQUENTIAL, "SUCCESS", ""
        return step.control.kind, step.control.exit_status, step.control.expression

    def _dependency(
        self,
        job: str,
        source: str,
        target: str,
        control_kind: JclControlKind,
        exit_status: str,
        raw_condition: str = "",
    ) -> JclStepDependency:
        return JclStepDependency(
            job=job,
            source=source,
            target=target,
            control_kind=control_kind,
            exit_status=exit_status,
            raw_condition=raw_condition,
        )

    def _build_dataset_inventory(
        self,
        jobs: list[JclSemanticJob],
    ) -> tuple[JclDatasetInventory, ...]:
        by_name: dict[str, dict] = {}
        for job in jobs:
            for step in job.steps:
                for resource in step.resources:
                    if not resource.dataset or resource.kind not in (
                        JclResourceKind.DATASET,
                        JclResourceKind.TEMPORARY,
                    ):
                        continue
                    entry = by_name.setdefault(
                        resource.dataset, {"jobs": set(), "kinds": set(), "uses": set()}
                    )
                    entry["jobs"].add(job.name)
                    entry["kinds"].add(resource.kind)
                    entry["uses"].add(resource.dataset_use)

        inventory: list[JclDatasetInventory] = []
        for name, entry in sorted(by_name.items()):
            kind = JclResourceKind.DATASET
            if JclResourceKind.TEMPORARY in entry["kinds"]:
                kind = JclResourceKind.TEMPORARY
            inventory.append(
                JclDatasetInventory(
                    name=name,
                    jobs=tuple(sorted(entry["jobs"])),
                    kind=kind,
                    uses=tuple(sorted(entry["uses"], key=lambda u: u.value)),
                )
            )
        return tuple(inventory)

    def _raw_for_job(self, job: JclJob, raw_sources: dict[str, str]) -> str | None:
        if job.source_path and job.source_path in raw_sources:
            return raw_sources[job.source_path]
        if job.name:
            pattern = re.compile(rf"//{re.escape(job.name)}\s+JOB\b", re.IGNORECASE)
            for text in raw_sources.values():
                if pattern.search(text):
                    return text
        return None

    def _scan_unsupported(self, raw_text: str, job_name: str) -> None:
        for line_number, raw in enumerate(raw_text.splitlines(), start=1):
            if not raw.startswith("//"):
                continue
            content = raw[2:]
            stripped = content.strip()
            if not stripped or content.lstrip().startswith("*"):
                continue

            location = f"line {line_number}"
            if stripped.startswith(",") or re.match(r"^\s+,", content):
                self.diagnostics.error(
                    JclDiagnosticCode.UNSUPPORTED_CONTINUATION,
                    "DD continuation / split statements are outside the supported subset",
                    job=job_name,
                    location=location,
                )
                continue

            upper = stripped.upper()
            parts = upper.split()
            first = parts[0] if parts else ""

            if first in ("ELSE", "ENDIF") or re.search(
                r"\bIF\b\s*\(.*\)\s*THEN\b", upper
            ):
                self.diagnostics.error(
                    JclDiagnosticCode.UNSUPPORTED_CONTROL_BLOCK,
                    f"IF/THEN/ELSE/ENDIF control blocks are outside the "
                    f"supported subset: {stripped}",
                    job=job_name,
                    location=location,
                )
                continue

            if first == "SET" or any(
                keyword in parts for keyword in ("JOB", "EXEC", "DD")
            ):
                if first == "SET":
                    self.diagnostics.info(
                        JclDiagnosticCode.SYMBOL_SET_PRESERVED,
                        "SET symbolic parameter preserved as text; substitution "
                        "is outside the profile",
                        job=job_name,
                        location=location,
                    )
                continue

            if first == "PROC" or (len(parts) >= 2 and parts[1] == "PROC"):
                self.diagnostics.error(
                    JclDiagnosticCode.UNSUPPORTED_PROCEDURE,
                    "INLINE/PROCEDURE definition is outside the supported subset",
                    job=job_name,
                    location=location,
                )
                continue

            if upper.strip() == "PEND":
                self.diagnostics.error(
                    JclDiagnosticCode.UNSUPPORTED_PROCEDURE,
                    "PEND procedure terminator is outside the supported subset",
                    job=job_name,
                    location=location,
                )
                continue

            if first in _UNSUPPORTED_STATEMENTS:
                self.diagnostics.error(
                    JclDiagnosticCode.UNSUPPORTED_STATEMENT,
                    f"{first} statement is outside the supported subset",
                    job=job_name,
                    location=location,
                )
                continue

            self.diagnostics.error(
                JclDiagnosticCode.UNSUPPORTED_STATEMENT,
                f"Unrecognised JCL statement outside the supported subset: {stripped}",
                job=job_name,
                location=location,
            )
