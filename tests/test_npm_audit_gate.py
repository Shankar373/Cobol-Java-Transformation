"""The npm audit gate excepts exactly one advisory and fails on everything else."""

from __future__ import annotations

import datetime

from tools.npm_audit_gate import ADVISORY, EXPIRES, evaluate

TODAY = datetime.date(2026, 11, 18)
URL = f"https://github.com/advisories/{ADVISORY}"


def _audit(**extra):
    vulns = {
        "picomatch": {"severity": "high", "via": [{"url": URL}]},
        "fdir": {"severity": "high", "via": ["picomatch"]},
        "vite": {"severity": "high", "via": ["fdir", "picomatch"]},
    }
    vulns.update(extra)
    return {"vulnerabilities": vulns}


def test_clean_audit_passes() -> None:
    assert evaluate({"vulnerabilities": {}}, {}, None, TODAY) == []


def test_only_the_excepted_advisory_and_its_dependents_pass() -> None:
    assert evaluate(_audit(), {}, None, TODAY) == []


def test_any_other_vulnerability_fails() -> None:
    problems = evaluate(_audit(lodash={"severity": "critical", "via": [{"url": "https://github.com/advisories/GHSA-other"}]}), {}, None, TODAY)
    assert any(p.startswith("lodash") for p in problems)


def test_a_dependent_with_an_additional_cause_fails() -> None:
    problems = evaluate(_audit(vite={"severity": "high", "via": ["picomatch", {"url": "https://github.com/advisories/GHSA-x"}]}), {}, None, TODAY)
    assert any(p.startswith("vite") for p in problems)


def test_a_second_advisory_on_picomatch_itself_fails() -> None:
    audit = _audit(picomatch={"severity": "high", "via": [{"url": URL}, {"url": "https://github.com/advisories/GHSA-y"}]})
    assert evaluate(audit, {}, None, TODAY)


def test_exception_is_void_when_picomatch_reaches_production() -> None:
    tree = {"dependencies": {"react": {"dependencies": {"picomatch": {"version": "4.0.7"}}}}}
    assert any("PRODUCTION" in p for p in evaluate(_audit(), tree, None, TODAY))


def test_exception_expires_and_yields_to_a_fixed_release() -> None:
    assert any("expired" in p for p in evaluate(_audit(), {}, None, EXPIRES + datetime.timedelta(days=1)))
    assert any("upgrade" in p for p in evaluate(_audit(), {}, "4.0.8", TODAY))
    assert evaluate(_audit(), {}, "4.0.7", TODAY) == []
