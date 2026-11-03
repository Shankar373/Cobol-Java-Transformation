"""Audit CI-F3: on the Docker lane a skip for missing infrastructure fails.

``tests/conftest.py`` turns such skips into failures by matching the skip
reason. The pattern missed several wordings used by real tests ("no JVM
toolchain available ...") and the COBOL/Maven toolchain names, so those
tests could silently skip on a broken CI image.
"""

import pytest

from tests.conftest import _INFRASTRUCTURE_SKIP


@pytest.mark.parametrize(
    "reason",
    [
        "no JVM toolchain available for runtime proof",
        "javac/java not on PATH",
        "cobc not found",
        "GnuCOBOL compiler unavailable",
        "mvn not installed",
        "Maven not available",
        "Docker not available",
        "oracle image missing",
    ],
)
def test_infrastructure_reasons_are_recognised(reason):
    assert _INFRASTRUCTURE_SKIP.search(reason)


@pytest.mark.parametrize(
    "reason",
    [
        "no bash binary available on this machine",
        "cannot create symlinks here: permission denied",
        "start-production.sh not present in this tree",
        "compose config could not be rendered (env missing)",
    ],
)
def test_non_infrastructure_reasons_still_skip(reason):
    assert not _INFRASTRUCTURE_SKIP.search(reason)
