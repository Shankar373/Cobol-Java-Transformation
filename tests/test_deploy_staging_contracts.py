"""Deployment contracts found by the first real staging deployment (2026-11-11), pinned so they cannot regress."""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = [*sorted((REPO / "scripts" / "deploy").glob("*.sh")), *sorted((REPO / "scripts" / "backup").glob("*.sh")),
           REPO / "scripts" / "ci" / "build-image.sh"]


def _text(name: str) -> str:
    return (REPO / name).read_text(encoding="utf-8")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX execute bits")
@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_documented_scripts_are_executable(script):
    # the docs run ./scripts/deploy/start-production.sh, which exec's ./scripts/deploy/verify-production.sh
    assert os.stat(script).st_mode & stat.S_IXUSR, script


def test_the_api_container_gets_the_image_provenance_the_candidate_adapter_needs():
    compose = _text("docker-compose.production.yml")
    assert ":/app/test-artifacts/docker-image-provenance.json:ro" in compose
    start = _text("scripts/deploy/start-production.sh")
    assert 'if [ ! -f "$PROVENANCE" ]' in start and "FATAL: image provenance record" in start
    verify = _text("scripts/deploy/verify-production.sh")
    assert "candidate adapter AVAILABLE" in verify


def test_the_nginx_loopback_healthcheck_does_not_verify_a_hostname_certificate():
    assert "wget -q --no-check-certificate -O /dev/null https://127.0.0.1/health" in _text("docker-compose.production.yml")


def test_verify_resolves_the_oracle_pin_when_run_standalone():
    assert "SYSTEMAOPS_ORACLE_DIGEST" in _text("scripts/deploy/verify-production.sh")


def test_env_examples_are_checked_out_with_lf():
    assert ".env*.example text eol=lf" in _text(".gitattributes")


def test_backup_records_the_deployed_tag_not_a_hardcoded_production_tag():
    backup = _text("scripts/backup/backup.sh")
    assert 'docker image inspect "systemaops-api:${TAG}"' in backup
    assert 'docker-image-provenance.${TAG}.json' in backup
    assert "systemaops-api:production" not in backup.replace("api image tag", "")


def test_wsl_path_translation_is_limited_to_windows_drive_mounts():
    # a path on WSL's own filesystem is valid to a Linux (Docker Desktop WSL-integration) daemon as it is
    for name in ("scripts/backup/backup.sh", "scripts/backup/restore.sh"):
        assert '[[ "$1" == /mnt/[a-z]/* ]]' in _text(name), name


def test_rollback_ignores_an_inherited_image_tag():
    rollback = _text("scripts/deploy/rollback.sh")
    assert rollback.index("unset IMAGE_TAG") < rollback.index("up -d --remove-orphans --wait api")
