"""Oracle compile record in the sealed evidence manifest (Layer 4, acceptance criterion 10).

The evidence records what the oracle actually did — the standard it compiled at (the
oracle never passes ``-std=``, so GnuCOBOL's default, observed not assumed) and the exact
source-format flag it was given — plus the discovery ``DialectProfile.profile_id`` the
source was read under, all beside ``oracle_id``.  Recording is additive and advisory:
manifests without the record keep the exact seal they always had, and no field here ever
changes the cobc invocation.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from api import serialization
from api.workload_contract import default_contract
from engine.evidence.models import canonical_evidence_graph
from engine.pipeline import PipelineConfig, PipelineResult, VerticalSlicePipeline
from tests.comparison_doubles import Candidate as _Candidate, Oracle as _Oracle

_STD = "default"
_FLAG = "-free"
_PROFILE = "f" * 64
#: The five keys every manifest has always carried beside ``oracle_id``.
_BASE_KEYS = {"oracle_id", "image_digest", "compiler_version", "preprocessor_version", "base_image"}

_PLAIN = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. MAIN.\n"
    "       PROCEDURE DIVISION.\n"
    "           DISPLAY 'HI'.\n"
    "           STOP RUN.\n"
)


def _with_record() -> tuple:
    """``(base, recorded)`` — a plain manifest and one carrying the compile record."""
    from tests.test_persistence_integrity import _manifest

    base = _manifest()
    recorded = dataclasses.replace(
        base,
        oracle_identity=dataclasses.replace(
            base.oracle_identity, std=_STD, format_flag=_FLAG, profile_id=_PROFILE
        ),
    )
    return base, recorded


# --- manifest level -----------------------------------------------------------------------------------------------


def test_compile_record_is_recorded_beside_oracle_id_and_covered_by_the_seal() -> None:
    base, recorded = _with_record()
    graph = canonical_evidence_graph(recorded)["oracle_identity"]
    assert graph["oracle_id"] == "gnucobol-3.1.2"
    assert (graph["std"], graph["format_flag"], graph["profile_id"]) == (_STD, _FLAG, _PROFILE)
    # the record is sealed: a different record is a different manifest
    assert recorded.manifest_hash != base.manifest_hash


def test_the_record_round_trips_through_persistence_with_its_seal() -> None:
    _, recorded = _with_record()
    decoded = serialization.decode_evidence_manifest(
        serialization.encode_evidence_manifest(recorded)
    )
    assert decoded is not None
    assert (
        decoded.oracle_identity.std,
        decoded.oracle_identity.format_flag,
        decoded.oracle_identity.profile_id,
    ) == (_STD, _FLAG, _PROFILE)
    assert decoded.manifest_hash == recorded.manifest_hash


def test_a_manifest_without_the_record_keeps_the_exact_seal_it_always_had() -> None:
    from tests.test_persistence_integrity import _manifest

    base = _manifest()
    graph = canonical_evidence_graph(base)["oracle_identity"]
    assert set(graph) == _BASE_KEYS  # no new key appears when nothing was observed
    decoded = serialization.decode_evidence_manifest(serialization.encode_evidence_manifest(base))
    assert decoded is not None
    assert decoded.manifest_hash == base.manifest_hash
    assert (
        decoded.oracle_identity.std,
        decoded.oracle_identity.format_flag,
        decoded.oracle_identity.profile_id,
    ) == (None, None, None)
    assert set(decoded.to_dict()["oracle_identity"]) == {
        "oracle_id", "image_digest", "compiler_version",
    }


def test_to_dict_records_the_compile_record_beside_oracle_id() -> None:
    _, recorded = _with_record()
    row = recorded.to_dict()["oracle_identity"]
    assert row["oracle_id"] == "gnucobol-3.1.2"
    assert (row["std"], row["format_flag"], row["profile_id"]) == (_STD, _FLAG, _PROFILE)


# --- pipeline level -----------------------------------------------------------------------------------------------


class _ObservedOracle(_Oracle):
    """Oracle double reporting the compile record a real run observed."""

    def execute(self, run_id, source_path, input_data=None, input_files=None):
        result = super().execute(run_id, source_path, input_data, input_files)
        return dataclasses.replace(result, std=_STD, format_flag=_FLAG)


def _run(tmp_path: Path, *, oracle_profile_id: str = "") -> PipelineResult:
    src = tmp_path / "MAIN.cob"
    src.write_text(_PLAIN, encoding="latin-1")
    cand = tmp_path / "cand"
    cand.mkdir()
    (cand / "Main.java").write_text("class Main {}", encoding="utf-8")
    config = PipelineConfig(
        workload_id="wl-oracle-profile",
        cobol_source_path=str(src),
        java_candidate_path=str(cand),
        java_entrypoint="Main",
        workload=default_contract("wl-oracle-profile").workload,
        use_docker_java=True,
        oracle_profile_id=oracle_profile_id,
    )
    pipe = VerticalSlicePipeline(config, candidate_adapter=_Candidate(b"HI\n", None, 0))
    pipe._oracle_adapter = _ObservedOracle(b"HI\n", None, 0)
    return pipe.run()


def test_pipeline_records_observed_std_and_format_flag_plus_profile_id(tmp_path: Path) -> None:
    result = _run(tmp_path, oracle_profile_id=_PROFILE)
    identity = result.oracle_identity
    assert (identity.std, identity.format_flag, identity.profile_id) == (_STD, _FLAG, _PROFILE)
    assert result.evidence_manifest.oracle_identity == identity
    graph = canonical_evidence_graph(result.evidence_manifest)["oracle_identity"]
    assert (graph["std"], graph["format_flag"], graph["profile_id"]) == (_STD, _FLAG, _PROFILE)
    decoded = serialization.decode_evidence_manifest(
        serialization.encode_evidence_manifest(result.evidence_manifest)
    )
    assert decoded is not None and decoded.manifest_hash == result.evidence_manifest.manifest_hash
    assert decoded.oracle_identity.profile_id == _PROFILE


def test_pipeline_records_only_what_it_observed(tmp_path: Path) -> None:
    """No profile supplied → no profile_id key; observed std/flag still recorded."""
    result = _run(tmp_path)
    identity = result.oracle_identity
    assert (identity.std, identity.format_flag, identity.profile_id) == (_STD, _FLAG, None)
    graph = canonical_evidence_graph(result.evidence_manifest)["oracle_identity"]
    assert "std" in graph and "format_flag" in graph
    assert "profile_id" not in graph
