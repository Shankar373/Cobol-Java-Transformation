"""Shell-script deployment contract (P2: scripts must be runnable at all).

Every deploy/backup entry point (``scripts/**/*.sh``) is invoked on a Linux
host as ``./scripts/...``. Two facts about them were true in the repository
and never checked:

* **line endings** — all six scripts were committed as CRLF. On Linux that
  makes the shebang line ``#!/usr/bin/env bash\\r`` a bad interpreter, so
  ``start-production.sh`` died before its first command; CI never noticed
  because no workflow executes a ``.sh`` file. ``.gitattributes`` now pins
  ``eol=lf`` for ``*.sh`` and this test pins the bytes themselves;
* **syntax** — nothing parsed them. ``bash -n`` now runs over every script
  (locally and in CI, where bash exists), so a broken ``case``/``if`` fails
  the suite instead of the production host.

The ``bash -n`` check is skipped only when no bash binary exists at all
(documented in the skip reason); the CRLF/shebang checks are unconditional.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
#: Generated/vendored trees are not deploy entry points (none contain .sh
#: today; kept explicit so a future dependency cannot fail this suite).
_EXCLUDED_PARTS = {"node_modules", ".git", "test-artifacts", "__pycache__", "dist"}


def _shell_scripts() -> list[Path]:
    found = [
        path
        for path in SCRIPTS_DIR.rglob("*.sh")
        if not _EXCLUDED_PARTS.intersection(path.parts)
    ]
    return sorted(found)


def test_at_least_the_known_entry_points_exist() -> None:
    names = {p.name for p in _shell_scripts()}
    # The four deploy scripts + backup/restore are the production surface.
    assert {
        "start-production.sh",
        "verify-production.sh",
        "build-production.sh",
        "rollback.sh",
        "backup.sh",
        "restore.sh",
    } <= names


@pytest.mark.parametrize(
    "script", _shell_scripts(), ids=lambda p: f"{p.parent.name}/{p.name}"
)
def test_script_is_lf_only_with_a_bash_shebang(script: Path) -> None:
    data = script.read_bytes()
    assert b"\r" not in data, (
        f"{script.relative_to(REPO_ROOT)} contains CR bytes; a CRLF shebang "
        "fails on Linux with 'bad interpreter: /usr/bin/env bash\\r'. "
        "Commit LF (see .gitattributes: *.sh text eol=lf)."
    )
    assert data.startswith(b"#!/usr/bin/env bash\n"), (
        f"{script.relative_to(REPO_ROOT)} must start with "
        "'#!/usr/bin/env bash' so it runs under bash explicitly"
    )


def test_gitattributes_pins_lf_for_shell_scripts() -> None:
    attributes = REPO_ROOT / ".gitattributes"
    assert attributes.is_file(), (
        ".gitattributes must pin *.sh to LF or the CRLF regression returns "
        "on the next Windows checkout"
    )
    text = attributes.read_text(encoding="utf-8")
    rules = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert "*.sh text eol=lf" in rules


# ---------------------------------------------------------------------------
# Wiring pins: the deploy/backup behaviour fixes have no CI host to execute
# against, so their source contracts are asserted here (the repo's established
# source-pin pattern, cf. TestProductionDeploymentWiring).
# ---------------------------------------------------------------------------


def test_start_script_preflights_before_mutating() -> None:
    """`start-production.sh` must validate before `up` (not after it fails)."""
    text = (SCRIPTS_DIR / "deploy" / "start-production.sh").read_text(
        encoding="utf-8"
    )
    assert "docker info" in text, "daemon reachability must be checked"
    assert "config --quiet" in text, "the compose stack must be render-checked"
    up_at = text.find(" up -d ")
    info_at = text.find("docker info")
    config_at = text.find("config --quiet")
    assert up_at != -1
    assert 0 <= info_at < up_at, "daemon check must run before `up`"
    assert 0 <= config_at < up_at, "compose render check must run before `up`"


def test_verify_script_derives_the_api_container_id() -> None:
    """No hardcoded compose-generated name: it breaks under project renames."""
    text = (SCRIPTS_DIR / "deploy" / "verify-production.sh").read_text(
        encoding="utf-8"
    )
    assert "ps -q --all api" in text, (
        "the api container id must come from compose, not a hardcoded name"
    )
    assert "docker inspect systemaops-production-api-1" not in text
    assert "docker inspect '${API_CONTAINER}'" in text or (
        "docker inspect \"${API_CONTAINER}\"" in text
    ) or "'${API_CONTAINER}' | grep" in text


def test_backup_script_verifies_the_backup_it_wrote() -> None:
    """`backup.sh` must fail when the backup would not restore (BL-147)."""
    text = (SCRIPTS_DIR / "backup" / "backup.sh").read_text(encoding="utf-8")
    assert "verify_backup.py" in text, (
        "backup.sh must chain scripts/backup/verify_backup.py"
    )
    verify_at = text.find("verify_backup.py")
    tar_at = text.find("workspaces.tar.gz")
    ok_at = text.find('echo "OK: backup written')
    assert tar_at != -1 and ok_at != -1
    assert tar_at < verify_at < ok_at, (
        "verification must run after both artifacts are written and before "
        "the script reports OK"
    )
    verifier = REPO_ROOT / "scripts" / "backup" / "verify_backup.py"
    assert verifier.is_file()


@pytest.mark.parametrize(
    "script", _shell_scripts(), ids=lambda p: f"{p.parent.name}/{p.name}"
)
def test_script_parses_with_bash(script: Path) -> None:
    """``bash -n``: syntax errors fail here, not on the production host."""
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("no bash binary available on this machine")
    # WSL/bash-on-Windows cannot resolve a Windows absolute path
    # (C:\\... becomes CUsers...), so pass a relative POSIX-style path.
    rel = os.path.relpath(script, REPO_ROOT).replace(os.sep, "/")
    result = subprocess.run(
        [bash, "-n", rel],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"{rel} has a shell syntax error:\n{result.stderr}"
    )
