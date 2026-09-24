from __future__ import annotations

from pathlib import Path

import pytest

from api.ingestion import discover_application


def test_cobol_discovery_failure_is_reported(monkeypatch, tmp_path: Path):
    from engine.transformation.application_discovery import ApplicationDiscovery

    def fail(*args, **kwargs):
        raise RuntimeError("parser exploded")

    monkeypatch.setattr(ApplicationDiscovery, "discover", fail)

    result = discover_application(tmp_path, "diagnostic-test")

    assert result.cobol_programs == []
    assert any(
        d["component"] == "COBOL_DISCOVERY" and "parser exploded" in d["message"]
        for d in result.diagnostics
    )


def test_jcl_discovery_failure_is_reported(monkeypatch, tmp_path: Path):
    from engine.transformation.jcl_discovery import JclDiscovery

    def fail(*args, **kwargs):
        raise RuntimeError("jcl parser exploded")

    monkeypatch.setattr(JclDiscovery, "discover", fail)

    result = discover_application(tmp_path, "diagnostic-test")

    assert any(
        d["component"] == "JCL_DISCOVERY" and "jcl parser exploded" in d["message"]
        for d in result.diagnostics
    )


def test_discovery_diagnostics_are_serialized(tmp_path: Path):
    result = discover_application(tmp_path, "diagnostic-test")
    payload = result.to_dict()

    assert "diagnostics" in payload
    assert isinstance(payload["diagnostics"], list)
