"""M7 integration: copybooks through the REAL modernization path.

Exercises, without mocks:
  ApplicationDiscovery
    -> ApplicationGenerator.generate (materialization + shared models)
    -> map_java_application_to_spring_boot (models carried)
    -> SpringBootGenerator.generate_project (model/ emission)

No Docker, no oracle, no file writes outside tmp_path. The full
Docker/oracle/verdict chain is proven separately by the fresh E2E run.
"""

from __future__ import annotations

from pathlib import Path

from engine.transformation.application_discovery import ApplicationDiscovery
from engine.transformation.application_generator import ApplicationGenerator
from engine.transformation.java_to_spring_mapping import (
    map_java_application_to_spring_boot,
)
from engine.transformation.spring_boot_generator import SpringBootGenerator


MAIN_COB = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MAIN.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-COUNT PIC 9(5) VALUE 0.
           COPY COMMON.
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE CLAIM-AMOUNT TO WS-COUNT.
           DISPLAY CLAIM-ID.
           STOP RUN.
"""

PROG2_COB = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROG2.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-FLAG PIC X(1) VALUE 'N'.
           COPY COMMON.
       PROCEDURE DIVISION.
       PROG2-PARA.
           DISPLAY CLAIM-ID.
           STOP RUN.
"""

COMMON_CPY = """\
       01 CLAIM-REC.
           05 CLAIM-ID PIC X(10) VALUE "C-001".
           05 CLAIM-AMOUNT PIC 9(5) VALUE 123.
"""


def _workspace(tmp_path: Path, second: bool = False) -> Path:
    (tmp_path / "MAIN.cob").write_text(MAIN_COB, encoding="utf-8")
    if second:
        (tmp_path / "PROG2.cob").write_text(PROG2_COB, encoding="utf-8")
    (tmp_path / "COMMON.cpy").write_text(COMMON_CPY, encoding="utf-8")
    return tmp_path


def _discover(ws: Path):
    return ApplicationDiscovery().discover(str(ws), application_id="m7-int")


class TestDiscoveryKeepsCopybookAsDependency:
    def test_copy_recorded_never_executable(self, tmp_path: Path) -> None:
        app = _discover(_workspace(tmp_path))
        assert {u.program_id for u in app.programs} == {"MAIN"}
        assert "COMMON" in app.copybooks
        unit = app.get_program("MAIN")
        assert unit is not None
        assert [cb.copybook_name for cb in unit.copybooks] == ["COMMON"]


class TestGeneratorMaterialization:
    def test_fields_materialized_into_program_ir(
        self, tmp_path: Path
    ) -> None:
        app = _discover(_workspace(tmp_path))
        result = ApplicationGenerator().generate(app, entrypoint="Main", source_root=tmp_path)
        assert result.success, result.errors
        java_app = result.java_application
        assert java_app is not None
        prog = java_app.get_program("MAIN")
        assert prog is not None
        assert prog.java_class is not None
        field_names = {f.name for f in prog.java_class.fields}
        # Own field + copybook group + expanded copybook leaves.
        assert {"WS_COUNT", "CLAIM_REC", "CLAIM_ID", "CLAIM_AMOUNT"} <= field_names
        # Provenance preserved on the Java side.
        assert "COMMON" in prog.copybooks

    def test_shared_model_generated_once_for_two_programs(
        self, tmp_path: Path
    ) -> None:
        app = _discover(_workspace(tmp_path, second=True))
        result = ApplicationGenerator().generate(app, source_root=tmp_path)
        assert result.success, result.errors
        assert len(result.copybook_models) == 1
        model = result.copybook_models[0]
        assert model.name == "CommonRecord"
        assert model.package == "com.generated.app.model"
        model_files = [
            f for f in result.generated_files if f.class_name == "CommonRecord"
        ]
        assert len(model_files) == 1
        assert "private String CLAIM_ID" in model_files[0].source_code
        assert "static void main" not in model_files[0].source_code

    def test_model_never_entrypoint(self, tmp_path: Path) -> None:
        app = _discover(_workspace(tmp_path))
        result = ApplicationGenerator().generate(app, entrypoint="CommonRecord", source_root=tmp_path)
        assert result.success, result.errors
        # Even when explicitly requested, a model class is refused.
        assert result.entrypoint != "CommonRecord"
        assert result.entrypoint == "Main"

    def test_sources_remain_separate(self, tmp_path: Path) -> None:
        ws = _workspace(tmp_path)
        before = {
            p.name: p.read_bytes() for p in (ws / "MAIN.cob", ws / "COMMON.cpy")
        }
        app = _discover(ws)
        result = ApplicationGenerator().generate(app, source_root=tmp_path)
        assert result.success, result.errors
        after = {
            p.name: p.read_bytes() for p in (ws / "MAIN.cob", ws / "COMMON.cpy")
        }
        assert before == after
        assert b"CLAIM-REC" not in after["MAIN.cob"]
        assert b"WS-COUNT" not in after["COMMON.cpy"]


