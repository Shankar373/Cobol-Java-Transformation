"""JCL semantic model → Java/Spring Batch modernization profile mapper.

This is the final stage of the JCL modernization lane:

    JCL
        ↓ (engine.transformation.jcl_parser)
    JclApplication IR
        ↓ (engine.jcl.builder)
    JclSemanticModel
        ↓ (this module)
    SpringBatchApplication + JclModernizationProfile

The mapper is deterministic and declarative. It captures the *program*
(step order, step activation, dataset producer/consumer relationships) in
Spring Batch terms. It does not execute JCL and makes no JES/z/OS runtime
equivalence claims.

Deterministic naming:
    JOB MYJOB              → job_bean "MyjobJob", start_step "Step01"
    STEP01 EXEC PGM=MAIN   → step "Step01", tasklet_bean "Step01Tasklet"
    DD INPUT DSN=...       → resource "Input", bean "Input"
"""

from __future__ import annotations

import re
from collections import OrderedDict
from itertools import pairwise

from engine.jcl.builder import JclSemanticBuilder
from engine.jcl.diagnostics import (
    JclDiagnostic,
    JclDiagnosticCode,
    JclDiagnosticCollector,
)
from engine.jcl.model import (
    JclControlKind,
    JclDatasetUse,
    JclResource,
    JclResourceKind,
    JclSemanticModel,
    JclSemanticStep,
)
from engine.transformation.ir import JclApplication
from engine.transformation.jcl_spring_batch_ir import (
    EXIT_STATUS_ANY,
    EXIT_STATUS_CONDITIONAL,
    EXIT_STATUS_FAILED,
    EXIT_STATUS_SUCCESS,
    EXIT_STATUS_UNKNOWN,
    PROFILE_VERSION,
    SpringBatchApplication,
    SpringBatchDatasetEdge,
    SpringBatchFlowEdge,
    SpringBatchJob,
    SpringBatchResource,
    SpringBatchResourceType,
    SpringBatchStep,
)

_SUPPORTED_CONSTRUCTS = (
    "JOB",
    "EXEC-PGM",
    "DD-DATASET",
    "DATASET-REFERENCE",
    "STEP-ORDER",
    "COND-EVEN",
    "COND-ONLY",
    "COND-RC-DECLARED",
    "SYSOUT",
    "SYSIN-INLINE",
)

_UNSUPPORTED_CONSTRUCT_TEXT = {
    JclDiagnosticCode.UNSUPPORTED_PROCEDURE: "PROC steps / procedure definitions",
    JclDiagnosticCode.UNSUPPORTED_CONTROL_BLOCK: "IF/THEN/ELSE/ENDIF control blocks",
    JclDiagnosticCode.UNSUPPORTED_STATEMENT: "statements outside the supported subset",
    JclDiagnosticCode.UNSUPPORTED_CONTINUATION: "DD continuations",
    JclDiagnosticCode.STEP_NO_EXEC: "steps without an EXEC program",
    JclDiagnosticCode.JOB_UNNAMED: "unnamed jobs",
}


class JclProfileStatus:
    """Overall modernization profile status."""

    FULL = "FULL"
    PARTIAL = "PARTIAL"
    EMPTY = "EMPTY"


class JclModernizationProfile:
    """Result of profiling a JCL application for Java/Spring Batch.

    Carries the generated representation, the full diagnostic trail, and an
    explicit contract summary (supported vs unsupported constructs).
    """

    def __init__(
        self,
        application: SpringBatchApplication,
        diagnostics: tuple[JclDiagnostic, ...],
        status: str,
    ) -> None:
        self.application = application
        self.diagnostics = diagnostics
        self.status = status
        self._unsupported = tuple(self._derive_unsupported(diagnostics))
        self._supported = _SUPPORTED_CONSTRUCTS

    @property
    def has_errors(self) -> bool:
        return any(d.level.value == "ERROR" for d in self.diagnostics)

    @property
    def has_warnings(self) -> bool:
        return any(d.level.value == "WARNING" for d in self.diagnostics)

    @property
    def supported_constructs(self) -> tuple[str, ...]:
        return self._supported

    @property
    def unsupported_constructs(self) -> tuple[str, ...]:
        return self._unsupported

    @staticmethod
    def _derive_unsupported(diagnostics: tuple[JclDiagnostic, ...]) -> list[str]:
        seen: set[str] = set()
        for diagnostic in diagnostics:
            if diagnostic.level.value != "ERROR":
                continue
            text = _UNSUPPORTED_CONSTRUCT_TEXT.get(diagnostic.code)
            if text is not None:
                seen.add(text)
        return sorted(seen)


