"""M7 (Lane C): COPYBOOK semantic materialization — focused tests.

Covers the mission's 10 cases:
  1. COPY resolves to the actual .cpy file.
  2. Missing copybook produces a controlled diagnostic.
  3. Copybook group hierarchy is represented.
  4. PIC fields are represented.
  5. OCCURS survives.
  6. One shared copybook used by two programs -> one model, no duplicates.
  7. No .cpy becomes an executable Java program.
  8. Generated Java uses copybook-defined fields.
  9. Spring Boot project contains the expected model (SKIPPED: blocked on
     FRNC-owned spring_boot_ir.py / spring_boot_generator.py wiring).
 10. No-concatenation invariant holds (source-untouched test here + existing
     suites run green, reported separately).

Only Lane-C-owned files are exercised for writes: the two new modules
under engine/transformation/. FRNC-owned files are imported read-only
(parser reuse, mapping reuse, discovery behaviour lock-in) — never edited.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.transformation.copybook_model import (
    build_copybook_model_class,
    flatten_records,
    generate_copybook_model_sources,
    materialize_copybooks_into_program,
    parse_copybook,
    plan_shared_models,
    render_model_class,
    rendered_model_path,
    to_model_class_name,
)
from engine.transformation.copybook_resolver import (
    AmbiguousCopybookError,
    CopybookResolutionError,
    ResolvedCopybook,
    resolve_application_copybooks,
    resolve_copybook,
)
from engine.transformation.ir import CobolProgram, DataItem, PicType


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
           05 CLAIM-TAGS PIC X(5) OCCURS 3 TIMES.
"""


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "MAIN.cob").write_text(MAIN_COB, encoding="utf-8")
    (tmp_path / "COMMON.cpy").write_text(COMMON_CPY, encoding="utf-8")
    return tmp_path


@pytest.fixture()
def model(tmp_path: Path) -> object:
    cpy = tmp_path / "COMMON.cpy"
    cpy.write_text(COMMON_CPY, encoding="utf-8")
    return parse_copybook(cpy)


# ---------------------------------------------------------------------------
# Regression: bare .cpy data-description lines must parse without a
# WORKING-STORAGE SECTION banner (public parse_data_description_lines).
# ---------------------------------------------------------------------------

class TestPublicDataDescriptionInterface:
    def test_parse_data_description_lines_parses_bare_copybook(self) -> None:
        from engine.transformation.cobol_parser import CobolParser

        records = CobolParser().parse_data_description_lines(
            COMMON_CPY.splitlines()
        )
        assert len(records) == 1
        root = records[0]
        assert root.name == "CLAIM-REC"
        assert root.level == 1
        children = {c.name: c for c in root.children}
        assert set(children) == {"CLAIM-ID", "CLAIM-AMOUNT", "CLAIM-TAGS"}
        assert children["CLAIM-ID"].pic_type == PicType.ALPHANUMERIC
        assert children["CLAIM-ID"].pic_length == 10
        assert children["CLAIM-AMOUNT"].pic_type == PicType.NUMERIC
        assert children["CLAIM-TAGS"].occurs == 3

    def test_parse_data_description_lines_ignores_non_data_lines(self) -> None:
        from engine.transformation.cobol_parser import CobolParser

        text = (
            "       IDENTIFICATION DIVISION.\n"
            "* comment only\n"
            + COMMON_CPY +
            "\n       PROCEDURE DIVISION.\n"
            "       STOP RUN.\n"
        )
        records = CobolParser().parse_data_description_lines(text.splitlines())
        assert len(records) == 1
        assert records[0].name == "CLAIM-REC"

    def test_load_workload_copybook_records(self) -> None:
        here = Path(__file__).resolve().parent.parent
        models = parse_copybook(here / "fixtures/workload-copybook/cobol/COMMON.cpy")
        assert models.name == "COMMON"
        assert len(models.records) == 1
        flat = {i.name: i for i in flatten_records(models.records)}
        assert flat["CLAIM-ID"].pic_type == PicType.ALPHANUMERIC
        assert flat["CLAIM-ID"].pic_length == 10
        assert flat["CLAIM-ID"].value == '"C-001"'
        assert flat["CLAIM-AMOUNT"].pic_type == PicType.NUMERIC
        assert flat["CLAIM-AMOUNT"].pic_length == 6
        assert flat["CLAIM-AMOUNT"].value == "500"


