"""Phase 8 P0 — §32 Runtime Adapter Architecture (BL-088).

Proves, fail-closed and deterministically:
- the Master README §32 example configuration keys are accepted with the
  documented shape and defaults;
- every unsupported value raises ``ValueError`` naming the field, the
  value, and the supported set (config AND adapter lookup AND plan);
- assembly dispatches through the runtime-adapter registry — never a
  silent spring fallback for a non-spring target;
- the plan's ``assembly.output_type`` records the configured target;
- default configuration reproduces the original Spring Boot pipeline
  output (identical file set to an explicit §32 spring_boot run);
- the single shared COBOL parser / semantic transformer path is reused
  (both targets transform through the same generator; only assembly
  differs).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from engine.modernization.pipeline import (
    ModernizationConfig,
    ModernizationReport,
    UniversalModernizationPipeline,
)
from engine.modernization.transformation_plan import (
    TransformationPlanGenerator,
)
from engine.transformation.runtime_adapters import (
    SUPPORTED_TARGET_RUNTIMES,
    RuntimeAdapterNotImplementedError,
    RuntimeTargetConfig,
    get_runtime_adapter,
    plan_output_type_for,
)
from engine.transformation.java_generator import JavaGenerator  # noqa: F401  (shared-transform proof below)
from engine.transformation.spring_boot_generator import SpringBootGenerator  # noqa: F401

FIXTURE_DIR = (
    Path(__file__).resolve().parent.parent
    / "fixtures"
    / "workload-universal"
    / "cobol"
)


class TestSection32Configuration:
    def test_modernization_config_accepts_section32_keys(self):
        config = ModernizationConfig(
            source_dir="src",
            output_dir="out",
            target_runtime="spring_boot",
            java_version="21",
            build_tool="maven",
            packaging="jar",
            execution_mode="batch",
        )
        assert config.target_runtime == "spring_boot"
        assert config.runtime_config == RuntimeTargetConfig()

    def test_defaults_match_section32_example(self):
        config = ModernizationConfig(source_dir="s", output_dir="o")
        assert config.target_runtime == "spring_boot"
        assert config.java_version == "21"
        assert config.build_tool == "maven"
        assert config.packaging == "jar"
        assert config.execution_mode == "batch"
        assert RuntimeTargetConfig() == RuntimeTargetConfig(
            target_runtime="spring_boot",
            java_version="21",
            build_tool="maven",
            packaging="jar",
            execution_mode="batch",
        )

    @pytest.mark.parametrize(
        ("field", "bad_value"),
        [
            ("target_runtime", "websphere"),
            ("target_runtime", "SPRING_BOOT"),
            ("target_runtime", ""),
            ("java_version", "8"),
            ("build_tool", "gradle"),
            ("packaging", "war"),
            ("execution_mode", "interactive"),
        ],
    )
    def test_unknown_value_fails_closed_naming_field_value_and_set(
        self, field, bad_value
    ):
        kwargs = {
            "target_runtime": "spring_boot",
            "java_version": "21",
            "build_tool": "maven",
            "packaging": "jar",
            "execution_mode": "batch",
        }
        kwargs[field] = bad_value
        with pytest.raises(ValueError) as excinfo:
            RuntimeTargetConfig(**kwargs)
        message = str(excinfo.value)
        assert f"invalid {field}" in message
        assert repr(bad_value) in message
        assert "supported" in message

    @pytest.mark.parametrize(
        "bad_target", ["websphere", "SPRING_BOOT", "spring-boot"]
    )
    def test_modernization_config_rejects_unknown_target(self, bad_target):
        with pytest.raises(ValueError) as excinfo:
            ModernizationConfig(
                source_dir="s", output_dir="o", target_runtime=bad_target
            )
        assert "invalid target_runtime" in str(excinfo.value)
        assert repr(bad_target) in str(excinfo.value)

    def test_all_section32_targets_validate_as_config(self):
        for target in SUPPORTED_TARGET_RUNTIMES:
            config = ModernizationConfig(
                source_dir="s", output_dir="o", target_runtime=target
            )
            assert config.target_runtime == target


class TestRuntimeAdapterRegistry:
    def test_spring_boot_adapter_registered(self):
        adapter = get_runtime_adapter("spring_boot")
        assert adapter.target_runtime == "spring_boot"
        assert type(adapter).__name__ == "SpringBootRuntimeAdapter"

    def test_plain_java_adapter_implemented(self):
        # BL-089 (Phase 8 batch P1) implemented plain_java.
        adapter = get_runtime_adapter("plain_java")
        assert adapter.target_runtime == "plain_java"
        assert type(adapter).__name__ == "PlainJavaRuntimeAdapter"

    def test_pending_jakarta_target_fails_closed(self):
        # Staged delivery: BL-090 (jakarta_ee) lands in Phase 8 batch P2.
        # Until then the lookup must fail closed with an explicit
        # "not implemented yet" error — never a silent spring fallback.
        with pytest.raises(RuntimeAdapterNotImplementedError) as excinfo:
            get_runtime_adapter("jakarta_ee")
        message = str(excinfo.value)
        assert "'jakarta_ee'" in message
        assert "not implemented yet" in message
        assert "spring_boot" in message
        assert "plain_java" in message  # implemented set is named truthfully

    @pytest.mark.parametrize("bad", ["tomcat", "springboot", "PLAIN_JAVA", ""])
    def test_unknown_target_fails_closed_with_supported_set(self, bad):
        with pytest.raises(ValueError) as excinfo:
            get_runtime_adapter(bad)
        assert "invalid target_runtime" in str(excinfo.value)
        for target in SUPPORTED_TARGET_RUNTIMES:
            assert target in str(excinfo.value)

    @pytest.mark.parametrize(
        ("target", "expected"),
        [
            ("spring_boot", "SPRING_BOOT"),
            ("plain_java", "NATIVE_JAVA"),
            ("jakarta_ee", "JAKARTA_EE"),
        ],
    )
    def test_plan_output_type_mapping(self, target, expected):
        assert plan_output_type_for(target) == expected

    def test_plan_output_type_unknown_fails_closed(self):
        with pytest.raises(ValueError) as excinfo:
            plan_output_type_for("tomcat")
        assert "invalid target_runtime" in str(excinfo.value)

    def test_adapters_share_the_single_semantic_transform(self):
        # §32: "Do not duplicate the COBOL parser or semantic transformer
        # for every runtime." The adapter module must not carry its own
        # parser/pipeline — it assembles IR produced by the ONE shared
        # transformation path.
        import inspect

        import engine.transformation.runtime_adapters as mod

        source = inspect.getsource(mod)
        assert "CobolParser" not in source
        assert "UniversalModernizationPipeline" not in source
        assert "map_java_application_to_spring_boot" in source  # shared mapper
        assert hasattr(SpringBootGenerator, "generate_project")
        assert hasattr(JavaGenerator, "generate_from_java")
        # Registry keys are exactly the implemented subset of §32 targets.
        from engine.transformation.runtime_adapters import (
            _ADAPTER_FACTORIES,
            implemented_target_runtimes,
        )

        assert set(_ADAPTER_FACTORIES) == set(implemented_target_runtimes())
        assert set(_ADAPTER_FACTORIES) <= set(SUPPORTED_TARGET_RUNTIMES)
        assert set(_ADAPTER_FACTORIES) == {"spring_boot", "plain_java"}


class TestPlanTruth:
    def test_plan_records_configured_target(self):
        import json

        from engine.modernization.capability_analyzer import CapabilityAnalyzer
        from engine.transformation.application_discovery import ApplicationDiscovery

        app = ApplicationDiscovery().discover(
            FIXTURE_DIR, application_id="plan-target"
        )
        report = CapabilityAnalyzer(docker_available=False).analyze(app)
        plan = TransformationPlanGenerator().generate(
            app, report, "", assembly_output_type="SPRING_BOOT"
        )
        assert plan.assembly.output_type == "SPRING_BOOT"
        assert json.dumps(plan.to_dict())  # serializable as before

    @pytest.mark.parametrize(
        "output_type", ["NATIVE_JAVA", "JAKARTA_EE", "SPRING_BOOT"]
    )
    def test_plan_accepts_valid_vocabulary(self, output_type):
        from engine.modernization.capability_analyzer import CapabilityAnalyzer
        from engine.transformation.application_discovery import ApplicationDiscovery

        app = ApplicationDiscovery().discover(
            FIXTURE_DIR, application_id="plan-target"
        )
        report = CapabilityAnalyzer(docker_available=False).analyze(app)
        plan = TransformationPlanGenerator().generate(
            app, report, "", assembly_output_type=output_type
        )
        assert plan.assembly.output_type == output_type

    def test_plan_rejects_unknown_output_type(self):
        from engine.modernization.capability_analyzer import CapabilityAnalyzer
        from engine.transformation.application_discovery import ApplicationDiscovery

        app = ApplicationDiscovery().discover(
            FIXTURE_DIR, application_id="plan-target"
        )
        report = CapabilityAnalyzer(docker_available=False).analyze(app)
        with pytest.raises(ValueError) as excinfo:
            TransformationPlanGenerator().generate(
                app, report, "", assembly_output_type="WEBSPHERE"
            )
        assert "invalid assembly_output_type" in str(excinfo.value)


_HELLO_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HELLO.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-NUM  PIC 9(4) VALUE 42.
       PROCEDURE DIVISION.
           DISPLAY WS-NUM
           STOP RUN.
"""