class JclSpringBatchMapper:
    """Map a ``JclSemanticModel`` into a ``SpringBatchApplication``."""

    def __init__(self, diagnostics: JclDiagnosticCollector | None = None) -> None:
        self.diagnostics = diagnostics or JclDiagnosticCollector()

    def map_model(
        self,
        model: JclSemanticModel,
        application_id: str = "jcl-modernization",
        base_package: str = "com.generated.batch",
    ) -> SpringBatchApplication:
        """Map the whole semantic model into the Spring Batch representation."""
        jobs = tuple(self.map_job(job) for job in model.jobs)
        resources = self._build_resource_inventory(jobs)
        dataset_edges = self._build_dataset_edges(model.jobs)

        return SpringBatchApplication(
            application_id=application_id,
            base_package=base_package,
            jobs=jobs,
            resources=resources,
            dataset_edges=dataset_edges,
            profile_version=PROFILE_VERSION,
        )

    def map_job(self, job) -> SpringBatchJob:
        """Map one semantic JCL job into a ``SpringBatchJob``."""
        steps = tuple(self.map_step(step) for step in job.steps)
        start_step = steps[0].name if steps else ""
        flow_edges = self._build_flow_edges(job.steps)
        parameters = tuple(sorted(job.parameters.items()) if job.parameters else ())
        return SpringBatchJob(
            name=job.name,
            job_bean=_camel_bean(job.name) + "Job" if job.name else "UnnamedJob",
            start_step=start_step,
            steps=steps,
            flows=tuple(flow_edges),
            parameters=parameters,
            source_path=job.source_path,
        )

    def map_step(self, step: JclSemanticStep) -> SpringBatchStep:
        """Map one semantic step into a ``SpringBatchStep``."""
        program = ""
        if step.exec_ is not None:
            program = step.exec_.program
        if not program:
            program = ""

        activation, raw_condition = self._activation(step)
        step_name = _camel_bean(step.name) if step.name else "Step"
        resources = tuple(
            self._map_resource(resource, step_name) for resource in step.resources
        )

        return SpringBatchStep(
            name=step_name,
            program=program,
            tasklet_bean=step_name + "Tasklet",
            resources=resources,
            activation=activation,
            raw_condition=raw_condition,
            source_step=step.name,
        )

    def _map_resource(
        self, resource: JclResource, step_name: str
    ) -> SpringBatchResource:
        resource_type = self._resource_type(resource)
        bean = _camel_bean(resource.name) if resource.name else "Resource"
        return SpringBatchResource(
            name=resource.name,
            resource_type=resource_type,
            dsn=resource.dataset,
            disposition=resource.disposition,
            bean=bean,
            step_ref=step_name,
        )

    def _resource_type(self, resource: JclResource) -> SpringBatchResourceType:
        if resource.kind == JclResourceKind.SYSOUT:
            return SpringBatchResourceType.SYSOUT_LOG
        if resource.kind == JclResourceKind.SYSIN_INLINE:
            return SpringBatchResourceType.INLINE_PARAMS
        if resource.kind == JclResourceKind.TEMPORARY:
            return SpringBatchResourceType.TEMP
        if resource.kind == JclResourceKind.DATASET:
            if resource.dataset_use == JclDatasetUse.OUTPUT:
                return SpringBatchResourceType.OUTPUT
            if resource.dataset_use == JclDatasetUse.INPUT:
                return SpringBatchResourceType.INPUT
        return SpringBatchResourceType.UNKNOWN

    def _activation(self, step: JclSemanticStep) -> tuple[str, str]:
        if step.control is None:
            return EXIT_STATUS_SUCCESS, ""
        mapping = {
            JclControlKind.SEQUENTIAL: EXIT_STATUS_SUCCESS,
            JclControlKind.EVEN: EXIT_STATUS_ANY,
            JclControlKind.ONLY: EXIT_STATUS_FAILED,
            JclControlKind.RETURN_CODE: EXIT_STATUS_CONDITIONAL,
            JclControlKind.UNSUPPORTED: EXIT_STATUS_UNKNOWN,
        }
        return mapping[step.control.kind], step.control.expression

    def _build_flow_edges(self, steps) -> list[SpringBatchFlowEdge]:
        edges: list[SpringBatchFlowEdge] = []
        ordered = sorted(steps, key=lambda s: s.order_index)
        for current, following in pairwise(ordered):
            on_status = EXIT_STATUS_SUCCESS
            if following.control is not None:
                on_status, _ = self._activation(following)
            edges.append(
                SpringBatchFlowEdge(
                    source=_camel_bean(current.name),
                    target=_camel_bean(following.name),
                    on_status=on_status,
                )
            )
        return edges

    def _build_resource_inventory(self, jobs) -> tuple[SpringBatchResource, ...]:
        by_key: OrderedDict[tuple, SpringBatchResource] = OrderedDict()
        for job in jobs:
            for step in job.steps:
                for resource in step.resources:
                    if not resource.dsn:
                        continue
                    key = (resource.dsn, resource.name)
                    by_key.setdefault(key, resource)
        return tuple(by_key.values())

    def _build_dataset_edges(
        self,
        semantic_jobs,
    ) -> tuple[SpringBatchDatasetEdge, ...]:
        edges: list[SpringBatchDatasetEdge] = []
        for job in semantic_jobs:
            for flow in job.dataset_flows:
                producer = _camel_bean(flow.producer) if flow.producer else ""
                if flow.producer:
                    consumer_steps = flow.consumers or ("",)
                    for consumer in consumer_steps:
                        edges.append(
                            SpringBatchDatasetEdge(
                                job=job.name,
                                dataset=flow.dataset,
                                producer=producer,
                                consumer=_camel_bean(consumer) if consumer else "",
                            )
                        )
                else:
                    for consumer in flow.consumers:
                        edges.append(
                            SpringBatchDatasetEdge(
                                job=job.name,
                                dataset=flow.dataset,
                                producer="",
                                consumer=_camel_bean(consumer),
                            )
                        )
        return tuple(edges)


