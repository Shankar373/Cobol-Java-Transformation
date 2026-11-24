"""Layer 12: a tampered or malformed Layer 7-10 sealed record can never reach VERIFIED.

The control is a manifest that verifies.  The same manifest carrying a record that fails shape or cross-binding validation is not admitted by the
integrity validator (a violation list, not a ``ValidatedEvidenceManifest``), and the production clamp ``derive_verdict_untrusted`` turns the natural
VERIFIED into ERROR.
"""

from __future__ import annotations

import dataclasses

import pytest

from engine.domain.identities import RunId, VerdictState
from engine.evidence.integrity import EvidenceIntegrityValidator, ValidatedEvidenceManifest
from engine.verdict.derivation import derive_verdict_untrusted, derive_verdict_validated
from tests.verdict.test_verdict_trust_boundary import _make_valid_manifest

SEALED_FIELDS = ("capability_analysis", "transformation_plan", "java_generation", "build_artifact")

# One malformed value per record: wrong key set, then a wrong-typed digest.
MALFORMED = {
    "capability_analysis": (("only", "x"),),
    "transformation_plan": (("only", "x"),),
    "java_generation": (("only", "x"),),
    "build_artifact": (("artifact_digest", "NOT-HEX"), ("artifact_name", "../evil.jar"), ("built_tree_digest", "z")),
}


def _verifying():
    return _make_valid_manifest(RunId(value="run-l12"))


def test_the_control_manifest_verifies():
    validation = EvidenceIntegrityValidator().validate(_verifying())
    assert isinstance(validation, ValidatedEvidenceManifest)
    assert derive_verdict_validated(validation).state == VerdictState.VERIFIED


@pytest.mark.parametrize("field", SEALED_FIELDS)
def test_a_malformed_sealed_record_is_refused_and_never_verifies(field):
    manifest = dataclasses.replace(_verifying(), **{field: MALFORMED[field]})
    validation = EvidenceIntegrityValidator().validate(manifest)
    assert not isinstance(validation, ValidatedEvidenceManifest), field
    verdict = derive_verdict_untrusted(manifest, validation)
    assert verdict.state == VerdictState.ERROR and verdict.state != VerdictState.VERIFIED
    assert verdict.differences, field  # the violation is surfaced, not swallowed
