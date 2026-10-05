"""Regression coverage for P0 discovery and evidence-completeness boundaries."""

from engine.modernization.pipeline import ModernizationConfig, UniversalModernizationPipeline
from engine.transformation.application_discovery import ApplicationDiscovery


def test_discovery_records_unparseable_source_and_pipeline_fails_closed(tmp_path):
    (tmp_path / "VALID.cob").write_text(
        "IDENTIFICATION DIVISION.\n"
        "PROGRAM-ID. VALID.\n"
        "PROCEDURE DIVISION.\n"
        "MAIN.\n"
        "    STOP RUN.\n",
        encoding="utf-8",
    )
    # Declared COBOL source whose bytes cannot be decoded as UTF-8: the file
    # cannot be parsed at all (text-level malformation alone is tolerated by
    # the tolerant parser, which skips unrecognized statements with a
    # diagnostic), so discovery must record it as a discovery error instead
    # of silently shrinking the application.
    (tmp_path / "BROKEN.cob").write_bytes(
        b"IDENTIFICATION DIVISION.\n"
        b"PROGRAM-ID. BROKEN.\n"
        b"PROCEDURE DIVISION.\n"
        b"MAIN.\n"
        b"    DISPLAY \xff\xfe BROKEN.\n"
    )

    application = ApplicationDiscovery().discover(tmp_path, application_id="partial")
    assert [p.program_id for p in application.programs] == ["VALID"]
    assert application.discovery_errors == (
        "BROKEN.cob: COBOL source could not be parsed",
    )

    report = UniversalModernizationPipeline(
        ModernizationConfig(
            source_dir=str(tmp_path),
            output_dir=str(tmp_path / "out"),
            application_id="partial",
            docker_available=False,
        )
    ).execute()
    assert report.transformation_plan is None
    assert report.limitations[0] == "Discovery incomplete; transformation is fail-closed."


def test_discovery_still_succeeds_for_fully_parseable_application(tmp_path):
    (tmp_path / "MAIN.cob").write_text(
        "IDENTIFICATION DIVISION.\n"
        "PROGRAM-ID. MAIN.\n"
        "PROCEDURE DIVISION.\n"
        "MAIN.\n"
        "    STOP RUN.\n",
        encoding="utf-8",
    )
    application = ApplicationDiscovery().discover(tmp_path)
    assert application.discovery_errors == ()


def test_evidence_validator_rejects_missing_candidate_artifact():
    from tests.adversarial.test_evidence_trust_boundary import _manifest, _art_ev, _comp
    from engine.evidence.integrity import (
        EvidenceIntegrityValidator,
        ViolationType,
    )
    from engine.domain.identities import RunId

    run_id = RunId(value="run-missing-candidate-artifact")
    manifest = _manifest(
        run_id=run_id,
        artifacts=(
            _art_ev("art-o", "STDOUT", "ORACLE", "data", "oracle-exec-1"),
        ),
        comparisons=(
            _comp(run_id, result="MATCH", oracle_id="art-o", candidate_id="art-c"),
        ),
    )
    result = EvidenceIntegrityValidator().validate(manifest)
    assert isinstance(result, list)
    assert any(v.violation_type == ViolationType.MISSING_REQUIRED_EVIDENCE for v in result)


def test_evidence_validator_rejects_uncompared_artifact():
    from tests.adversarial.test_evidence_trust_boundary import _manifest, _art_ev, _comp
    from engine.evidence.integrity import (
        EvidenceIntegrityValidator,
        ViolationType,
    )
    from engine.domain.identities import RunId

    run_id = RunId(value="run-uncompared-artifact")
    manifest = _manifest(
        run_id=run_id,
        artifacts=(
            _art_ev("art-o", "STDOUT", "ORACLE", "data", "oracle-exec-1"),
            _art_ev("art-c", "STDOUT", "CANDIDATE", "data", "candidate-exec-1"),
            _art_ev("art-extra", "EXIT_STATUS", "CANDIDATE", "0", "candidate-exec-1"),
        ),
        comparisons=(
            _comp(run_id, result="MATCH", oracle_id="art-o", candidate_id="art-c"),
        ),
    )
    result = EvidenceIntegrityValidator().validate(manifest)
    assert isinstance(result, list)
    assert any(
        v.violation_type == ViolationType.MISSING_REQUIRED_EVIDENCE
        and "art-extra" in v.description
        for v in result
    )
