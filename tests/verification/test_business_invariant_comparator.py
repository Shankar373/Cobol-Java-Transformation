"""BUSINESS_INVARIANT comparator: MATCH only when both sides PASS."""

from __future__ import annotations

import json

import pytest

from engine.comparators.framework import (
    CANONICAL_COMPARATOR_IDS,
    BusinessInvariantComparator,
    ComparisonResult,
    create_default_registry,
    create_verification_registry,
    resolve_comparator_id,
)
from engine.domain.identities import ArtifactIdentity, ContentHash
from engine.verification.business_invariants import (
    BusinessInvariant,
    InvariantKind,
    InvariantObservation,
    InvariantSource,
    build_report,
)


def _artifact(role: str) -> ArtifactIdentity:
    return ArtifactIdentity(
        artifact_id=f"invariant-{role.lower()}",
        artifact_type="BUSINESS_INVARIANT",
        logical_name="business-invariants",
        producer_role=role,
        content_hash=ContentHash.from_bytes(b""),
        size_bytes=0,
    )


def _report_bytes(stdout: bytes, expected: tuple[str, ...] = ("OK",)) -> bytes:
    return build_report(
        (
            BusinessInvariant(
                invariant_id="lines",
                kind=InvariantKind.EXACT_LINES,
                expected=expected,
            ),
        ),
        InvariantObservation(exit_code=0, stdout=stdout),
    ).to_bytes()


def _compare(oracle: bytes, candidate: bytes):
    return BusinessInvariantComparator().compare(
        _artifact("ORACLE"), oracle, _artifact("CANDIDATE"), candidate,
    )


class TestRegistryWiring:
    def test_canonical_id_and_alias_are_bound(self) -> None:
        assert CANONICAL_COMPARATOR_IDS["BUSINESS_INVARIANT"] == (
            "BUSINESS_INVARIANT_COMPARATOR"
        )
        assert resolve_comparator_id("business-invariant-exact") == (
            "BUSINESS_INVARIANT_COMPARATOR"
        )

    def test_default_registry_remains_the_five_v1_types(self) -> None:
        registry = create_default_registry()
        assert len(registry.get_all()) == 5
        assert not registry.is_registered("BUSINESS_INVARIANT")

    def test_verification_registry_adds_the_gate(self) -> None:
        registry = create_verification_registry()
        assert registry.is_registered("BUSINESS_INVARIANT")
        assert isinstance(
            registry.get("BUSINESS_INVARIANT"), BusinessInvariantComparator
        )


class TestComparisonSemantics:
    def test_both_pass_is_match(self) -> None:
        result = _compare(_report_bytes(b"OK\n"), _report_bytes(b"OK\n"))
        assert result.result is ComparisonResult.MATCH
        assert result.differences == ()

    def test_pass_and_fail_is_mismatch(self) -> None:
        result = _compare(_report_bytes(b"OK\n"), _report_bytes(b"WRONG\n"))
        assert result.result is ComparisonResult.MISMATCH
        assert any("Candidate" in item.description for item in result.differences)

    def test_identical_failure_on_both_sides_is_not_equivalence(self) -> None:
        result = _compare(_report_bytes(b"WRONG\n"), _report_bytes(b"WRONG\n"))
        assert result.result is ComparisonResult.MISMATCH
        descriptions = " ".join(item.description for item in result.differences)
        assert "Oracle" in descriptions
        assert "Candidate" in descriptions

    def test_missing_candidate_is_inconclusive_by_default(self) -> None:
        result = BusinessInvariantComparator().compare(
            _artifact("ORACLE"), _report_bytes(b"OK\n"),
            _artifact("CANDIDATE"), None,
        )
        assert result.result is ComparisonResult.INCONCLUSIVE

    def test_malformed_report_is_inconclusive(self) -> None:
        result = _compare(_report_bytes(b"OK\n"), b"{not json")
        assert result.result is ComparisonResult.INCONCLUSIVE

    def test_different_declarations_are_inconclusive(self) -> None:
        result = _compare(
            _report_bytes(b"OK\n", expected=("OK",)),
            _report_bytes(b"OK\n", expected=("OK", "EXTRA")),
        )
        assert result.result is ComparisonResult.INCONCLUSIVE
        assert any(
            item.location == "business_invariant_definitions"
            for item in result.differences
        )

    def test_tampered_report_overall_is_inconclusive(self) -> None:
        payload = json.loads(_report_bytes(b"WRONG\n"))
        payload["overall"] = "PASS"
        result = _compare(
            _report_bytes(b"OK\n"), json.dumps(payload).encode(),
        )
        assert result.result is ComparisonResult.INCONCLUSIVE

    def test_normalization_is_refused_not_ignored(self) -> None:
        with pytest.raises(ValueError, match="does not accept normalization"):
            BusinessInvariantComparator().compare(
                _artifact("ORACLE"), _report_bytes(b"OK\n"),
                _artifact("CANDIDATE"), _report_bytes(b"OK\n"),
                normalization_policy=("crlf_to_lf",),
            )

    def test_ordering_is_refused_not_ignored(self) -> None:
        with pytest.raises(ValueError, match="SEQUENTIAL"):
            BusinessInvariantComparator().compare(
                _artifact("ORACLE"), _report_bytes(b"OK\n"),
                _artifact("CANDIDATE"), _report_bytes(b"OK\n"),
                ordering="SORTED",
            )
