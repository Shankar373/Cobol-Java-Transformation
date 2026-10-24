"""BL-064 focused gate: every copybook model file is emitted exactly once.

``SpringBootGenerator.generate_project`` appended ``application.models``
twice — the original M7 loop plus a second loop added later by
``fa0fa62a`` without removing the first — so the output list carried each
model class file twice. Duplicate same-package classes fail at ``javac``
(fail-closed, no false green), breaking every copybook workload on the
Spring Boot lane.

Acceptance (docs/BACKLOG.md BL-064):
1. each model class file appears exactly once in the generated file list;
2. all output paths of a model-bearing application are globally unique;
3. non-model emission unchanged — control with a model-less application;
4. generator tests green.
"""

from __future__ import annotations

from collections import Counter

from engine.transformation.spring_boot_generator import SpringBootGenerator
from engine.transformation.spring_boot_ir import (
    SpringBootApplication,
    SpringBootModel,
)

MODEL_PACKAGE = "com.generated.app.model"
MODEL_DIR = f"src/main/java/{MODEL_PACKAGE.replace('.', '/')}"


def _model(name: str) -> SpringBootModel:
    return SpringBootModel(
        name=name,
        package=MODEL_PACKAGE,
        source_copybook=name.upper(),
    )


def _app(*models: SpringBootModel) -> SpringBootApplication:
    return SpringBootApplication(application_id="bl064", models=models)


def _counts(files) -> Counter:
    return Counter(f.path for f in files)


def _duplicates(files) -> list[str]:
    return [p for p, n in _counts(files).items() if n > 1]


class TestModelEmissionIsUnique:
    def test_single_model_emitted_exactly_once(self):
        files = SpringBootGenerator().generate_project(
            _app(_model("CommonRecord"))
        )
        counts = _counts(files)
        assert counts[f"{MODEL_DIR}/CommonRecord.java"] == 1, counts

    def test_two_models_emitted_once_each(self):
        files = SpringBootGenerator().generate_project(
            _app(_model("CommonRecord"), _model("AuditRecord"))
        )
        counts = _counts(files)
        assert counts[f"{MODEL_DIR}/CommonRecord.java"] == 1, counts
        assert counts[f"{MODEL_DIR}/AuditRecord.java"] == 1, counts

    def test_all_output_paths_of_model_app_are_unique(self):
        files = SpringBootGenerator().generate_project(
            _app(_model("CommonRecord"))
        )
        assert _duplicates(files) == [], _duplicates(files)


def test_model_less_application_output_paths_stay_unique():
    """Control: emission outside the models loop is already duplicate-free."""
    files = SpringBootGenerator().generate_project(
        SpringBootApplication(application_id="bl064")
    )
    assert _duplicates(files) == [], _duplicates(files)
