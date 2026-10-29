"""Fail-closed verification of the observed GnuCOBOL oracle identity.

The adapter must only claim a verified runtime identity when the image
digest matches the pin *and* the observed ``cobc --version`` banner proves
the declared compiler version. Anything else is UNAVAILABLE.
"""

from __future__ import annotations

import json
import subprocess as _real_subprocess

import pytest

from engine.domain.identities import AdapterStatus
from engine.oracle.adapter import OracleAdapterConfig
from engine.oracle.docker_adapter import DockerOracleAdapter

DECLARED = "3.1.2.0"
DIGEST = "sha256:" + "c" * 64


class _Completed:
    def __init__(self, returncode: int = 0, stdout: bytes = b"", stderr: bytes = b""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class _SubprocessStub:
    """Stand-in for the ``subprocess`` module used by the adapter."""

    CREATE_NO_WINDOW = 0
    TimeoutExpired = _real_subprocess.TimeoutExpired
    FileNotFoundError = FileNotFoundError

    def __init__(self, *, banner: str | None, image_digest: str, digest_ok: bool = True):
        self.calls: list[list[str]] = []
        self._banner = banner
        self._image_digest = image_digest
        self._digest_ok = digest_ok

    def run(self, cmd, **kwargs):  # noqa: ANN001 - mirrors subprocess.run
        args = [str(part) for part in cmd]
        self.calls.append(args)
        if args[:2] == ["docker", "info"]:
            return _Completed(0, b"Server: ok\n")
        if args[:3] == ["docker", "image", "inspect"]:
            if not self._digest_ok:
                return _Completed(1, b"", b"no such image")
            payload = [
                {
                    "RepoDigests": [f"gnucobol-ocesql@{self._image_digest}"],
                    "Id": self._image_digest,
                }
            ]
            return _Completed(0, json.dumps(payload).encode())
        if "cobc" in args:
            if self._banner is None:
                return _Completed(1, b"", b"docker run failed")
            return _Completed(0, f"{self._banner}\n".encode())
        if args[:2] == ["docker", "version"]:
            return _Completed(0, b"27.0.1\n")
        raise AssertionError(f"unexpected command: {args}")


def _make_adapter(
    monkeypatch: pytest.MonkeyPatch,
    *,
    banner: str | None,
    declared: str = DECLARED,
    image_digest: str = DIGEST,
    digest_ok: bool = True,
) -> tuple[DockerOracleAdapter, _SubprocessStub]:
    config = OracleAdapterConfig(
        oracle_id="gnucobol-3.1.2",
        image_digest=image_digest,
        compiler_version=declared,
    )
    stub = _SubprocessStub(banner=banner, image_digest=image_digest, digest_ok=digest_ok)
    monkeypatch.setattr("engine.oracle.docker_adapter.subprocess", stub)
    return DockerOracleAdapter(config), stub


class TestCompilerMatchesDeclared:
    def test_accepts_real_banner(self):
        assert DockerOracleAdapter.compiler_matches_declared(
            "cobc (GnuCOBOL) 3.1.2.0", DECLARED
        )

    @pytest.mark.parametrize(
        ("observed", "declared"),
        [
            ("cobc (GnuCOBOL) 3.2.1", "3.1.2.0"),
            ("cobc (GnuCOBOL) 3.1.2", "3.1.2.0"),
            ("", "3.1.2.0"),
            ("cobc (GnuCOBOL) 3.1.2.0", ""),
            ("cobc (GnuCOBOL) 3.1.2.0", "0.0.0"),
        ],
    )
    def test_rejects_mismatches(self, observed: str, declared: str):
        assert not DockerOracleAdapter.compiler_matches_declared(observed, declared)


class TestVerifiedIdentity:
    def test_banner_matching_declared_is_verified(self, monkeypatch):
        adapter, _ = _make_adapter(monkeypatch, banner="cobc (GnuCOBOL) 3.1.2.0")

        assert adapter.identity_failure_reason == ""
        assert adapter.verified_image_digest == DIGEST
        assert adapter.verified_image_ref.startswith("gnucobol-ocesql@")
        assert adapter.observed_compiler_version == "cobc (GnuCOBOL) 3.1.2.0"
        assert adapter.probe() == AdapterStatus.AVAILABLE

        identity = adapter.get_identity()
        assert identity.image_digest == DIGEST
        assert identity.compiler_version == "cobc (GnuCOBOL) 3.1.2.0"

    def test_unpinned_digest_is_not_verified(self, monkeypatch):
        adapter, _ = _make_adapter(
            monkeypatch, banner="cobc (GnuCOBOL) 3.1.2.0", image_digest="latest"
        )

        assert adapter.verified_image_digest == ""
        assert adapter.identity_failure_reason
        assert adapter.probe() == AdapterStatus.UNAVAILABLE


class TestCompilerMismatchFailsClosed:
    def test_version_drift_drops_verified_identity(self, monkeypatch, tmp_path):
        adapter, _ = _make_adapter(monkeypatch, banner="cobc (GnuCOBOL) 3.2.1")
        source = tmp_path / "MAIN.cob"
        source.write_text("       IDENTIFICATION DIVISION.\n", encoding="utf-8")

        assert adapter.verified_image_digest == ""
        assert adapter.verified_image_ref == ""
        assert adapter.observed_compiler_version == ""
        assert DECLARED in adapter.identity_failure_reason
        assert "3.2.1" in adapter.identity_failure_reason
        assert adapter.probe() == AdapterStatus.UNAVAILABLE

        identity = adapter.get_identity()
        assert identity.compiler_version == DECLARED

        result = adapter.execute(run_id=_run_id(), source_path=str(tmp_path))
        assert result.status == AdapterStatus.UNAVAILABLE
        assert b"unverified" in result.stderr

    def test_missing_banner_is_not_verified(self, monkeypatch):
        adapter, _ = _make_adapter(monkeypatch, banner=None)

        assert adapter.verified_image_digest == ""
        assert adapter.observed_compiler_version == ""
        assert adapter.identity_failure_reason
        assert adapter.probe() == AdapterStatus.UNAVAILABLE

    def test_digest_mismatch_is_not_verified(self, monkeypatch):
        adapter, _ = _make_adapter(monkeypatch, banner="cobc (GnuCOBOL) 3.1.2.0", digest_ok=False)

        assert adapter.verified_image_digest == ""
        assert adapter.identity_failure_reason
        assert adapter.probe() == AdapterStatus.UNAVAILABLE


def _run_id():
    from engine.domain.identities import RunId

    return RunId(value="run-identity-001")
