"""Layer 6 migration M4: Java generation takes its application-level inputs through the canonical Application IR.

The parser IR stays the statement-generation authority (programs are mapped from ``unit.program``); the IR supplies the
application-level relationships (call edges for entry selection, COPY references, entry points).  Differential: generation is
byte-identical with and without the IR over every fixture application.  Mutation: a disagreeing IR refuses generation.
Integration: the modernization pipeline hands the generator the IR.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from engine.application_ir.consume import ir_for_application
from engine.transformation import application_generator as generator_module
from engine.transformation.application_discovery import ApplicationDiscovery
from engine.transformation.application_generator import ApplicationGenerator

REPO = Path(__file__).resolve().parents[2]
APP_DIRS = sorted(p for p in (REPO / "fixtures").glob("*/cobol") if p.is_dir())

MAIN = ("       IDENTIFICATION DIVISION.\n       PROGRAM-ID. MAIN.\n       DATA DIVISION.\n       WORKING-STORAGE SECTION.\n"
        "       01 A PIC 9(4).\n       PROCEDURE DIVISION.\n       RUN-IT.\n           CALL 'SUB1' USING A.\n           STOP RUN.\n")
SUB1 = ("       IDENTIFICATION DIVISION.\n       PROGRAM-ID. SUB1.\n       DATA DIVISION.\n       LINKAGE SECTION.\n"
        "       01 P1 PIC 9(4).\n       PROCEDURE DIVISION USING P1.\n       ENTRY-P.\n           GOBACK.\n")


def _result_key(result):
    return (result.success, result.program_ids, result.entrypoint, result.errors,
            tuple((f.filename, f.class_name, f.source_code) for f in result.generated_files))


def _tree(tmp_path: Path) -> Path:
    (tmp_path / "MAIN.cob").write_text(MAIN, encoding="utf-8")
    (tmp_path / "SUB1.cob").write_text(SUB1, encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("directory", APP_DIRS, ids=lambda d: d.parent.name)
def test_differential_generation_is_identical_with_and_without_the_ir(directory):
    try:
        app = ApplicationDiscovery().discover(directory)
    except Exception:       # noqa: BLE001 - nothing to generate
        pytest.skip("discovery refused this application")
    ir = ir_for_application(app, directory)
    legacy = ApplicationGenerator().generate(app, source_root=directory)
    via_ir = ApplicationGenerator().generate(app, source_root=directory, ir=ir)
    assert _result_key(via_ir) == _result_key(legacy)


def test_a_generating_application_exercises_the_ir_path(tmp_path):
    root = _tree(tmp_path)
    app = ApplicationDiscovery().discover(root)
    result = ApplicationGenerator().generate(app, entrypoint="MAIN", source_root=root, ir=ir_for_application(app, root))
    assert result.success and result.entrypoint and len(result.generated_files) >= 2


def test_programs_are_still_mapped_from_the_parser_ir(tmp_path, monkeypatch):
    root = _tree(tmp_path)
    app = ApplicationDiscovery().discover(root)
    seen = {}
    real = generator_module.map_cobol_programs_to_application

    def spy(programs, **kwargs):
        seen["programs"] = programs
        return real(programs=programs, **kwargs)

    monkeypatch.setattr(generator_module, "map_cobol_programs_to_application", spy)
    ApplicationGenerator().generate(app, entrypoint="MAIN", source_root=root, ir=ir_for_application(app, root))
    mapped = {p.program_id: p for p in seen["programs"]}
    assert mapped == {u.program_id: u.program for u in app.programs}      # the parser IR's programs, value for value


def test_a_disagreeing_ir_refuses_generation_and_does_not_silently_proceed(tmp_path):
    root = _tree(tmp_path)
    app = ApplicationDiscovery().discover(root)
    ir = ir_for_application(app, root)
    forged = dataclasses.replace(ir, edges=tuple(
        dataclasses.replace(e, resolution=dataclasses.replace(e.resolution, state="unresolved", candidates=(),
                                                                reason="missing-program", confidence="unresolved"), target="")
        if e.kind == "call" else e for e in ir.edges))
    assert ApplicationGenerator().generate(app, entrypoint="MAIN", source_root=root).success
    refused = ApplicationGenerator().generate(app, entrypoint="MAIN", source_root=root, ir=forged)
    assert not refused.success and not refused.generated_files
    assert "Application IR disagrees with discovery on CALL edges" in refused.errors[0]


def test_the_pipeline_hands_the_generator_the_ir(tmp_path, monkeypatch):
    from engine.modernization.pipeline import ModernizationConfig, UniversalModernizationPipeline

    (tmp_path / "src").mkdir()
    root = _tree(tmp_path / "src")
    seen = []
    real = ApplicationGenerator.generate

    def spy(self, application, entrypoint="", source_root=None, orders=(), ir=None, plan=None):
        seen.append(ir)
        return real(self, application, entrypoint, source_root, orders, ir=ir, plan=plan)

    monkeypatch.setattr(ApplicationGenerator, "generate", spy)
    UniversalModernizationPipeline(ModernizationConfig(
        source_dir=str(root), output_dir=str(tmp_path / "out"), application_id="m4", entrypoint="MAIN",
        docker_available=True)).execute()
    assert seen and seen[0] is not None and {p.name for p in seen[0].programs} == {"MAIN", "SUB1"}