# ---------------------------------------------------------------------------
# 1. COPY resolves to the actual .cpy file
# ---------------------------------------------------------------------------

class TestResolution:
    def test_copy_resolves_to_actual_cpy(self, workspace: Path) -> None:
        ref = resolve_copybook("COMMON", (workspace,), program_id="MAIN")
        assert ref.path == workspace / "COMMON.cpy"
        assert ref.program_id == "MAIN"
        assert ref.copybook_name == "COMMON"

    def test_resolution_is_case_insensitive(self, tmp_path: Path) -> None:
        (tmp_path / "Common.cpy").write_text(COMMON_CPY, encoding="utf-8")
        ref = resolve_copybook("common", (tmp_path,))
        assert ref.path == tmp_path / "Common.cpy"

    def test_cpy_beats_other_extensions_deterministically(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "COMMON.cbl").write_text("x", encoding="utf-8")
        (tmp_path / "COMMON.cpy").write_text(COMMON_CPY, encoding="utf-8")
        ref = resolve_copybook("COMMON", (tmp_path,))
        assert ref.path.suffix == ".cpy"


# ---------------------------------------------------------------------------
# 2. Missing copybook -> controlled diagnostic (no silent behaviour)
# ---------------------------------------------------------------------------

class TestMissing:
    def test_collect_reports_missing_without_raising(
        self, workspace: Path
    ) -> None:
        resolved, missing = resolve_application_copybooks(
            (("MAIN", "COMMON"), ("MAIN", "NOPE")), (workspace,)
        )
        assert [r.copybook_name for r in resolved] == ["COMMON"]
        assert len(missing) == 1
        assert missing[0].program_id == "MAIN"
        assert missing[0].copybook_name == "NOPE"
        assert "Missing COPY target: NOPE (in MAIN)" in missing[0].message

    def test_strict_raises_controlled_error(self, workspace: Path) -> None:
        with pytest.raises(CopybookResolutionError, match="NOPE"):
            resolve_copybook("NOPE", (workspace,), program_id="MAIN")

    def test_ambiguity_is_an_error_not_first_match(
        self, tmp_path: Path
    ) -> None:
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()
        (dir_a / "COMMON.cpy").write_text(COMMON_CPY, encoding="utf-8")
        (dir_b / "COMMON.cpy").write_text(COMMON_CPY, encoding="utf-8")
        with pytest.raises(AmbiguousCopybookError) as exc_info:
            resolve_copybook("COMMON", (dir_a, dir_b))
        assert len(exc_info.value.candidates) == 2
        # Collecting API reports it as a controlled diagnostic as well.
        resolved, missing = resolve_application_copybooks(
            (("MAIN", "COMMON"),), (dir_a, dir_b)
        )
        assert resolved == ()
        assert len(missing) == 1


# ---------------------------------------------------------------------------
# 3-5. Semantic model: hierarchy, PIC, OCCURS
# ---------------------------------------------------------------------------

