"""Audit CI-F7: THIRD_PARTY_NOTICES lists every shipped dependency.

The notices named only the direct dependencies, so most of the production
image (starlette, pydantic_core, uvloop, ...) carried no attribution. The
tables are generated from the lockfiles; this test fails when a lock
changes without regenerating them.
"""

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _generator():
    path = REPO / "scripts" / "supply-chain" / "generate_notices.py"
    spec = importlib.util.spec_from_file_location("generate_notices", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_shipped_package_is_listed_at_its_locked_version():
    problems = _generator().check()
    assert problems == [], (
        "run python scripts/supply-chain/generate_notices.py: " + "; ".join(problems)
    )


def test_tables_cover_the_runtime_closure_not_just_direct_dependencies():
    names = {name for name, _, _ in _generator().python_packages()}
    assert {"starlette", "pydantic_core", "uvloop"} <= names
    assert "pytest" not in names
