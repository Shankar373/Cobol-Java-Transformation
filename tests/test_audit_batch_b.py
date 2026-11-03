"""Audit 2026-11-03 batch B follow-ups (verification tooling and fixtures)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def test_multiprog_declaration_resolves():
    # V18: it passed keyword arguments the workload classes do not accept,
    # so resolving it always failed.
    from api.workload_contract import load_declared_workload

    workload = load_declared_workload("workload-multiprog")
    assert workload is not None
    assert [a.artifact_type for a in workload.artifacts] == ["STDOUT", "STDERR", "EXIT_STATUS"]
    assert workload.inputs == ()


def _verifier():
    spec = importlib.util.spec_from_file_location(
        "verify_independent", REPO / "scripts" / "e2e" / "verify_independent.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_independent_verifier_pins_images_and_records_identity():
    # V11: it ran mutable tags, recorded no identities and picked an
    # arbitrary jar when several were built.
    text = (REPO / "scripts" / "e2e" / "verify_independent.py").read_text(encoding="utf-8")
    assert "_pin_images()" in text.split("def main()", 1)[1]
    assert '"images": dict(IMAGES)' in text and '"project_sha256"' in text
    assert "expected exactly one jar" in text
    assert "next(jars.glob" not in text


def test_project_hash_ignores_build_output(tmp_path):
    verifier = _verifier()
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "Main.java").write_text("class Main {}")
    first = verifier.project_sha256(tmp_path)
    (tmp_path / "target").mkdir()
    (tmp_path / "target" / "app.jar").write_bytes(b"jar")
    assert verifier.project_sha256(tmp_path) == first
    (tmp_path / "src" / "Main.java").write_text("class Main { }")
    assert verifier.project_sha256(tmp_path) != first


def test_engine_run_ids_are_unique_within_one_second(tmp_path, monkeypatch):
    # V14: run-<workload>-<YYYYmmddHHMMSS> collided for two runs of one
    # workload in the same second.  The clock is frozen so both runs fall
    # in the same second deterministically.
    from datetime import datetime, timezone

    import engine.pipeline as pipeline_module
    from tests.test_comparison_contract_strength import _verdict

    frozen = datetime(2026, 11, 3, 12, 0, 0, tzinfo=timezone.utc)

    class _FrozenClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen

    monkeypatch.setattr(pipeline_module, "datetime", _FrozenClock)
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    first = _verdict(tmp_path / "a")
    second = _verdict(tmp_path / "b")
    assert first.evidence_manifest.run_id.value != second.evidence_manifest.run_id.value
