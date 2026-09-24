"""Universal Modernization Pipeline — the SINGLE authoritative orchestrator.

Accepts an unfamiliar COBOL application directory and executes the complete
modernization flow (phases 1-5):

    1. DISCOVERY     — discover programs, copybooks, CALLs, files, dependencies
    2. CAPABILITY    — analyze graph and produce CapabilityReport
    3. PLAN          — generate TransformationPlan from capabilities
    4. TRANSFORM     — transform each program independently (never concatenate)
    5. ASSEMBLE      — assemble all artifacts into ONE Spring Boot application
                      using map_java_application_to_spring_boot + SpringBootGenerator

Phases 6-11 (Docker build, Docker execute, GnuCOBOL oracle, comparison,
evidence, verdict) are handled by VerticalSlicePipeline in the service layer.

This module reuses ALL existing components:
    - ApplicationDiscovery (engine/transformation/application_discovery.py)
    - ApplicationGenerator (engine/transformation/application_generator.py)
    - JavaGenerator (engine/transformation/java_generator.py)
    - java_to_spring_mapping (engine/transformation/java_to_spring_mapping.py)
    - SpringBootGenerator (engine/transformation/spring_boot_generator.py)
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from engine.modernization.capability_analyzer import CapabilityAnalyzer, CapabilityReport
from engine.modernization.completeness_gate import evaluate_verification_readiness
from engine.modernization.transformation_plan import (
    TransformationPlan,
    TransformationPlanGenerator,
)
from engine.transformation.application_discovery import ApplicationDiscovery
from engine.transformation.application_generator import ApplicationGenerator
from engine.transformation.ir import CobolApplication


@dataclass(frozen=True)
class ModernizationConfig:
    """Configuration for the universal modernization pipeline."""
    source_dir: str
    output_dir: str
    application_id: str = ""
    entrypoint: str = ""
    docker_available: bool = True
    allow_partial: bool = False
    enforce_readiness: bool = True


@dataclass
class ModernizationReport:
    """Complete modernization report for an application.

    Carries all outputs from phases 1-5 so the service layer can use them
    for phases 6-11 (Docker validation, comparison, evidence, verdict).
    """
    application_id: str
    source_dir: str
    output_dir: str

    # Discovery results
    discovered_programs: tuple[str, ...] = ()
    discovered_copybooks: tuple[str, ...] = ()
    discovered_calls: tuple[str, ...] = ()
    discovered_files: tuple[str, ...] = ()
    dependency_edges: int = 0

    # Capability analysis
    capability_report: CapabilityReport | None = None
    overall_capability: str = ""
    verification_readiness: str = ""
    readiness_reasons: tuple[str, ...] = ()

    # Transformation plan
    transformation_plan: TransformationPlan | None = None
    transformable_count: int = 0
    skipped_count: int = 0

    # Generation
    generation_success: bool = False
    generation_errors: tuple[str, ...] = ()
    generated_program_ids: tuple[str, ...] = ()

    # Assembly: the Spring Boot project directory and entry point
    generated_project_dir: str = ""
    generated_entrypoint: str = ""

    # Limitations
    limitations: tuple[str, ...] = ()
    recommendations: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "application_id": self.application_id,
            "source_dir": self.source_dir,
            "output_dir": self.output_dir,
            "discovery": {
                "programs": list(self.discovered_programs),
                "copybooks": list(self.discovered_copybooks),
                "calls": list(self.discovered_calls),
                "files": list(self.discovered_files),
                "dependency_edges": self.dependency_edges,
            },
            "capability": self.capability_report.to_dict() if self.capability_report else {},
            "verification_readiness": self.verification_readiness,
            "readiness_reasons": list(self.readiness_reasons),
            "plan": self.transformation_plan.to_dict() if self.transformation_plan else {},
            "transformation": {
                "success": self.generation_success,
                "program_ids": list(self.generated_program_ids),
                "errors": list(self.generation_errors),
            },
            "assembly": {
                "project_dir": self.generated_project_dir,
                "entrypoint": self.generated_entrypoint,
            },
            "limitations": list(self.limitations),
            "recommendations": list(self.recommendations),
        }

    def summary(self) -> str:
        """Human-readable summary."""
        lines = [
            f"=== Modernization Report: {self.application_id} ===",
            f"Source: {self.source_dir}",
            f"Output: {self.output_dir}",
            "",
            "DISCOVERY:",
            f"  Programs: {', '.join(self.discovered_programs)}",
            f"  Copybooks: {', '.join(self.discovered_copybooks) or 'none'}",
            f"  CALLs: {', '.join(self.discovered_calls) or 'none'}",
            f"  Dependency edges: {self.dependency_edges}",
            "",
            "CAPABILITY:",
            f"  Overall: {self.overall_capability}",
        ]
        if self.capability_report:
            r = self.capability_report
            lines.append(f"  Supported: {r.supported_count}, Partial: {r.partial_count}, Unsupported: {r.unsupported_count}, Unavailable: {r.unavailable_count}")

        lines.extend([
            "",
            "TRANSFORMATION:",
            f"  Transformable: {self.transformable_count}, Skipped: {self.skipped_count}",
            f"  Generation success: {self.generation_success}",
        ])
        if self.generation_errors:
            for err in self.generation_errors:
                lines.append(f"  Error: {err}")

        lines.extend([
            "",
            "ASSEMBLY:",
            f"  Project dir: {self.generated_project_dir or 'N/A'}",
            f"  Entrypoint: {self.generated_entrypoint or 'N/A'}",
        ])

        if self.limitations:
            lines.extend(["", "LIMITATIONS:"])
            for lim in self.limitations:
                lines.append(f"  - {lim}")

        if self.recommendations:
            lines.extend(["", "RECOMMENDATIONS:"])
            for rec in self.recommendations:
                lines.append(f"  - {rec}")

        return "\n".join(lines)


class UniversalModernizationPipeline:
    """The SINGLE authoritative orchestrator for COBOL → Java modernization.

    Executes phases 1-5 of the universal modernization flow:
      Discovery → Capability → Plan → Transform → Spring Boot Assembly

    Phases 6-11 (Docker build/execute, oracle, comparison, evidence,
    verdict) are handled by VerticalSlicePipeline in the service layer.

    Usage:
        pipeline = UniversalModernizationPipeline(config)
        report = pipeline.execute()
        # report.generated_project_dir → feed to VerticalSlicePipeline
    """

    def __init__(self, config: ModernizationConfig) -> None:
        self._config = config
        self._discovery = ApplicationDiscovery()
        self._generator = ApplicationGenerator()
        self._capability_analyzer = CapabilityAnalyzer(
            docker_available=config.docker_available,
        )
        self._plan_generator = TransformationPlanGenerator()

    def execute(self, progress=None) -> ModernizationReport:
        """Execute the complete modernization flow (phases 1-5)."""
        source_path = Path(self._config.source_dir)
        output_path = Path(self._config.output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        report = ModernizationReport(
            application_id=self._config.application_id or source_path.name,
            source_dir=str(source_path),
            output_dir=str(output_path),
        )

        # Phase 1: DISCOVERY
        if progress:
            progress("DISCOVERING")
        try:
            application = self._discovery.discover(
                source_path,
                application_id=self._config.application_id or source_path.name,
            )
            report = self._fill_discovery(report, application)
        except Exception as e:
            report.limitations = (f"Discovery failed: {e}",)
            return report
        if progress:
            progress("DISCOVERY_COMPLETED")

        # Phase 2: CAPABILITY ANALYSIS
        if progress:
            progress("ANALYZING")
        capability_report = self._capability_analyzer.analyze(application)
        report.capability_report = capability_report
        report.overall_capability = capability_report.overall_level.value

        # Fail closed before transformation. Unsupported, unavailable, and
        # partial capabilities cannot silently become a "complete" artifact.
        readiness = evaluate_verification_readiness(
            capability_report,
            allow_partial=self._config.allow_partial,
        )
        report.verification_readiness = readiness.readiness.value
        report.readiness_reasons = readiness.reasons
        if self._config.enforce_readiness and not readiness.ready:
            report.limitations = readiness.reasons
            report.recommendations = (
                "Resolve blocked capabilities or explicitly enable exploratory partial mode",
            )
            return report

        if progress:
            progress("ANALYSIS_COMPLETED")

        # Phase 3: TRANSFORMATION PLAN
        if progress:
            progress("PLANNING")
        plan = self._plan_generator.generate(
            application, capability_report, self._config.entrypoint,
        )
        report.transformation_plan = plan
        report.transformable_count = plan.transformable_programs
        report.skipped_count = plan.skipped_programs
        if progress:
            progress("PLAN_COMPLETED")

        # Phase 4: TRANSFORM (per-program, never concatenate)
        if progress:
            progress("TRANSFORMING")
        try:
            gen_result = self._generator.generate(
                application,
                entrypoint=self._config.entrypoint,
                source_root=source_path,
            )
            if not gen_result.success:
                report.generation_errors = gen_result.errors
                report.limitations = ("Transformation failed",) + gen_result.errors
                return report
            if gen_result.java_application is None:
                report.generation_errors = ("Transformation produced no Java application",)
                report.limitations = ("Transformation produced no Java application",)
                return report
        except Exception as e:
            report.generation_errors = (str(e),)
            report.limitations = (f"Transformation exception: {e}",)
            return report

        report.generation_success = True
        report.generated_program_ids = gen_result.program_ids

        # Phase 5: ASSEMBLY via Spring Boot mapping (same path as the service)
        if progress:
            progress("ASSEMBLING")
        try:
            project_dir, spring_entry = self._assemble_spring_boot(
                gen_result.java_application,
                entry_program=self._config.entrypoint or "",
                copybook_models=gen_result.copybook_models,
                output_prefix="pipeline-",
            )
            report.generated_project_dir = str(project_dir)
            report.generated_entrypoint = spring_entry
        except Exception as e:
            report.limitations = (f"Assembly failed: {e}",)
            return report
        if progress:
            progress("ASSEMBLY_COMPLETED")

        # Phase 6: LIMITATIONS AND RECOMMENDATIONS
        report.limitations, report.recommendations = self._derive_limitations(report)

        return report

    def _assemble_spring_boot(
        self,
        java_application,
        entry_program: str = "",
        copybook_models=(),
        output_prefix: str = "generated-",
    ) -> tuple[Path, str]:
        """Map JavaApplication to Spring Boot and write the project.

        Single-mapping-pass: reuses the exact same code path as the service.
        """
        from engine.transformation.java_to_spring_mapping import (
            map_java_application_to_spring_boot,
        )
        from engine.transformation.spring_boot_generator import SpringBootGenerator

        spring_app = map_java_application_to_spring_boot(
            java_application,
            entry_program=entry_program,
            copybook_models=copybook_models,
        )
        violations = spring_app.validate()
        if violations:
            raise RuntimeError(
                "Spring Boot mapping failed: " + "; ".join(violations)
            )

        files = SpringBootGenerator().generate_project(spring_app)
        if not files:
            raise RuntimeError("Spring Boot generation produced no files")

        project_dir = Path(tempfile.mkdtemp(prefix=output_prefix))
        project_dir.mkdir(parents=True, exist_ok=True)
        resolved_root = project_dir.resolve()
        for gen_file in files:
            rel = getattr(gen_file, "path", "") or gen_file.filename
            parts = [
                p for p in Path(rel).parts
                if p not in ("", ".", "..") and ":" not in p
            ]
            if not parts:
                continue
            target = (resolved_root / Path(*parts)).resolve()
            if target != resolved_root and resolved_root not in target.parents:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(gen_file.source_code, encoding="utf-8")

        entry = spring_app.entry_point
        entry_fqn = (
            f"{entry.package}.{entry.class_name}"
            if entry and entry.package
            else (entry.class_name if entry else "")
        )
        if not entry_fqn:
            raise RuntimeError("Spring Boot mapping produced no entry point")
        return project_dir, entry_fqn

    def _fill_discovery(self, report: ModernizationReport, app: CobolApplication) -> ModernizationReport:
        """Fill discovery results into the report."""
        return ModernizationReport(
            application_id=report.application_id,
            source_dir=report.source_dir,
            output_dir=report.output_dir,
            discovered_programs=tuple(u.program_id for u in app.programs),
            discovered_copybooks=app.copybooks,
            discovered_calls=tuple(
                f"{e.source}->{e.target}"
                for e in app.edges if e.edge_type == "CALL"
            ),
            discovered_files=tuple(
                e.target for e in app.edges
                if e.edge_type in ("FILE_READ", "FILE_WRITE")
            ),
            dependency_edges=len(app.edges),
        )

    def _derive_limitations(
        self,
        report: ModernizationReport,
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """Derive limitations and recommendations from the report."""
        limitations: list[str] = []
        recommendations: list[str] = []

        if report.capability_report:
            cap = report.capability_report
            if cap.unsupported_count > 0:
                limitations.append(
                    f"{cap.unsupported_count} component(s) contain unsupported constructs"
                )
                recommendations.append(
                    "Add transformer support for unsupported constructs or manual intervention"
                )
            if cap.unavailable_count > 0:
                limitations.append(
                    f"{cap.unavailable_count} component(s) require unavailable infrastructure"
                )
                recommendations.append("Ensure Docker is running with required images")

        if not report.generation_success:
            limitations.append("Java generation did not complete successfully")
            recommendations.append("Review COBOL source for parser limitations")

        if not limitations:
            limitations = ("No limitations identified",)

        if not recommendations:
            recommendations = ()

        return tuple(limitations), tuple(recommendations)
