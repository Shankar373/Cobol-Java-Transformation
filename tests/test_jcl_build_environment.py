"""BL-071: the canonical offline Maven image must support generated JCL apps.

The JCL adapter declares ``spring-boot-starter-batch`` as a CORE
dependency of every generated project
(``engine/transformation/jcl_spring_boot_adapter.py`` L198-207), but
``Dockerfile.maven-offline`` — the canonical build environment that
compiles every generated Spring Boot project — precached only
``spring-boot-starter``.  Phase 5 §76 audit probe 16 proved the real
consequence: a generated JCL project fails to build with
``Cannot access central … in offline mode and the artifact
org.springframework.boot:spring-boot-starter-batch:jar:3.2.5 has not
been downloaded from it before`` while the adapter docstring claimed
"it compiles, starts".

These Docker-free tests pin both sides of the contract so the mismatch
cannot silently return: the offline image precaches what the lanes emit.
The executed proof lives in ``tests/integration/test_jcl_spring_boot_compile.py``.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_jcl_lane_output_declares_the_spring_batch_starter() -> None:
    """Control: the JCL generator requires spring-boot-starter-batch."""
    from engine.transformation.jcl_consumer import modernize_jcl_from_sources
    from engine.transformation.jcl_spring_boot_adapter import jcl_to_spring_boot

    result = modernize_jcl_from_sources(
        {"s.jcl": "//SJOB JOB CLASS=A\n//S1 EXEC PGM=MAIN\n"},
        application_id="bl071",
    )
    spring_app = jcl_to_spring_boot(
        result.profile.application, base_package="com.generated.jcl"
    )
    dep_names = {dep.name for dep in spring_app.dependencies}
    assert "spring-boot-starter-batch" in dep_names


def test_offline_maven_image_precaches_the_spring_batch_starter() -> None:
    """The canonical build image must carry every declared starter."""
    dockerfile = (REPO_ROOT / "Dockerfile.maven-offline").read_text(
        encoding="utf-8"
    )
    assert "spring-boot-starter-batch" in dockerfile, (
        "Dockerfile.maven-offline does not precache spring-boot-starter-batch: "
        "generated JCL Spring Boot projects cannot compile offline (BL-071)"
    )


def test_generated_jcl_properties_exclude_datasource_autoconfiguration() -> None:
    """The generated JCL app must start without a configured datasource.

    ``spring-boot-starter-batch`` pulls in JDBC auto-configuration; a
    structural JCL profile (no JES/z/OS, no persistence strategy) has no
    datasource URL, so without the exclusion the context fails with
    "Failed to configure a DataSource" and the app exits 1 — the "it
    compiles, **starts**" half of the adapter claim (BL-071).
    """
    from engine.transformation.jcl_consumer import modernize_jcl_from_sources
    from engine.transformation.jcl_spring_boot_adapter import jcl_to_spring_boot
    from engine.transformation.spring_boot_generator import SpringBootGenerator

    result = modernize_jcl_from_sources(
        {"s.jcl": "//SJOB JOB CLASS=A\n//S1 EXEC PGM=MAIN\n"},
        application_id="bl071",
    )
    spring_app = jcl_to_spring_boot(
        result.profile.application, base_package="com.generated.jcl"
    )
    files = SpringBootGenerator().generate_project(spring_app)
    props = next(f for f in files if f.path.endswith("application.properties"))
    assert (
        "spring.autoconfigure.exclude="
        "org.springframework.boot.autoconfigure.jdbc.DataSourceAutoConfiguration"
        in props.source_code
    ), (
        "generated JCL application.properties does not exclude DataSource "
        "auto-configuration: the app cannot start (BL-071)"
    )
