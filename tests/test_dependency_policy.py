"""Roadmap unit 3: the dependency policy is enforced, not just written down."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
CONFIG = yaml.safe_load((REPO / ".github/dependabot.yml").read_text(encoding="utf-8"))
UPDATES = {u["package-ecosystem"]: u for u in CONFIG["updates"]}


def test_python_is_not_managed_by_dependabot():
    """The hash-pinned locks are the source of truth; floors in requirements*.txt must not drift."""
    assert "pip" not in UPDATES


def test_certified_runtime_pins_are_not_moved_by_dependabot():
    ignored = {i["dependency-name"] for i in UPDATES["docker"]["ignore"]}
    assert {"ubuntu", "python", "maven", "eclipse-temurin"} <= ignored


def test_frontend_majors_that_need_a_migration_are_ignored():
    ignored = {i["dependency-name"] for i in UPDATES["npm"]["ignore"]}
    assert {"react", "react-dom", "typescript", "vite", "@vitejs/plugin-react", "jsdom", "vitest"} <= ignored
    assert all(i["update-types"] == ["version-update:semver-major"] for i in UPDATES["npm"]["ignore"])


def test_updates_are_grouped_and_bounded():
    assert UPDATES["github-actions"]["groups"]["github-actions"]["patterns"] == ["*"]
    assert UPDATES["npm"]["groups"]["frontend-minor-patch"]["update-types"] == ["minor", "patch"]
    for update in UPDATES.values():
        assert update["open-pull-requests-limit"] <= 3


def _uses():
    for path in sorted((REPO / ".github/workflows").glob("*.yml")):
        for line in path.read_text(encoding="utf-8").splitlines():
            match = re.search(r"uses:\s*(\S+)@([0-9a-f]{40})\s*#\s*(\S+)", line)
            if match:
                yield path.name, match.group(1), match.group(2), match.group(3)


def test_every_action_is_pinned_to_one_commit_per_version():
    seen: dict[str, set[tuple[str, str]]] = {}
    for _, action, sha, version in _uses():
        seen.setdefault(action, set()).add((sha, version))
    assert seen, "no pinned actions found"
    # One commit and one version label per action across all workflows.
    assert all(len(v) == 1 for v in seen.values()), seen


def test_actions_are_on_the_reviewed_v7_line():
    by_action = {a: v for _, a, _, v in _uses()}
    assert by_action["actions/checkout"].startswith("v7.")
    assert by_action["actions/setup-python"].startswith("v7.")
    assert by_action["actions/setup-node"].startswith("v7.")
    assert by_action["actions/upload-artifact"].startswith("v7.")
