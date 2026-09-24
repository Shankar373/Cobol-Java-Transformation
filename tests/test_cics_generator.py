"""Generator tests for the isolated CICS modernization lane."""

from engine.cics.generator import NO_EQUIVALENCE_DISCLAIMER, CicsSpringGenerator
from engine.cics.model import CicsGeneratedFile
from engine.transformation.cics_java_mapping import map_cics_programs

DEMO_COBOL = """IDENTIFICATION DIVISION.
PROGRAM-ID. DEMOPRG.
PROCEDURE DIVISION.
MAIN.
    EXEC CICS
        SEND MAP(OUTMAP) MAPSET(OUTSET)
        RECEIVE MAP(INMAP) INTO(:WS-IN) LENGTH(:WS-LEN)
        LINK PROGRAM(NEXTPGM) COMMAREA(:WS-CA) LENGTH(:WS-LEN)
        SYNCPOINT
        RETURN TRANSID(NEXT)
    END-EXEC.
    GOBACK.
"""


def _files(application_id="demo-app"):
    application = map_cics_programs(DEMO_COBOL, application_id=application_id)
    return CicsSpringGenerator().generate(application)


def test_generated_file_set_is_complete():
    files = _files()
    assert all(isinstance(item, CicsGeneratedFile) for item in files)
    assert {item.path for item in files} == {
        "src/main/java/com/generated/cics/CicsApplication.java",
        "src/main/java/com/generated/cics/cics/CicsRuntime.java",
        "src/main/java/com/generated/cics/client/ProgramClient.java",
        "src/main/java/com/generated/cics/service/DemoprgService.java",
        "src/main/java/com/generated/cics/dto/DemoprgCommArea.java",
        "cics-mapping/demo-app-CICS-MAPPING.md",
    }
    assert {item.class_name for item in files} == {
        "CicsApplication",
        "CicsRuntime",
        "ProgramClient",
        "DemoprgService",
        "DemoprgCommArea",
        "CICS-MAPPING",
    }


def test_every_generated_source_contains_no_equivalence_disclaimer():
    for generated in _files():
        assert "NOT CICS TS EQUIVALENCE" in generated.source_code
        assert NO_EQUIVALENCE_DISCLAIMER.splitlines()[0] in generated.source_code


def test_service_preserves_command_order_and_seams():
    files = _files()
    service = next(item for item in files if item.class_name == "DemoprgService")
    assert "@Service" in service.source_code
    assert "@Transactional" in service.source_code
    assert "programClient.linkNextpgm();" in service.source_code
    assert "cics.syncpoint();" in service.source_code
    assert "cics.returnControl();" in service.source_code
    assert service.source_code.index("step0();") < service.source_code.index(
        "step4();"
    )


def test_unsupported_constructs_remain_explicit_in_source():
    application = map_cics_programs(
        "PROGRAM-ID. DEMOPRG.\nEXEC CICS\nALLOCATE\nSYNCPOINT\nEND-EXEC.",
        application_id="demo-unsupported",
    )
    files = CicsSpringGenerator().generate(application)
    service = next(item for item in files if item.class_name == "DemoprgService")
    report = next(item for item in files if item.class_name == "CICS-MAPPING")
    assert "CICS-UNSUPPORTED" in service.source_code
    assert "ALLOCATE" in service.source_code
    assert "`ALLOCATE`" in report.source_code


def test_generated_files_are_not_cobol_entrypoints():
    for generated in _files():
        assert not generated.filename.endswith(".cob")
        assert not generated.path.endswith(".cob")
        assert "IDENTIFICATION DIVISION" not in generated.source_code
        assert "PROCEDURE DIVISION" not in generated.source_code
        assert "PROGRAM-ID." not in generated.source_code


def test_generation_is_deterministic():
    first = [
        (generated.path, generated.source_code) for generated in _files()
    ]
    second = [
        (generated.path, generated.source_code) for generated in _files()
    ]
    assert first == second
