"""The capability-truth gate list (audit B3).

``tests/capability_truth.txt`` is the single list the CI ``capability-truth``
job runs with pytest only. A missing or misspelt entry used to surface only
as a CI failure; this pins the manifest itself.
"""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / "tests" / "capability_truth.txt"


def _entries() -> list[str]:
    return [line.strip() for line in MANIFEST.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")]


def test_every_listed_test_exists_once():
    paths = [e for e in _entries() if not e.startswith("--")]
    assert len(paths) == len(set(paths)), "duplicate entries"
    missing = [p for p in paths if not (REPO / p).is_file()]
    assert not missing, missing


def test_deselected_nodes_belong_to_listed_files():
    entries = _entries()
    paths = {e for e in entries if not e.startswith("--")}
    for entry in entries:
        if entry.startswith("--deselect "):
            node = entry.split(" ", 1)[1]
            assert node.split("::", 1)[0] in paths, node


def test_ci_runs_the_manifest_and_the_dependency_map_check():
    ci = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "tests/capability_truth.txt" in ci
    assert "python tools/dependency_map.py --check" in ci
    assert "tests/test_capability_registry_reconciliation.py \\" not in ci  # no second inline list


def test_docker_lane_turns_infrastructure_skips_into_failures(tmp_path):
    """Audit B1: with RUN_DOCKER_TESTS=1 a skip for missing Docker/JDK fails;
    without it the same test still skips (hermetic lane unchanged)."""
    import os
    import shutil
    import subprocess
    import sys

    shutil.copy(REPO / "tests" / "conftest.py", tmp_path / "conftest.py")
    (tmp_path / "docker_lane.txt").write_text("", encoding="utf-8")
    (tmp_path / "test_probe.py").write_text(
        "import pytest\n\n"
        "def test_needs_docker():\n    pytest.skip('Docker not available')\n\n"
        "def test_unrelated_skip():\n    pytest.skip('cannot create symlinks here')\n",
        encoding="utf-8")

    def run(lane: bool):
        env = {k: v for k, v in os.environ.items() if k != "RUN_DOCKER_TESTS"}
        if lane:
            env["RUN_DOCKER_TESTS"] = "1"
        return subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(tmp_path)],
            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)

    on = run(lane=True)
    assert on.returncode == 1 and "1 failed, 1 skipped" in on.stdout, on.stdout[-800:]
    assert "requires this test to run" in on.stdout
    off = run(lane=False)
    assert off.returncode == 0 and "2 skipped" in off.stdout, off.stdout[-800:]
