"""Docker build-context hygiene (audit L.3.6).

``.dockerignore`` was git-ignored and absent, so every ``docker build``
shipped the entire repository — including ``.env*``, ``*.secret``, private
keys, ``test-artifacts/``, and ``.git/`` — into the image build context.
This pins the contract that the file exists, is tracked, and excludes the
dangerous patterns.  A behavioral check also asserts that no tracked file
under the repo matches a secret/credential pattern (defence in depth).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DOCKERIGNORE = REPO / ".dockerignore"


def _tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, cwd=REPO
    )
    return [line for line in out.stdout.splitlines() if line.strip()]


class TestDockerignoreContract:
    def test_dockerignore_exists_and_is_tracked(self) -> None:
        assert DOCKERIGNORE.is_file(), ".dockerignore must exist"
        tracked = _tracked_files()
        assert ".dockerignore" in tracked, (
            ".dockerignore must be tracked (not git-ignored) so the contract "
            "is enforced in version control"
        )

    def test_dockerignore_excludes_secrets_and_credentials(self) -> None:
        text = DOCKERIGNORE.read_text(encoding="utf-8")
        for pattern in (".env", "*.secret", "*.pem", "*.key", "*.p12"):
            assert pattern in text, (
                f".dockerignore must exclude {pattern!r} to keep secrets out of "
                "the build context"
            )

    def test_dockerignore_excludes_build_artifacts_and_vcs(self) -> None:
        text = DOCKERIGNORE.read_text(encoding="utf-8")
        for pattern in ("test-artifacts/", "node_modules/", ".git/", "__pycache__/"):
            assert pattern in text, (
                f".dockerignore must exclude {pattern!r}"
            )

    def test_no_tracked_secret_files(self) -> None:
        """Defence in depth: no tracked file may look like a secret/credential."""
        offenders: list[str] = []
        secret_suffixes = (".env", ".pem", ".key", ".p12", ".jks", ".secret")
        for path in _tracked_files():
            name = path.rsplit("/", 1)[-1]
            # Example templates are committed on purpose (no real secrets).
            if name.endswith(".example"):
                continue
            if name == ".env" or name.startswith(".env."):
                offenders.append(path)
                continue
            if any(name.endswith(s) for s in secret_suffixes):
                offenders.append(path)
        assert not offenders, (
            "tracked files look like secrets/credentials — they must not be "
            f"committed: {offenders}"
        )