class TestSemanticModel:
    def test_group_hierarchy_represented(self, model) -> None:
        assert len(model.records) == 1
        root = model.records[0]
        assert root.name == "CLAIM-REC"
        assert root.level == 1
        children = {c.name: c for c in root.children}
        assert set(children) == {"CLAIM-ID", "CLAIM-AMOUNT", "CLAIM-TAGS"}
        assert children["CLAIM-ID"].level == 5

    def test_pic_fields_represented(self, model) -> None:
        children = {c.name: c for c in model.records[0].children}
        claim_id = children["CLAIM-ID"]
        assert claim_id.pic_type == PicType.ALPHANUMERIC
        assert claim_id.pic_length == 10
        assert claim_id.value == '"C-001"'
        amount = children["CLAIM-AMOUNT"]
        assert amount.pic_type == PicType.NUMERIC
        assert amount.pic_length == 5
        assert amount.value == "123"

    def test_occurs_survives(self, model) -> None:
        children = {c.name: c for c in model.records[0].children}
        assert children["CLAIM-TAGS"].occurs == 3
        flat = {i.name: i for i in flatten_records(model.records)}
        assert flat["CLAIM-TAGS"].occurs == 3

    def test_model_provenance(self, model, tmp_path: Path) -> None:
        assert model.name == "COMMON"
        assert model.source_path == str(tmp_path / "COMMON.cpy")


# ---------------------------------------------------------------------------
# 3 (merge). Program gains copybook fields; provenance kept; no rewriting
# ---------------------------------------------------------------------------

def _program() -> CobolProgram:
    return CobolProgram(
        program_id="MAIN",
        working_storage=(
            DataItem(
                name="WS-COUNT",
                level=1,
                pic_type=PicType.NUMERIC,
                pic_length=5,
                value="0",
            ),
        ),
        copybooks=("COMMON",),
    )


class TestMerge:
    def test_merge_appends_copybook_fields(self, model) -> None:
        merged, diagnostics = materialize_copybooks_into_program(
            _program(), {"COMMON": model}
        )
        assert diagnostics == () or all(
            d.level != "ERROR" for d in diagnostics
        )
        names = {i.name for i in merged.working_storage}
        assert {"WS-COUNT", "CLAIM-REC"} <= names
        # Provenance preserved: dependency tuple untouched.
        assert merged.copybooks == ("COMMON",)
        assert merged.program_id == "MAIN"

    def test_merge_keeps_program_field_on_collision(self, model) -> None:
        mine = DataItem(
            name="CLAIM-ID", level=1, pic_type=PicType.ALPHANUMERIC,
            pic_length=3, value='"M"',
        )
        prog = CobolProgram(
            program_id="MAIN", working_storage=(mine,), copybooks=("COMMON",)
        )
        merged, diagnostics = materialize_copybooks_into_program(
            prog, {"COMMON": model}
        )
        kept = [i for i in merged.working_storage if i.name == "CLAIM-ID"]
        assert len(kept) == 1  # no duplication
        assert kept[0].pic_length == 3  # program's own definition wins
        assert any(d.code == "COPYBOOK_FIELD_COLLISION" for d in diagnostics)

    def test_merge_reports_unmaterialized_reference(self) -> None:
        merged, diagnostics = materialize_copybooks_into_program(
            _program(), {}
        )
        assert merged.working_storage == _program().working_storage
        assert any(d.code == "COPYBOOK_MODEL_MISSING" for d in diagnostics)

    def test_sources_never_rewritten_or_concatenated(
        self, workspace: Path, model
    ) -> None:
        before_main = (workspace / "MAIN.cob").read_bytes()
        before_cpy = (workspace / "COMMON.cpy").read_bytes()
        materialize_copybooks_into_program(_program(), {"COMMON": model})
        assert (workspace / "MAIN.cob").read_bytes() == before_main
        assert (workspace / "COMMON.cpy").read_bytes() == before_cpy
        assert b"CLAIM-REC" not in before_main  # no textual duplication
        assert b"WS-COUNT" not in before_cpy  # no concatenation either way


# ---------------------------------------------------------------------------
# 6. Shared model: two programs, one copybook -> one plan, no duplicates
# ---------------------------------------------------------------------------

