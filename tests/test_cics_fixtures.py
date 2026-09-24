"""Workload-fixture tests for the isolated CICS modernization lane."""

import importlib.util
from pathlib import Path

from engine.transformation.cics_java_mapping import map_and_generate_cics
from engine.workload import WorkloadDefinition

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "workload-cics"


def _program(name: str) -> str:
    return (FIXTURE / "cobol" / f"{name}.cob").read_text(encoding="utf-8")


def test_fixture_files_exist_with_program_ids():
    assert (FIXTURE / "workload.py").is_file()
    assert (FIXTURE / "cobol" / "CUSTINQ.cob").is_file()
    assert (FIXTURE / "cobol" / "ORDPROC.cob").is_file()
    assert "PROGRAM-ID. CUSTINQ." in _program("CUSTINQ")
    assert "PROGRAM-ID. ORDPROC." in _program("ORDPROC")


def test_workload_declaration_uses_standard_artifacts():
    spec = importlib.util.spec_from_file_location(
        "wl_cics_fixture", FIXTURE / "workload.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    workload = module.cics_workload()
    assert isinstance(workload, WorkloadDefinition)
    assert workload.workload_id == "cics"
    assert {artifact.artifact_type for artifact in workload.artifacts} == {
        "STDOUT",
        "STDERR",
        "EXIT_STATUS",
    }


def test_custinq_covers_inquiry_request_response_and_link_return():
    from engine.transformation.cics_java_mapping import map_cics_programs

    service = map_cics_programs(_program("CUSTINQ")).services[0]
    assert service.source_program == "CUSTINQ"
    assert service.is_transactional
    assert [step.step_kind for step in service.flow][1:7] == [
        "SEND",
        "RECEIVE",
        "READ",
        "LINK",
        "SYNCPOINT",
        "RETURN",
    ]
    assert ("LINK", "CUSTDISP") in service.get_interaction_targets()
    assert "PSEUDO_CONVERSATIONAL" in {
        boundary.kind for boundary in service.transaction_boundaries
    }


def test_ordproc_covers_resource_updates_and_explicit_allocate():
    from engine.transformation.cics_java_mapping import map_cics_programs

    service = map_cics_programs(_program("ORDPROC")).services[0]
    assert service.source_program == "ORDPROC"
    assert service.is_transactional
    assert {"read", "write", "writeq"} <= service.get_resource_operations()
    assert {item.command for item in service.unsupported_constructs} == {"ALLOCATE"}
    assert "COMMIT" in {
        boundary.kind for boundary in service.transaction_boundaries
    }


def test_fixture_smoke_produces_expected_files_deterministically():
    first = map_and_generate_cics(_program("CUSTINQ"), application_id="cics-custinq")
    second = map_and_generate_cics(_program("CUSTINQ"), application_id="cics-custinq")
    assert [(item.path, item.source_code) for item in first] == [
        (item.path, item.source_code) for item in second
    ]
    assert {item.class_name for item in first} == {
        "CicsApplication",
        "CicsRuntime",
        "ProgramClient",
        "CustinqService",
        "CustinqCommArea",
        "CICS-MAPPING",
    }
    for generated in first:
        assert "NOT CICS TS EQUIVALENCE" in generated.source_code
