"""JCL Spring Batch IR → Spring Boot IR adapter.

Converts a ``SpringBatchApplication`` (produced by the JCL modernization
lane) into a ``SpringBootApplication`` that the existing
``SpringBootGenerator`` can consume **without modification**.

This adapter is JCL-owned.  It has ZERO imports from COBOL modules.
It imports only from:
  - engine.transformation.jcl_spring_batch_ir  (JCL lane output)
  - engine.transformation.spring_boot_ir       (shared IR — read-only)
  - engine.transformation.java_ir              (shared IR — read-only)

The generated Spring Boot project is a **structural representation**:
it compiles, starts, and prints what each JCL step would do.
It does NOT execute real batch processing.
"""

from __future__ import annotations

from engine.transformation.java_ir import (
    JavaBasicType,
    JavaComment,
    JavaLiteral,
    JavaMethodCall,
    JavaMethodCallStatement,
    JavaType,
)
from engine.transformation.jcl_spring_batch_ir import (
    EXIT_STATUS_ANY,
    EXIT_STATUS_CONDITIONAL,
    EXIT_STATUS_FAILED,
    EXIT_STATUS_SUCCESS,
    SpringBatchApplication,
    SpringBatchDatasetEdge,
    SpringBatchJob,
    SpringBatchStep,
)
from engine.transformation.spring_boot_ir import (
    SpringBootApplication,
    SpringBootDependency,
    SpringBootDependencyType,
    SpringBootEntryPoint,
    SpringBootService,
    SpringBootServiceMethod,
)

_VOID = JavaType(basic_type=JavaBasicType.VOID)
_STRING = JavaType(basic_type=JavaBasicType.STRING)


def _camel(name: str) -> str:
    """Camel-case a JCL token: STEP01 -> step01, PAY-MAIN -> payMain."""
    parts = [p for p in __import__("re").split(r"[^A-Za-z0-9]+", name) if p]
    if not parts:
        return "step"
    return parts[0].lower() + "".join(p.capitalize() for p in parts[1:])


def _step_comment(step: SpringBatchStep, job: SpringBatchJob) -> str:
    """Build a human-readable comment for a JCL step."""
    parts = [f"JCL step {step.source_step}"]
    if step.program:
        parts.append(f"PGM={step.program}")
    if step.activation and step.activation != EXIT_STATUS_SUCCESS:
        parts.append(f"activation={step.activation}")
    if step.raw_condition:
        parts.append(f"COND={step.raw_condition}")
    return " — ".join(parts)


def _activation_comment(step: SpringBatchStep) -> str | None:
    """Return an activation gate comment, or None if default."""
    if step.activation == EXIT_STATUS_SUCCESS:
        return None
    if step.activation == EXIT_STATUS_ANY:
        return "EVEN — runs regardless of prior step return code"
    if step.activation == EXIT_STATUS_FAILED:
        return "ONLY — runs only if prior step failed"
    if step.activation == EXIT_STATUS_CONDITIONAL:
        return f"CONDITIONAL — gated by COND={step.raw_condition}"
    if step.activation == "UNKNOWN":
        return "UNSUPPORTED activation — requires manual review"
    return None


def _resource_comment(resources: tuple[SpringBatchStep, ...]) -> list[str]:
    """Describe dataset resources used by a step."""
    comments = []
    for res in resources:
        if res.dsn:
            comments.append(f"DD {res.name} → DSN={res.dsn} ({res.resource_type.value})")
    return comments


def _build_step_method(
    step: SpringBatchStep,
    job: SpringBatchJob,
    base_package: str,
) -> SpringBootServiceMethod:
    """Map one JCL step to a SpringBootServiceMethod."""
    body: list[JavaComment | JavaMethodCallStatement] = []

    # Step header comment
    body.append(JavaComment(text=_step_comment(step, job)))

    # Activation gate comment
    act_comment = _activation_comment(step)
    if act_comment:
        body.append(JavaComment(text=act_comment))

    # Resource comments
    for res in step.resources:
        if res.dsn:
            body.append(JavaComment(text=f"DD {res.name} → DSN={res.dsn} ({res.resource_type.value})"))

    # Print statement — makes the step observable at runtime
    body.append(JavaMethodCallStatement(
        call=JavaMethodCall(
            method_name="println",
            arguments=(JavaLiteral(
                value=f"[{step.source_step}] {step.program or 'no-program'}",
                java_type=JavaType(basic_type=JavaBasicType.STRING),
            ),),
            is_static=True,
            class_name="System.out",
        ),
    ))

    return SpringBootServiceMethod(
        name=_camel(step.source_step) or "execute",
        return_type=_VOID,
        parameters=(),
        body_statements=tuple(body),
    )


def _build_job_service(
    job: SpringBatchJob,
    base_package: str,
) -> SpringBootService:
    """Map one JCL job to a SpringBootService."""
    methods = tuple(
        _build_step_method(step, job, base_package)
        for step in job.steps
    )

    return SpringBootService(
        name=job.job_bean,
        package=base_package,
        source_program=job.name,
        methods=methods,
    )


def _build_dataset_comments(
    edges: tuple[SpringBatchDatasetEdge, ...],
) -> str:
    """Build a block comment describing dataset flow."""
    if not edges:
        return ""
    lines = ["Dataset flow:"]
    for e in edges:
        producer = e.producer or "(external)"
        consumer = e.consumer or "(unconsumed)"
        lines.append(f"  {e.dataset}: {producer} → {consumer}")
    return "\n".join(lines)


def jcl_to_spring_boot(
    app: SpringBatchApplication,
    base_package: str = "com.generated.batch",
) -> SpringBootApplication:
    """Convert a JCL SpringBatchApplication to a SpringBootApplication.

    This is the JCL adapter entry point.  It produces a
    ``SpringBootApplication`` that the existing ``SpringBootGenerator``
    can consume without modification.

    The generated project is a **structural representation**:
    it compiles, starts, and prints what each JCL step would do.
    It does NOT execute real batch processing.

    Args:
        app: JCL Spring Batch application (from ``modernize_jcl``).
        base_package: target Java package namespace.

    Returns:
        A ``SpringBootApplication`` ready for ``SpringBootGenerator``.
    """
    # One service per JCL job
    services = tuple(
        _build_job_service(job, base_package)
        for job in app.jobs
    )

    # Entry point: run all job services via CommandLineRunner
    entry_point = SpringBootEntryPoint(
        class_name="JclBatchApplication",
        package=base_package,
        application_name=app.application_id,
        selected_service="",  # invoke all services
    )

    # Dependencies: Spring Boot Core + Batch
    dependencies = (
        SpringBootDependency(
            name="spring-boot-starter",
            dependency_type=SpringBootDependencyType.CORE,
        ),
        SpringBootDependency(
            name="spring-boot-starter-batch",
            dependency_type=SpringBootDependencyType.CORE,
        ),
    )

    return SpringBootApplication(
        application_id=app.application_id,
        base_package=base_package,
        services=services,
        entry_point=entry_point,
        dependencies=dependencies,
    )
