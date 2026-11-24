"""Layer 13: the sealed bundle is bound to the sealed manifest's generation and build records.

The artifact seal covers the bytes on disk after validation; ``java_generation`` names the project Layer 9 generated and ``build_artifact`` the jar the
lane built.  Approval and export refuse a bundle whose source or jar is not the one the evidence recorded.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from api.artifact_seal import compute_generated_seal, seal_binding_problem
from tests.test_candidate_generation_binding import generated

JAR = b"PK jar bytes"


def _sealed(tmp_path, *, jar: bytes | None = JAR, mutate=None):
    report = generated(tmp_path)
    root = Path(report.generated_project_dir)
    if jar is not None:
        (root / "target").mkdir()
        (root / "target" / "app.jar").write_bytes(jar)
    if mutate:
        mutate(root)
    build = (("artifact_digest", hashlib.sha256(JAR).hexdigest()), ("artifact_name", "app.jar"), ("built_tree_digest", "x"))
    return compute_generated_seal(root), report.generation_record, build


def test_nothing_recorded_binds_nothing(tmp_path):
    seal, _generation, _build = _sealed(tmp_path)
    assert seal_binding_problem(seal) == ""


def test_the_generated_bundle_with_its_built_jar_is_bound(tmp_path):
    seal, generation, build = _sealed(tmp_path)
    assert seal_binding_problem(seal, generation, build) == ""


def test_a_bundle_without_a_build_after_generation_is_bound_to_the_generation(tmp_path):
    seal, generation, _build = _sealed(tmp_path, jar=None)
    assert seal_binding_problem(seal, generation) == ""


@pytest.mark.parametrize("fault", ["edit", "add", "remove"])
def test_a_source_changed_before_the_seal_is_refused(tmp_path, fault):
    def mutate(root: Path):
        java = next(root.rglob("*.java"))
        if fault == "edit":
            java.write_text(java.read_text(encoding="utf-8") + "// swapped\n", encoding="utf-8")
        elif fault == "add":
            (root / "Extra.java").write_text("class Extra {}", encoding="utf-8")
        else:
            java.unlink()

    seal, generation, build = _sealed(tmp_path, mutate=mutate)
    assert "does not match its recorded generation" in seal_binding_problem(seal, generation, build)


def test_a_jar_other_than_the_one_built_is_refused(tmp_path):
    seal, generation, build = _sealed(tmp_path, jar=b"PK substituted")
    assert "built artifact" in seal_binding_problem(seal, generation, build)


def test_a_missing_jar_is_refused(tmp_path):
    seal, generation, build = _sealed(tmp_path, jar=None)
    assert "built artifact" in seal_binding_problem(seal, generation, build)


def test_a_nested_target_directory_is_source_not_build_output(tmp_path):
    def mutate(root: Path):
        (root / "src" / "target").mkdir()
        (root / "src" / "target" / "Sneaky.java").write_text("class Sneaky {}", encoding="utf-8")

    seal, generation, build = _sealed(tmp_path, mutate=mutate)
    assert seal_binding_problem(seal, generation, build) != ""


def test_a_malformed_seal_is_refused_when_a_record_exists(tmp_path):
    from api.errors import ConflictError

    _seal, generation, build = _sealed(tmp_path)
    with pytest.raises(ConflictError):
        seal_binding_problem("{not json", generation, build)


def _gate(seal, generation, build):
    from types import SimpleNamespace

    from api.service import Service
    from engine.domain.identities import VerdictState

    service = Service.__new__(Service)
    service._check_evidence_verdict_consistency = lambda run: None
    service._require_valid_evidence = lambda run: None
    manifest = SimpleNamespace(java_generation=generation, build_artifact=build)
    run = SimpleNamespace(id="r1", verdict=SimpleNamespace(state=VerdictState.VERIFIED), generated_seal=seal, evidence_manifest=manifest)
    service.require_verified_evidence(run, action="approved")


def test_the_approval_and_export_gate_refuses_a_substituted_jar(tmp_path):
    from api.errors import ConflictError

    seal, generation, build = _sealed(tmp_path, jar=b"PK substituted")
    with pytest.raises(ConflictError, match="built artifact"):
        _gate(seal, generation, build)


def test_the_approval_and_export_gate_admits_the_generated_and_built_bundle(tmp_path):
    seal, generation, build = _sealed(tmp_path)
    _gate(seal, generation, build)
