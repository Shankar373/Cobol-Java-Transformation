"""The CI image-build network fallbacks stay narrow: they never touch pins, smoke tests or sandbox isolation."""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
UBUNTU_DOCKERFILES = ("Dockerfile.gnucobol", "Dockerfile.ocesql-pg")


def _script() -> str:
    return (REPO / "scripts" / "ci" / "build-image.sh").read_text(encoding="utf-8")


def test_the_mirror_fallback_is_opt_in_and_only_for_the_ubuntu_images():
    script = _script()
    assert 'grep -q \'^ARG APT_MIRROR\' "$dockerfile"' in script and "! getent hosts archive.ubuntu.com" in script
    assert '[ "$attempt" -gt 1 ]' in script  # never on the first attempt
    for name in UBUNTU_DOCKERFILES:
        text = (REPO / name).read_text(encoding="utf-8")
        assert 'ARG APT_MIRROR=""' in text  # empty by default: the base image's sources are untouched


def test_pins_and_smoke_tests_are_unchanged_by_the_fallbacks():
    gnucobol = (REPO / "Dockerfile.gnucobol").read_text(encoding="utf-8")
    assert "ubuntu:22.04@sha256:5ec03bb3441e8b0bf3b4f9cd4629a1ae763010dc3035bb8da3ae6cf026486401" in gnucobol
    assert "gnucobol3=3.1.2-5" in gnucobol and "libcob4=3.1.2-5" in gnucobol
    assert "cobc (GnuCOBOL) 3.1.2.0" in gnucobol
    script = _script()
    assert "--pull" in script and "exit 1" in script  # a deterministic failure still fails the job


def test_the_fallbacks_are_build_time_only():
    script = _script()
    for runtime_flag in ("docker run", "--privileged", "--cap-add"):
        assert runtime_flag not in script