class TestDeterministicFailure:
    def test_missing_copybook_fails_with_explicit_error(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "MAIN.cob").write_text(MAIN_COB, encoding="utf-8")
        app = _discover(tmp_path)
        result = ApplicationGenerator().generate(app, source_root=tmp_path)
        assert not result.success
        assert any("COMMON" in e for e in result.errors)

    def test_ambiguous_copybook_fails_with_explicit_error(
        self, tmp_path: Path
    ) -> None:
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()
        (dir_a / "MAIN.cob").write_text(MAIN_COB, encoding="utf-8")
        (dir_a / "COMMON.cpy").write_text(COMMON_CPY, encoding="utf-8")
        (dir_b / "COMMON.cpy").write_text(COMMON_CPY, encoding="utf-8")
        # MAIN.cob lives in dir_a; both dirs are on the search path only
        # if a second program references from dir_b — emulate by discovering
        # the parent holding both plus a PROG2 in dir_b.
        (dir_b / "PROG2.cob").write_text(PROG2_COB, encoding="utf-8")
        app = _discover(tmp_path)
        assert {u.program_id for u in app.programs} == {"MAIN", "PROG2"}
        result = ApplicationGenerator().generate(app, source_root=tmp_path)
        assert not result.success
        assert any("COMMON" in e for e in result.errors)


class TestSpringRepresentation:
    def _spring_app(self, tmp_path: Path):
        app = _discover(_workspace(tmp_path))
        result = ApplicationGenerator().generate(app, entrypoint="Main", source_root=tmp_path)
        assert result.success, result.errors
        assert result.java_application is not None
        spring_app = map_java_application_to_spring_boot(
            result.java_application,
            entry_program="Main",
            copybook_models=result.copybook_models,
        )
        assert spring_app.validate() == []
        return spring_app

    def test_spring_app_carries_model(self, tmp_path: Path) -> None:
        spring_app = self._spring_app(tmp_path)
        assert len(spring_app.models) == 1
        assert spring_app.models[0].name == "CommonRecord"
        assert spring_app.models[0].source_copybook == "COMMON"

    def test_project_contains_model_under_canonical_path(
        self, tmp_path: Path
    ) -> None:
        spring_app = self._spring_app(tmp_path)
        files = SpringBootGenerator().generate_project(spring_app)
        by_path = {f.path: f for f in files}
        model_path = (
            "src/main/java/com/generated/app/model/CommonRecord.java"
        )
        assert model_path in by_path, sorted(by_path)
        source = by_path[model_path].source_code
        assert "public class CommonRecord" in source
        assert "private String CLAIM_ID" in source
        assert "private int CLAIM_AMOUNT" in source
        assert "static void main" not in source

    def test_model_not_service_nor_entrypoint(
        self, tmp_path: Path
    ) -> None:
        spring_app = self._spring_app(tmp_path)
        assert [s.name for s in spring_app.services] == ["Main"]
        assert spring_app.entry_point is not None
        assert spring_app.entry_point.selected_service == "Main"
        assert "CommonRecord" not in spring_app.entry_point.selected_service