def _camel_bean(name: str) -> str:
    """Deterministic bean-style name from a JCL token (e.g. "PAY-MAIN" → "PayMain")."""
    return "".join(
        part[:1].upper() + part[1:].lower()
        for part in re.split(r"[^A-Za-z0-9]+", name)
        if part
    )


def modernize_jcl(
    app: JclApplication,
    raw_sources: dict[str, str] | None = None,
    application_id: str = "jcl-modernization",
    base_package: str = "com.generated.batch",
) -> JclModernizationProfile:
    """Profile a parsed JCL application into a Java/Spring Batch representation.

    This is the single entry point of the JCL modernization lane:

        JclParser.parse_application({...})  or  JclDiscovery().discover(...)
            ↓
        modernize_jcl(app, raw_sources)
            ↓
        JclModernizationProfile

    Args:
        app: parsed ``JclApplication``.
        raw_sources: optional mapping of source filename to raw JCL text used
            to detect (and explicitly diagnose) unsupported constructs.
        application_id: identifier for the resulting Spring Batch application.
        base_package: target Java package namespace for the batch layer.

    Returns:
        A ``JclModernizationProfile`` containing the generated Spring Batch
        representation and the full diagnostic trail.
    """
    builder = JclSemanticBuilder()
    model = builder.build(app, raw_sources)

    mapper = JclSpringBatchMapper(diagnostics=builder.diagnostics)
    application = mapper.map_model(model, application_id, base_package)

    mapper.diagnostics.info(
        JclDiagnosticCode.PROFILE_NOTED,
        "JCL modernization profile is a static representation; no JES/z/OS "
        "runtime equivalence is claimed. Return-code conditions are declared "
        "gates pending verification.",
    )

    if not application.jobs:
        status = JclProfileStatus.EMPTY
    elif mapper.diagnostics.has_errors:
        status = JclProfileStatus.PARTIAL
    else:
        status = JclProfileStatus.FULL

    return JclModernizationProfile(
        application=application,
        diagnostics=mapper.diagnostics.all,
        status=status,
    )
