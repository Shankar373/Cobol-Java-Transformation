from __future__ import annotations

from pathlib import Path

from api.ingestion import discover_application
from engine.transformation.application_discovery import ApplicationDiscovery
from engine.transformation.jcl_discovery import JclDiscovery


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


def test_strict_cobol_discovery_raises(monkeypatch, tmp_path: Path):
    def fail(*args, **kwargs):
        raise RuntimeError("strict parser exploded")

    monkeypatch.setattr(ApplicationDiscovery, "_parse_program_unit", fail)

    discovery = ApplicationDiscovery(strict=True)
    monkeypatch.setattr(discovery, "_find_cobol_files", lambda _: [tmp_path / "broken.cbl"])
    (tmp_path / "broken.cbl").write_text("IDENTIFICATION DIVISION.", encoding="utf-8")

    from engine.transformation.application_discovery import DiscoveryError
    try:
        discovery.discover(tmp_path, "strict-test")
    except DiscoveryError as exc:
        assert "strict parser exploded" in str(exc)
    else:
        raise AssertionError("strict discovery did not fail closed")


def test_strict_jcl_discovery_raises(monkeypatch, tmp_path: Path):
    def fail(*args, **kwargs):
        raise RuntimeError("strict jcl parser exploded")

    monkeypatch.setattr(JclDiscovery, "_parser", None, raising=False)
    discovery = JclDiscovery(strict=True)
    monkeypatch.setattr(discovery._parser, "parse", fail)
    jcl = tmp_path / "broken.jcl"
    jcl.write_text("//JOB JOB", encoding="utf-8")

    from engine.transformation.jcl_discovery import JclDiscoveryError
    try:
        discovery.discover(tmp_path)
    except JclDiscoveryError as exc:
        assert "strict jcl parser exploded" in str(exc)
    else:
        raise AssertionError("strict JCL discovery did not fail closed")


def test_discovery_diagnostics_are_serialized(tmp_path: Path):
    result = discover_application(tmp_path, "diagnostic-test")
    payload = result.to_dict()

    assert "diagnostics" in payload
    assert isinstance(payload["diagnostics"], list)