class TestSharedPlan:
    def test_one_plan_for_two_consumers(self, model) -> None:
        resolved, missing = resolve_application_copybooks(
            (("MAIN", "COMMON"), ("PROG2", "COMMON")),
            (Path(model.source_path).parent,),
        )
        assert missing == ()
        plans = plan_shared_models(resolved, {"COMMON": model})
        assert len(plans) == 1
        plan = plans[0]
        assert plan.class_name == "CommonRecord"
        assert plan.package == "com.generated.app.model"
        assert plan.using_programs == ("MAIN", "PROG2")
        field_names = [f.name for f in plan.fields]
        assert len(field_names) == len(set(f.upper() for f in field_names))

    def test_class_naming(self) -> None:
        assert to_model_class_name("COMMON") == "CommonRecord"
        assert to_model_class_name("claim-master") == "ClaimMasterRecord"


# ---------------------------------------------------------------------------
# 7. No .cpy becomes an executable Java program
# ---------------------------------------------------------------------------

class TestNeverExecutable:
    def test_discovery_never_lists_cpy_as_program(
        self, workspace: Path
    ) -> None:
        from engine.transformation.application_discovery import (
            ApplicationDiscovery,
        )

        app = ApplicationDiscovery().discover(
            str(workspace), application_id="m7"
        )
        assert {u.program_id for u in app.programs} == {"MAIN"}
        assert "COMMON" in app.copybooks

    def test_model_class_has_no_executable_shape(self, model) -> None:
        from engine.transformation.copybook_model import plan_shared_models
        from engine.transformation.copybook_resolver import ResolvedCopybook

        plans = plan_shared_models(
            (
                ResolvedCopybook(
                    program_id="MAIN",
                    copybook_name="COMMON",
                    path=Path(model.source_path),
                ),
            ),
            {"COMMON": model},
        )
        cls = build_copybook_model_class(plans[0])
        assert not any(m.name.lower() == "main" for m in cls.methods)
        assert "public static void main" not in render_model_class(cls)


# ---------------------------------------------------------------------------
# 8. Generated Java uses copybook-defined fields
# ---------------------------------------------------------------------------

class TestJavaRepresentation:
    def test_model_fields_come_from_copybook(self, model) -> None:
        from engine.transformation.copybook_model import plan_shared_models
        from engine.transformation.copybook_resolver import ResolvedCopybook

        plans = plan_shared_models(
            (
                ResolvedCopybook(
                    program_id="MAIN",
                    copybook_name="COMMON",
                    path=Path(model.source_path),
                ),
            ),
            {"COMMON": model},
        )
        cls = build_copybook_model_class(plans[0])
        assert cls.name == "CommonRecord"
        assert cls.package == "com.generated.app.model"
        by_name = {f.name: f for f in cls.fields}
        assert set(by_name) == {"CLAIM_ID", "CLAIM_AMOUNT", "CLAIM_TAGS"}
        assert by_name["CLAIM_ID"].java_type.basic_type.value == "String"
        assert by_name["CLAIM_AMOUNT"].java_type.basic_type.value == "int"
        assert not any(f.is_static for f in cls.fields)

    def test_rendered_source_has_fields_accessors_and_path(
        self, model
    ) -> None:
        plans = plan_shared_models(
            (
                ResolvedCopybook(
                    program_id="MAIN",
                    copybook_name="COMMON",
                    path=Path(model.source_path),
                ),
            ),
            {"COMMON": model},
        )
        path, source = generate_copybook_model_sources(plans)[0]
        assert path == (
            "src/main/java/com/generated/app/model/CommonRecord.java"
        )
        assert rendered_model_path(plans[0]) == path
        assert "public class CommonRecord" in source
        assert "private String CLAIM_ID" in source
        assert "private int CLAIM_AMOUNT" in source
        assert "getCLAIM_ID()" in source
        assert "setCLAIM_AMOUNT(" in source
        assert "static void main" not in source


# ---------------------------------------------------------------------------
# 9. Spring Boot project contains the expected model.
#    Proven through the real path in test_copybook_integration_m7.py
#    (TestSpringRepresentation) now that pipeline wiring has landed.
# ---------------------------------------------------------------------------
