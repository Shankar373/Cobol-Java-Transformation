"""Package tests for the isolated CICS modernization lane."""

import engine.cics as cics_package
from engine.cics import (
    SUPPORTED_SUBSET_VERSION,
    CicsGeneratedFile,
    CicsSpringApplication,
    CicsSpringGenerator,
    CicsSpringMapper,
    classify_command,
)
from engine.cics.naming import camel, pascal


def test_package_imports_successfully():
    assert cics_package.__name__ == "engine.cics"
    assert cics_package.__doc__ is not None


def test_public_exports_are_available():
    for name in cics_package.__all__:
        assert hasattr(cics_package, name), name
    assert cics_package.CicsSpringMapper is CicsSpringMapper
    assert cics_package.CicsSpringGenerator is CicsSpringGenerator
    assert cics_package.CicsSpringApplication is CicsSpringApplication
    assert cics_package.CicsGeneratedFile is CicsGeneratedFile
    assert cics_package.classify_command is classify_command
    assert cics_package.SUPPORTED_SUBSET_VERSION == SUPPORTED_SUBSET_VERSION


def test_subset_version_is_deterministic():
    assert SUPPORTED_SUBSET_VERSION == "1.0.0"
    assert cics_package.SUPPORTED_SUBSET_VERSION == SUPPORTED_SUBSET_VERSION


def test_name_derivation_is_deterministic():
    assert pascal("WS-CUST-ID") == "WsCustId"
    assert camel("WS-CUST-ID") == "wsCustId"
    assert pascal("WS-CUST-ID") == pascal("WS-CUST-ID")
    assert camel("WS-CUST-ID") == camel("WS-CUST-ID")
