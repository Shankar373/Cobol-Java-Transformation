"""Audit CI-F15: the lint baseline is configured and enforced in CI."""

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]


def test_ruff_baseline_is_configured():
    text = (REPO / "ruff.toml").read_text(encoding="utf-8")
    assert 'select = ["F", "E9"]' in text
    assert "frontend" in text  # not a Python tree


def test_ci_runs_ruff_from_the_hash_lock():
    workflow = yaml.safe_load((REPO / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["lint"]["steps"]
    runs = [s.get("run", "") for s in steps]
    assert any("--require-hashes -r requirements-lint.lock" in r for r in runs)
    assert "ruff check ." in runs


def test_lint_lock_pins_ruff_with_hashes():
    lock = (REPO / "requirements-lint.lock").read_text(encoding="utf-8")
    assert "ruff==" in lock and "--hash=sha256:" in lock
