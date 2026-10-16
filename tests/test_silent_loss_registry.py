"""Wiring: the semantic proof matrix documents the same registry the analyzer uses.

If a construct is added to CONSTRUCT_REGISTRY or _SOURCE_PATTERNS without a
matching row in docs/SEMANTIC_PROOF_MATRIX.md, this test fails, so the matrix
cannot silently drift from the honest classification table.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from engine.transformation.semantic_capability import (
    CONSTRUCT_REGISTRY,
    CONSTRUCT_IR_COVERAGE,
    IR_TYPE_TO_CONSTRUCT,
    _SOURCE_PATTERNS,
    CapabilityLevel,
)

MATRIX = Path(__file__).resolve().parent.parent / "docs" / "SEMANTIC_PROOF_MATRIX.md"


def _matrix_text() -> str:
    return MATRIX.read_text(encoding="utf-8")


class TestMatrixMatchesRegistry:
    def test_every_registry_key_is_documented(self) -> None:
        text = _matrix_text()
        missing = [k for k in CONSTRUCT_REGISTRY if k not in text]
        assert not missing, f"Matrix missing registry keys: {missing}"

    def test_every_source_pattern_is_documented(self) -> None:
        text = _matrix_text()
        missing = [key for key, _ in _SOURCE_PATTERNS if key not in text]
        assert not missing, f"Matrix missing source patterns: {missing}"

    def test_every_ir_type_maps_to_a_registry_key(self) -> None:
        for ir_type, key in IR_TYPE_TO_CONSTRUCT.items():
            assert key in CONSTRUCT_REGISTRY, (
                f"{ir_type} maps to unknown registry key {key}"
            )

    def test_coverage_targets_are_known_ir_shapes(self) -> None:
        for key, targets in CONSTRUCT_IR_COVERAGE.items():
            assert key in CONSTRUCT_REGISTRY
            for target in targets:
                assert target == "InvalidKeyScope" or target in {
                    "IF/ELSE",
                    "PERFORM",
                }, f"Unexpected coverage target {target} for {key}"


class TestNoSilentSupportiveClaims:
    """Constructs without an IR mapper path must never be SUPPORTED."""

    @pytest.mark.parametrize(
        "key",
        ["GO TO", "GOBACK", "SORT", "MERGE", "ACCEPT", "INSPECT", "SET",
         "ALTER", "EXEC SQL", "EXEC CICS"],
    )
    def test_non_mappable_constructs_are_unsupported(self, key: str) -> None:
        assert CONSTRUCT_REGISTRY[key].level is CapabilityLevel.UNSUPPORTED

    def test_source_only_constructs_fail_closed(self) -> None:
        """A construct present in source with no IR must report a non-supported
        verdict.  _supported with default source_only=UNKNOWN fails closed
        (UNKNOWN), and helpers that document an unreachable generator branch
        must lower that to UNSUPPORTED."""
        for key, entry in CONSTRUCT_REGISTRY.items():
            assert entry.effective_source_level is not CapabilityLevel.SUPPORTED, (
                f"{key} would be reported SUPPORTED even when its IR is "
                "missing"
            )
