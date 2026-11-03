"""Deployment hardening gates (audit L.3.4, L.3.5).

Two production scripts had a real defect that no test could catch, because
neither script runs on a CI host. Their source contracts are pinned here
(the repo's established pattern, cf. ``test_shell_script_contracts.py`` and
``test_ci_deployment_security.py``).

* **L.3.5 — ``scripts/backup/restore.sh`` deleted the live volumes before it
  validated the backup.** It only checked that ``control-plane.db`` and
  ``workspaces.tar.gz`` *exist* (line 12), then ran ``docker compose down``
  and ``docker volume rm``. A truncated SQLite file or an empty/corrupt
  ``workspaces.tar.gz`` passes that existence check — so a corrupt backup
  destroyed the current volumes and then restored garbage. ``backup.sh``
  already chains ``verify_backup.py`` (BL-147) to prove what it *wrote* is
  restorable; restore must prove what it is about to *read from* is
  restorable, and it must do so before the first destructive command.

* **L.3.4 — ``scripts/deploy/verify-production.sh``'s auth check passed on
  *any* curl failure.** ``! curl -fsS .../applications`` inverts curl's exit
  status, so a down backend (connection refused, exit 7), a 500, or a 403 all
  satisfied it: the post-deploy gate could report "api auth enforced" while the
  API was broken or wide open. The check must assert the response is exactly
  HTTP 401 Unauthorized.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RESTORE = REPO / "scripts" / "backup" / "restore.sh"
VERIFY_PROD = REPO / "scripts" / "deploy" / "verify-production.sh"


def _executable_lines(text: str) -> list[str]:
    return [
        line
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


class TestRestoreVerifiesBeforeDestroying:
    """L.3.5: a corrupt backup must abort with the volumes still intact."""

    def test_restore_runs_the_backup_verifier(self) -> None:
        text = RESTORE.read_text(encoding="utf-8")
        assert "verify_backup.py" in text, (
            "restore.sh must run scripts/backup/verify_backup.py to prove the "
            "backup is restorable (not merely that its files exist)"
        )

    def test_verification_precedes_every_destructive_command(self) -> None:
        """The verifier must run before `down` and before `volume rm`."""
        text = RESTORE.read_text(encoding="utf-8")
        verify_at = text.find("verify_backup.py")
        down_at = text.find("docker compose")
        volume_rm_at = text.find("docker volume rm")
        assert verify_at != -1
        assert down_at != -1 and volume_rm_at != -1
        assert verify_at < down_at, (
            "restore.sh must verify the backup before stopping the stack "
            "(docker compose down) — otherwise a corrupt backup still takes "
            "the running system down first"
        )
        assert verify_at < volume_rm_at, (
            "restore.sh must verify the backup before `docker volume rm` — "
            "deleting the live volumes on an unverified backup destroys the "
            "only good copy (audit L.3.5)"
        )

    def test_verifier_mounts_the_backup_read_only(self) -> None:
        """The verification step must not mutate the backup it inspects."""
        text = RESTORE.read_text(encoding="utf-8")
        verify_block = _executable_lines(text)
        verify_line = next(
            ln for ln in verify_block if "verify_backup.py" in ln
        )
        assert "verify_backup.py" in verify_line
        # the docker run that carries it mounts /backup read-only
        assert "/backup:ro" in text, (
            "the verification container must mount the backup read-only"
        )


class TestVerifyProductionAuthCheck:
    """L.3.4: the auth gate must assert a real 401, not `! curl`."""

    def test_old_negated_curl_pattern_is_gone(self) -> None:
        text = VERIFY_PROD.read_text(encoding="utf-8")
        for line in _executable_lines(text):
            assert "! curl" not in line, (
                "verify-production.sh still uses `! curl`, which passes on ANY "
                f"curl failure (down backend, 500, 403): {line.strip()!r}"
            )

    def test_auth_check_asserts_http_401(self) -> None:
        text = VERIFY_PROD.read_text(encoding="utf-8")
        assert "%{http_code}" in text, (
            "the auth check must capture the HTTP status code, not just "
            "curl's exit status"
        )
        assert '"401"' in text, (
            "the auth check must assert the response is exactly 401 "
            "Unauthorized"
        )
        assert "/applications" in text, (
            "the auth check must probe the protected /applications route"
        )

    def test_negated_status_inverts_any_failure(self) -> None:
        """Behavioural proof of WHY `! cmd` was a defect.

        ``!`` inverts the wrapped command's exit status, so *any* failure —
        a down backend, a 500, a 403 — is recorded as PASS by the old gate.
        """
        # stands in for `curl` against a down backend (non-zero exit)
        proc = subprocess.run(["bash", "-c", "! false"], capture_output=True)
        assert proc.returncode == 0, (
            "expected `! <failing command>` to exit 0 — the old auth check "
            "recorded PASS whenever curl failed for any reason"
        )
