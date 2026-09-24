"""Subset-contract tests for the isolated CICS modernization lane."""

from typing import cast

from engine.cics.model import CicsConstructStatus
from engine.cics.subset import (
    SUPPORTED_SUBSET_VERSION,
    classify_command,
    is_supported,
    known_command_names,
    supported_command_names,
    unsupported_command_names,
)
from engine.transformation.ir import CicsCommandType

EXPECTED_MAPPED = {
    "SEND",
    "RECEIVE",
    "LINK",
    "XCTL",
    "RETURN",
    "READ",
    "WRITE",
    "REWRITE",
    "DELETE",
    "STARTBR",
    "READNEXT",
    "READPREV",
    "ENDBR",
    "WRITEQ",
    "READQ",
    "DELETEQ",
    "SYNCPOINT",
    "ABEND",
}

EXPECTED_EXPLICIT_ONLY = {
    "HANDLE_CONDITION",
    "HANDLE_AID",
    "ASSIGN",
}

EXPECTED_UNSUPPORTED = {
    "ALLOCATE",
    "FREE",
    "HOLD",
    "RELEASE",
    "SET",
    "IGNORE",
    "POP",
    "PUSH",
}


def test_subset_version_is_deterministic():
    assert SUPPORTED_SUBSET_VERSION == "1.0.0"
    assert SUPPORTED_SUBSET_VERSION == "1.0.0"


def test_supported_commands_are_mapped():
    for command in CicsCommandType:
        if command.value in EXPECTED_MAPPED:
            result = classify_command(command)
            assert result.status == CicsConstructStatus.MAPPED
            assert result.is_mapped
            assert is_supported(command)


def test_supported_command_categories():
    assert classify_command(CicsCommandType.SEND).category == "TERMINAL_IO"
    assert classify_command(CicsCommandType.RECEIVE).category == "TERMINAL_IO"
    assert (
        classify_command(CicsCommandType.LINK).category == "PROGRAM_INTERACTION"
    )
    assert (
        classify_command(CicsCommandType.XCTL).category == "PROGRAM_INTERACTION"
    )
    assert (
        classify_command(CicsCommandType.RETURN).category == "PROGRAM_INTERACTION"
    )
    assert classify_command(CicsCommandType.READ).category == "RESOURCE_ACCESS"
    assert classify_command(CicsCommandType.WRITEQ).category == "RESOURCE_ACCESS"
    assert classify_command(CicsCommandType.SYNCPOINT).category == "BOUNDARY"
    assert classify_command(CicsCommandType.ABEND).category == "BOUNDARY"


def test_explicit_only_commands_are_not_translated():
    for command in CicsCommandType:
        if command.value in EXPECTED_EXPLICIT_ONLY:
            result = classify_command(command)
            assert result.status == CicsConstructStatus.EXPLICIT_ONLY
            assert result.category == "EXPLICIT_ONLY"
            assert not result.is_mapped
            assert not is_supported(command)


def test_known_unsupported_commands_stay_explicit():
    for command in CicsCommandType:
        if command.value in EXPECTED_UNSUPPORTED:
            result = classify_command(command)
            assert result.status == CicsConstructStatus.UNSUPPORTED
            assert result.category == "UNSUPPORTED"
            assert not result.is_mapped
            assert not is_supported(command)


def test_unknown_command_defaults_to_unsupported():
    unknown = cast(CicsCommandType, "NOT_A_REAL_CICS_COMMAND")
    result = classify_command(unknown)
    assert result.status == CicsConstructStatus.UNSUPPORTED
    assert result.category == "UNSUPPORTED"
    assert not result.is_mapped


def test_classification_is_deterministic():
    first = classify_command(CicsCommandType.RETURN)
    second = classify_command(CicsCommandType.RETURN)
    assert first is second
    assert first.status == second.status
    assert first.category == second.category


def test_command_name_lists_are_consistent():
    known = set(known_command_names())
    assert known == {command.value for command in CicsCommandType}
    assert EXPECTED_MAPPED <= set(supported_command_names())
    assert EXPECTED_UNSUPPORTED <= set(unsupported_command_names())
    assert not (set(supported_command_names()) & set(unsupported_command_names()))
