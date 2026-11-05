"""Roadmap unit 19: the type-check and coverage gates -- their logic, configuration and CI wiring.

mypy itself runs in the CI ``typecheck`` job (it needs the project environment); here the ratchet logic is
tested on constructed output, and the configuration is checked so the gate cannot be silently disabled.
"""

from __future__ import annotations

import importlib.util
from collections import Counter
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("mypy_gate", REPO / "tools" / "mypy_gate.py")
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)

OUTPUT = r"""
api\app.py:471: error: Argument 1 to "len" has incompatible type "str | None"; expected "Sized"  [arg-type]
api/app.py:475: error: Argument 1 to "len" has incompatible type "str | None"; expected "Sized"  [arg-type]
engine/x.py:9:4: error: Missing return statement  [return]
engine/x.py:12: error: Name "y" already defined on line 5  [no-redef]
engine/x.py:12: note: this is a note, not an error
Found 3 errors in 2 files (checked 5 source files)
"""

#: Modules written for the enterprise roadmap are held to zero type errors: no baseline entry is allowed.
STRICT = ("engine/simulators/", "engine/estate/", "engine/sql/database_dialect", "engine/sql/migration",
          "engine/sql/oracle_pg", "engine/transformation/exec_sql", "engine/transformation/inspect_",
          "engine/transformation/sort_", "engine/transformation/search_", "api/rbac.py", "api/estate.py", "tools/mypy_gate.py")


def test_errors_are_normalised_without_line_numbers_or_platform_separators():
    keys = gate.normalize(OUTPUT)
    assert keys == Counter({
        'api/app.py|[arg-type]|Argument 1 to "len" has incompatible type "str | None"; expected "Sized"': 2,
        "engine/x.py|[return]|Missing return statement": 1,
        'engine/x.py|[no-redef]|Name "y" already defined on line N': 1,
    })


def test_a_new_error_or_a_higher_count_fails_and_a_fixed_one_is_stale():
    baseline = Counter({"a|[x]|m": 2, "b|[y]|n": 1})
    assert gate.compare(Counter({"a|[x]|m": 2, "b|[y]|n": 1}), baseline) == ([], [])
    assert gate.compare(Counter({"a|[x]|m": 3, "b|[y]|n": 1}), baseline) == (["1x a|[x]|m"], [])
    assert gate.compare(Counter({"a|[x]|m": 2, "b|[y]|n": 1, "c|[z]|o": 1}), baseline)[0] == ["1x c|[z]|o"]
    new, stale = gate.compare(Counter({"a|[x]|m": 2}), baseline)
    assert new == [] and stale == ["1x b|[y]|n"]


def test_the_baseline_round_trips():
    keys = Counter({"a|[x]|m": 2, "b|[y]|n with | pipe": 1})
    assert gate.read_baseline(gate.write_baseline(keys)) == keys


def test_the_committed_baseline_is_well_formed_and_leaves_the_roadmap_modules_clean():
    text = (REPO / "tests" / "mypy_baseline.txt").read_text(encoding="utf-8")
    keys = gate.read_baseline(text)
    assert keys and all(count > 0 for count in keys.values())
    offenders = [k for k in keys if k.startswith(STRICT)]
    assert offenders == [], f"new modules must be type-clean, not baselined: {offenders}"


def test_mypy_is_configured_for_one_platform_and_the_two_trees():
    text = (REPO / "mypy.ini").read_text(encoding="utf-8")
    assert "platform = linux" in text and "files = api, engine" in text


def test_the_type_and_coverage_locks_are_hash_pinned_and_agree_with_the_dev_lock():
    for name, package in (("requirements-typecheck.lock", "mypy=="), ("requirements-coverage.lock", "coverage==")):
        lock = (REPO / name).read_text(encoding="utf-8")
        assert package in lock and "--hash=sha256:" in lock
    dev = (REPO / "requirements-dev.lock").read_text(encoding="utf-8")
    typecheck = (REPO / "requirements-typecheck.lock").read_text(encoding="utf-8")
    pinned = [line for line in typecheck.splitlines() if line.startswith("typing_extensions==")]
    assert pinned and pinned[0].split()[0].replace("_", "-") in dev


def _jobs():
    return yaml.safe_load((REPO / ".github/workflows/ci.yml").read_text(encoding="utf-8"))["jobs"]


def test_ci_runs_the_type_gate_from_the_hash_locks():
    steps = _jobs()["typecheck"]["steps"]
    runs = [s.get("run", "") for s in steps]
    assert any("--require-hashes -r requirements-dev.lock" in r for r in runs)
    assert any("--require-hashes -r requirements-typecheck.lock" in r for r in runs)
    assert any("tools/mypy_gate.py --check" in r for r in runs)


def test_ci_runs_the_suite_under_coverage_with_a_floor():
    job = _jobs()["coverage"]
    runs = "\n".join(s.get("run", "") for s in job["steps"])
    assert "--require-hashes -r requirements-coverage.lock" in runs
    assert "coverage run" in runs and "--fail-under=" in runs
    floor = int(runs.split("--fail-under=")[1].split()[0])
    assert floor >= 88, "the coverage floor may only rise (measured 90% on the first run)"
    config = (REPO / ".coveragerc").read_text(encoding="utf-8")
    sources = config.split("source =")[1].split("branch")[0].split()
    assert sources == ["api", "engine", "tools"]  # the code is measured; the tests are not
