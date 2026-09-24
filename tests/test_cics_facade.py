"""Facade tests for the isolated CICS modernization lane."""

from engine.cics.model import CicsGeneratedFile, CicsSpringApplication
from engine.transformation.cics_java_mapping import (
    extract_cics_blocks,
    generate_cics_spring,
    map_and_generate_cics,
    map_cics_programs,
    to_shared_generated_files,
    transform_cics_program,
)
from engine.transformation.contracts import GeneratedFile as SharedGeneratedFile

TWO_BLOCK_COBOL = """IDENTIFICATION DIVISION.
PROGRAM-ID. DEMOPRG.
PROCEDURE DIVISION.
MAIN.
    EXEC CICS
        SEND MAP(FIRST)
    END-EXEC.
    EXEC CICS
        LINK PROGRAM(SECOND)
        RETURN
    END-EXEC.
    GOBACK.
"""


def test_extract_identifies_program_id_and_preserves_block_order():
    blocks = extract_cics_blocks(TWO_BLOCK_COBOL)
    assert len(blocks) == 2
    assert [block.program_id for block in blocks] == ["DEMOPRG", "DEMOPRG"]
    assert [block.commands[0].command_type.value for block in blocks] == [
        "SEND",
        "LINK",
    ]


def test_extract_does_not_modify_cobol_source():
    source = TWO_BLOCK_COBOL
    before = source
    extract_cics_blocks(source)
    assert source == before


def test_unbalanced_block_is_skipped():
    assert extract_cics_blocks("PROGRAM-ID. DEMOPRG.\nEXEC CICS\nSEND MAP(A)") == []
    assert extract_cics_blocks("") == []


def test_multiple_blocks_consolidate_into_one_service_in_order():
    application = map_cics_programs(TWO_BLOCK_COBOL, application_id="demo-facade")
    assert isinstance(application, CicsSpringApplication)
    assert [service.source_program for service in application.services] == [
        "DEMOPRG"
    ]
    assert [step.step_kind for step in application.services[0].flow] == [
        "SEND",
        "LINK",
        "RETURN",
    ]


def test_unsupported_commands_are_preserved_as_diagnostics():
    application = map_cics_programs(
        "PROGRAM-ID. DEMOPRG.\nEXEC CICS\nALLOCATE\nSYNCPOINT\nEND-EXEC."
    )
    unsupported = application.all_unsupported()
    assert [item.command for item in unsupported] == ["ALLOCATE"]
    assert "outside the supported" in unsupported[0].reason


def test_map_and_generate_returns_native_generated_files():
    files = map_and_generate_cics(TWO_BLOCK_COBOL, application_id="demo-facade")
    assert files
    assert all(isinstance(item, CicsGeneratedFile) for item in files)
    assert {item.class_name for item in files} == {
        "CicsApplication",
        "CicsRuntime",
        "ProgramClient",
        "DemoprgService",
        "DemoprgCommArea",
        "CICS-MAPPING",
    }


def test_shared_generated_file_compatibility():
    native = map_and_generate_cics(TWO_BLOCK_COBOL, application_id="demo-facade")
    shared = to_shared_generated_files(native)
    assert len(shared) == len(native)
    assert all(isinstance(item, SharedGeneratedFile) for item in shared)
    for native_file, shared_file in zip(native, shared):
        assert shared_file.filename == native_file.filename
        assert shared_file.source_code == native_file.source_code
    assert {item.language for item in shared} == {"java", "markdown"}


def test_end_to_end_transform_returns_model_and_files():
    application, files = transform_cics_program(
        TWO_BLOCK_COBOL, application_id="demo-facade"
    )
    assert application.validate() == []
    assert files == generate_cics_spring(application)
