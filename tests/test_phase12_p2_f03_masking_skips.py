"""Phase 12 P2 — BL-092 (audit F-03): masking skips must fail, not skip.

Two tests silently converted regressions into a passing suite:

1. ``tests/test_universal_modernization.py::TestApplicationAssembly._get_assembly``
   called ``pytest.skip`` when generation failed — a generation regression
   produced a skip instead of a failure.
2. ``tests/integration/test_phase_d_negative_integration.py::TestUnsupportedJclConstruct``
   called ``pytest.skip`` when the workload classified as FULL — a detection
   regression (unsupported JCL constructs no longer found) produced a skip
   instead of a failure.

These behavioral tests drive both helpers with the failing input.  A
``Skipped`` outcome is converted into an explicit test failure (RED while
the masking skip exists); after the fix the helpers raise
``AssertionError`` with the enforcement message (GREEN).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import tests.test_universal_modernization as universal_mod
import tests.integration.test_phase_d_negative_integration as phase_d


class TestBL092MaskingSkipsRemoved:
    def test_generation_failure_fails_instead_of_skipping(self, monkeypatch):
        """Generation failure must raise AssertionError, never Skipped."""
        monkeypatch.setattr(
            universal_mod.ApplicationGenerator,
            "generate",
            lambda *a, **k: SimpleNamespace(
                success=False, errors=["synthetic BL-092 generation failure"]
            ),
        )
        helper = universal_mod.TestApplicationAssembly()._get_assembly
        try:
            helper()
        except pytest.skip.Exception:
            pytest.fail(
                "BL-092: generation failure was masked by pytest.skip "
                "instead of failing the suite"
            )
        except AssertionError as exc:
            assert "Generation failed" in str(exc), exc
        else:
            pytest.fail(
                "BL-092: generation failure raised no error at all "
                "(regression silently ignored)"
            )

    def test_jcl_full_status_fails_instead_of_skipping(self, monkeypatch):
        """A FULL classification of the unsupported-JCL fixture is a detection
        regression and must raise AssertionError, never Skipped."""
        monkeypatch.setattr(
            phase_d,
            "modernize_jcl_workload",
            lambda *a, **k: SimpleNamespace(
                status="FULL",
                unsupported_constructs=[],
            ),
        )
        case = phase_d.TestUnsupportedJclConstruct()
        try:
            case.test_unsupported_jcl_is_visible_and_classified()
        except pytest.skip.Exception:
            pytest.fail(
                "BL-092: unsupported-JCL detection loss was masked by "
                "pytest.skip instead of failing the suite"
            )
        except AssertionError as exc:
            assert "unsupported" in str(exc).lower(), exc
        else:
            pytest.fail(
                "BL-092: FULL status on the unsupported-JCL fixture raised "
                "no error (detection regression silently ignored)"
            )
