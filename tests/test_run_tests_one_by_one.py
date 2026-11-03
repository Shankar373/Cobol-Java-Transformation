"""Regression tests for scripts/run_tests_one_by_one.py (audit D-3).

The driver used to exit 0 while silently reporting that nothing ran:
  - a file that collected zero tests (NO_TESTS) was excluded from `bad`;
  - KeyboardInterrupt fell through to an exit code computed from partial
    results, so an interrupted run could return 0;
  - `--start-at` with a typo silently restarted from the beginning;
  - an all-skipped file read as PASS.

These tests drive the real driver (subprocess pytest per synthetic file)
against a temporary fake repo so the exit-code contract is pinned.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "run_tests_one_by_one.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "run_tests_one_by_one_under_test", SCRIPT
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


PASSING_SOURCE = "def test_ok():\n    assert 1 == 1\n"
EMPTY_SOURCE = "CONSTANT = 1\n"  # importable, but collects zero tests
ALL_SKIP_SOURCE = (
    "import pytest\n\n\n"
    "def test_gated():\n"
    '    pytest.skip("environment gate")\n'
)
FAILING_SOURCE = "def test_bad():\n    assert 1 == 2\n"


@pytest.fixture()
def fake_repo(tmp_path, monkeypatch):
    """A temp repo root with tests/ plus the driver module bound to it."""
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "__init__.py").write_text("", encoding="utf-8")
    mod = _load_module()
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    return mod, tmp_path


def _write(tests_dir: Path, name: str, source: str) -> None:
    (tests_dir / name).write_text(source, encoding="utf-8")


class TestRunOneStatus:
    @staticmethod
    def _run(mod, root, rel):
        out = root / "out"
        out.mkdir(exist_ok=True)
        import os

        env = {k: os.environ[k] for k in ("PATH", "SYSTEMROOT", "TEMP", "TMP")
               if k in os.environ}
        return mod.run_one(rel, out, env, 120)

    def test_collecting_file_reports_pass(self, fake_repo):
        mod, root = fake_repo
        _write(root / "tests", "test_passing.py", PASSING_SOURCE)
        row = self._run(mod, root, "tests/test_passing.py")
        assert row["status"] == "PASS"
        assert row["tests"] == 1
        assert row["failures"] == 0

    def test_zero_test_file_reports_no_tests_not_pass(self, fake_repo):
        mod, root = fake_repo
        _write(root / "tests", "test_empty.py", EMPTY_SOURCE)
        row = self._run(mod, root, "tests/test_empty.py")
        assert row["status"] == "NO_TESTS", row

    def test_all_skipped_file_reports_all_skip_not_pass(self, fake_repo):
        mod, root = fake_repo
        _write(root / "tests", "test_allskip.py", ALL_SKIP_SOURCE)
        row = self._run(mod, root, "tests/test_allskip.py")
        assert row["status"] == "ALL_SKIP", row

    def test_failing_file_reports_fail(self, fake_repo):
        mod, root = fake_repo
        _write(root / "tests", "test_failing.py", FAILING_SOURCE)
        row = self._run(mod, root, "tests/test_failing.py")
        assert row["status"] == "FAIL", row
        assert row["failures"] == 1

    def test_missing_file_is_error_not_no_tests(self, fake_repo):
        """pytest exit 4 (usage error) with zero tests must stay ERROR."""
        mod, root = fake_repo
        row = self._run(mod, root, "tests/test_does_not_exist.py")
        assert row["status"] == "ERROR", row


class TestMainExitCodes:
    def _run_main(self, mod, root, *argv):
        old = sys.argv
        sys.argv = ["run_tests_one_by_one.py", *argv]
        try:
            return mod.main()
        finally:
            sys.argv = old

    def test_all_passing_run_exits_zero(self, fake_repo):
        mod, root = fake_repo
        _write(root / "tests", "test_passing.py", PASSING_SOURCE)
        code = self._run_main(
            mod, root, "--no-docker", "--out-dir", str(root / "out")
        )
        assert code == 0

    def test_run_with_no_tests_file_exits_nonzero(self, fake_repo):
        """A zero-collection file must fail the run, not ride through."""
        mod, root = fake_repo
        _write(root / "tests", "test_empty.py", EMPTY_SOURCE)
        code = self._run_main(
            mod, root, "--no-docker", "--out-dir", str(root / "out")
        )
        assert code == 1

    def test_run_with_all_skipped_file_exits_nonzero(self, fake_repo):
        mod, root = fake_repo
        _write(root / "tests", "test_allskip.py", ALL_SKIP_SOURCE)
        code = self._run_main(
            mod, root, "--no-docker", "--out-dir", str(root / "out")
        )
        assert code == 1

    def test_run_with_failing_file_exits_nonzero(self, fake_repo):
        mod, root = fake_repo
        _write(root / "tests", "test_failing.py", FAILING_SOURCE)
        code = self._run_main(
            mod, root, "--no-docker", "--out-dir", str(root / "out")
        )
        assert code == 1

    def test_empty_collection_exits_two_before_running(self, fake_repo):
        """A --filter matching nothing must not report a clean run."""
        mod, root = fake_repo
        _write(root / "tests", "test_passing.py", PASSING_SOURCE)
        code = self._run_main(
            mod, root, "--no-docker", "--filter", "no_such_file",
            "--out-dir", str(root / "out"),
        )
        assert code == 2

    def test_start_at_typo_exits_two_instead_of_restarting(self, fake_repo):
        mod, root = fake_repo
        _write(root / "tests", "test_passing.py", PASSING_SOURCE)
        code = self._run_main(
            mod, root, "--no-docker", "--start-at", "no_such_file",
            "--out-dir", str(root / "out"),
        )
        assert code == 2

    def test_interrupted_run_exits_130_not_zero(self, fake_repo, monkeypatch):
        mod, root = fake_repo
        _write(root / "tests", "test_passing.py", PASSING_SOURCE)

        def _interrupt(rel, out_dir, env, timeout):
            raise KeyboardInterrupt

        monkeypatch.setattr(mod, "run_one", _interrupt)
        code = self._run_main(
            mod, root, "--no-docker", "--out-dir", str(root / "out")
        )
        assert code == 130

    def test_no_tests_status_is_listed_in_diagnostics(self, fake_repo):
        mod, root = fake_repo
        _write(root / "tests", "test_empty.py", EMPTY_SOURCE)
        self._run_main(mod, root, "--no-docker", "--out-dir", str(root / "out"))
        summary = (root / "out" / "summary.md").read_text(encoding="utf-8")
        assert "NO_TESTS" in summary
        assert "## Diagnostics" in summary