def _write_hello(root: Path) -> Path:
    src = root / "src"
    src.mkdir(parents=True)
    (src / "HELLO.cob").write_text(_HELLO_SOURCE, encoding="utf-8")
    return src


def _project_file_set(project_dir: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    for path in sorted(project_dir.rglob("*")):
        if path.is_file():
            files[str(path.relative_to(project_dir))] = path.read_text(
                encoding="utf-8"
            )
    return files


class TestPipelineAssemblyDispatch:
    def test_default_config_reproduces_explicit_spring_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            default_src = _write_hello(root / "a")
            explicit_src = _write_hello(root / "b")
            default_report = UniversalModernizationPipeline(
                ModernizationConfig(
                    source_dir=str(default_src),
                    output_dir=str(root / "default"),
                    application_id="target-equal",
                    entrypoint="HELLO",
                    docker_available=True,
                )
            ).execute()
            explicit_report = UniversalModernizationPipeline(
                ModernizationConfig(
                    source_dir=str(explicit_src),
                    output_dir=str(root / "explicit"),
                    application_id="target-equal",
                    entrypoint="HELLO",
                    docker_available=True,
                    target_runtime="spring_boot",
                    java_version="21",
                    build_tool="maven",
                    packaging="jar",
                    execution_mode="batch",
                )
            ).execute()

            assert default_report.generation_success
            assert explicit_report.generation_success
            assert default_report.target_runtime == "spring_boot"
            assert explicit_report.target_runtime == "spring_boot"
            default_files = _project_file_set(
                Path(default_report.generated_project_dir)
            )
            explicit_files = _project_file_set(
                Path(explicit_report.generated_project_dir)
            )
            assert list(default_files) == list(explicit_files)
            assert default_files == explicit_files
            # Plan truth + report truth
            assert (
                default_report.transformation_plan.assembly.output_type
                == "SPRING_BOOT"
            )
            assert (
                default_report.to_dict()["assembly"]["target_runtime"]
                == "spring_boot"
            )

    def test_unimplemented_target_fails_closed_before_any_phase(self):
        # jakarta_ee is the remaining staged target (BL-090, batch P2).
        pending_target = "jakarta_ee"
        with tempfile.TemporaryDirectory() as tmpdir:
            report = UniversalModernizationPipeline(
                ModernizationConfig(
                    source_dir=str(FIXTURE_DIR),
                    output_dir=str(Path(tmpdir) / "out"),
                    application_id="target-pending",
                    docker_available=False,
                    target_runtime=pending_target,
                )
            ).execute()
            assert report.generation_success is False
            assert report.discovered_programs == ()
            assert report.generated_project_dir == ""
            limitation = "; ".join(report.limitations)
            assert "Runtime adapter unavailable" in limitation
            assert repr(pending_target) in limitation
            assert "not implemented yet" in limitation

    def test_adapter_dispatch_runs_before_discovery(self):
        # The fail-closed lookup happens before Phase 1, so nothing is
        # discovered/analyzed/transformed for an unusable target.
        with tempfile.TemporaryDirectory() as tmpdir:
            report = UniversalModernizationPipeline(
                ModernizationConfig(
                    source_dir=str(FIXTURE_DIR),
                    output_dir=str(Path(tmpdir) / "out"),
                    application_id="target-pending-2",
                    docker_available=False,
                    target_runtime="jakarta_ee",
                )
            ).execute()
            assert report.capability_report is None
            assert report.transformation_plan is None
            assert report.generation_success is False


_COPY_SOURCE = """\\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MAIN.
       COPY BOOKX.
       PROCEDURE DIVISION.
           DISPLAY FLD-A
           STOP RUN.
"""

_COPYBOOK = """\\
       01  REC.
           05  FLD-A  PIC X(10) VALUE 'HELLO'.
           05  FLD-B  PIC 9(4) VALUE 42.
"""


class TestPlainJavaTarget:
    """BL-089 — plain_java assembly through the §32 adapter registry."""

    def test_plain_pipeline_run_emits_dependency_free_maven_project(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            src = root / "src"
            src.mkdir()
            (src / "HELLO.cob").write_text(_HELLO_SOURCE, encoding="utf-8")
            report = UniversalModernizationPipeline(
                ModernizationConfig(
                    source_dir=str(src),
                    output_dir=str(root / "out"),
                    application_id="plain-hello",
                    entrypoint="HELLO",
                    docker_available=True,
                    target_runtime="plain_java",
                )
            ).execute()

            assert report.generation_success is True, report.generation_errors
            assert report.target_runtime == "plain_java"
            assert (
                report.transformation_plan.assembly.output_type == "NATIVE_JAVA"
            )
            files = _project_file_set(Path(report.generated_project_dir))
            assert "pom.xml" in files
            assert "src/main/java/Hello.java" in files
            pom = files["pom.xml"]
            # §33 shape: dependency-free, jar packaging, configured release.
            assert "<dependency>" not in pom
            assert "<maven.compiler.release>21</maven.compiler.release>" in pom
            assert "<mainClass>Hello</mainClass>" in pom
            # No Spring coupling anywhere in the project (§32: adapters
            # select the runtime; the shared transform never hardwires one).
            for rel, content in files.items():
                assert "spring" not in content.lower(), rel
            # Bounded claim: the report discloses generation-only scope.
            assert any("plain_java" in line for line in report.limitations)

    def test_plain_target_honors_configured_java_version(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            src = root / "src"
            src.mkdir()
            (src / "HELLO.cob").write_text(_HELLO_SOURCE, encoding="utf-8")
            report = UniversalModernizationPipeline(
                ModernizationConfig(
                    source_dir=str(src),
                    output_dir=str(root / "out"),
                    application_id="plain-17",
                    entrypoint="HELLO",
                    docker_available=True,
                    target_runtime="plain_java",
                    java_version="17",
                )
            ).execute()
            assert report.generation_success is True, report.generation_errors
            pom = _project_file_set(Path(report.generated_project_dir))["pom.xml"]
            assert "<maven.compiler.release>17</maven.compiler.release>" in pom

    def test_plain_target_materializes_copybook_models(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            src = root / "src"
            src.mkdir()
            (src / "MAIN.cob").write_text(_COPY_SOURCE, encoding="utf-8")
            (src / "BOOKX.cpy").write_text(_COPYBOOK, encoding="utf-8")
            report = UniversalModernizationPipeline(
                ModernizationConfig(
                    source_dir=str(src),
                    output_dir=str(root / "out"),
                    application_id="plain-model",
                    entrypoint="MAIN",
                    docker_available=True,
                    target_runtime="plain_java",
                )
            ).execute()
            assert report.generation_success is True, report.generation_errors
            files = _project_file_set(Path(report.generated_project_dir))
            model_files = [
                rel for rel in files if "BookxRecord" in rel
            ]
            assert model_files, sorted(files)
            model_rel = model_files[0]
            # Package comes from the shared copybook-model builder (single
            # source of truth); the adapter only fills a missing package.
            assert model_rel.startswith("src/main/java/")
            assert model_rel.endswith("/model/BookxRecord.java")
            model_src = files[model_rel]
            # VALUE initializers survive (no silent loss vs the Spring lane).
            assert '"HELLO     "' in model_src
            assert "FLD_B" in model_src or "fld_b" in model_src.lower()

    def test_plain_unknown_entrypoint_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            src = root / "src"
            src.mkdir()
            (src / "HELLO.cob").write_text(_HELLO_SOURCE, encoding="utf-8")
            report = UniversalModernizationPipeline(
                ModernizationConfig(
                    source_dir=str(src),
                    output_dir=str(root / "out"),
                    application_id="plain-bad-entry",
                    entrypoint="NOPE",
                    docker_available=True,
                    target_runtime="plain_java",
                )
            ).execute()
            # Assembly failures surface as an empty project directory plus
            # a named limitation (pre-existing pipeline contract; the API
            # layer refuses to continue without a project dir).
            assert report.generated_project_dir == ""
            limitation = "; ".join(report.limitations)
            assert "Assembly failed" in limitation
            assert "NOPE" in limitation

    def test_spring_default_unchanged_by_plain_adapter(self):
        # The default path still assembles a Spring project (pom with the
        # spring-boot parent) — P1 must not have leaked plain-java shape
        # into the default target.
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            src = root / "src"
            src.mkdir()
            (src / "HELLO.cob").write_text(_HELLO_SOURCE, encoding="utf-8")
            report = UniversalModernizationPipeline(
                ModernizationConfig(
                    source_dir=str(src),
                    output_dir=str(root / "out"),
                    application_id="spring-default",
                    entrypoint="HELLO",
                    docker_available=True,
                )
            ).execute()
            assert report.generation_success is True, report.generation_errors
            files = _project_file_set(Path(report.generated_project_dir))
            pom = files["pom.xml"]
            assert "spring-boot-starter-parent" in pom


class TestReportCarriesTarget:
    def test_report_defaults_and_serialisation(self):
        report = ModernizationReport(
            application_id="x", source_dir="s", output_dir="o"
        )
        assert report.target_runtime == "spring_boot"
        assert report.to_dict()["assembly"]["target_runtime"] == "spring_boot"

    def test_back_compat_private_spring_helper_resolves_through_registry(
        self, monkeypatch
    ):
        # _assemble_spring_boot remains a thin delegation for older
        # callers; it must resolve the adapter through the registry
        # (never a private copy of the assembly logic).
        import engine.modernization.pipeline as pipeline_mod
        from engine.transformation.runtime_adapters import AssemblyOutcome

        calls: list[str] = []

        class _FakeAdapter:
            target_runtime = "spring_boot"

            def assemble(self, java_application, **kwargs):
                calls.append(kwargs.get("entry_program", ""))
                return AssemblyOutcome(
                    project_dir=Path("/tmp/adapter-delegate"),
                    entrypoint="com.example.Entry",
                )

        monkeypatch.setattr(
            pipeline_mod,
            "get_runtime_adapter",
            lambda name: calls.append(name) or _FakeAdapter(),
        )
        instance = object.__new__(pipeline_mod.UniversalModernizationPipeline)
        project_dir, entry = instance._assemble_spring_boot(
            object(), entry_program="MAIN"
        )
        assert calls[0] == "spring_boot"  # registry lookup by name
        assert calls[1] == "MAIN"  # arguments forwarded unchanged
        assert entry == "com.example.Entry"
        assert project_dir == Path("/tmp/adapter-delegate")
