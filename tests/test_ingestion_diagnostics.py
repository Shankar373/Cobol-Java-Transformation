from pathlib import Path

import pytest

import api.ingestion as ingestion


def test_discovery_preserves_cobol_failure_as_diagnostic(monkeypatch, tmp_path):
    class FailingCobolDiscovery:
        def discover(self, *args, **kwargs):
            raise RuntimeError("COBOL parser unavailable")

    class EmptyJclDiscovery:
        def discover(self, *args, **kwargs):
            return type("JclApp", (), {"jobs": [], "dependencies": []})()

    monkeypatch.setattr(
        "engine.transformation.application_discovery.ApplicationDiscovery",
        FailingCobolDiscovery,
    )
    monkeypatch.setattr(
        "engine.transformation.jcl_discovery.JclDiscovery",
        EmptyJclDiscovery,
    )

    result = ingestion.discover_application(tmp_path, "demo")

    assert result.discovery_success is False
    assert result.discovery_errors == [
        {"stage": "COBOL_DISCOVERY", "message": "COBOL parser unavailable"}
    ]
    assert result.cobol_programs == []
    assert result.jcl_jobs == []


def test_discovery_preserves_jcl_failure_as_diagnostic(monkeypatch, tmp_path):
    class EmptyCobolDiscovery:
        def discover(self, *args, **kwargs):
            return type(
                "CobolApp",
                (),
                {"programs": [], "copybooks": [], "edges": []},
            )()

    class FailingJclDiscovery:
        def discover(self, *args, **kwargs):
            raise RuntimeError("JCL parser unavailable")

    monkeypatch.setattr(
        "engine.transformation.application_discovery.ApplicationDiscovery",
        EmptyCobolDiscovery,
    )
    monkeypatch.setattr(
        "engine.transformation.jcl_discovery.JclDiscovery",
        FailingJclDiscovery,
    )

    result = ingestion.discover_application(tmp_path, "demo")

    assert result.discovery_success is False
    assert result.discovery_errors == [
        {"stage": "JCL_DISCOVERY", "message": "JCL parser unavailable"}
    ]


def test_ingest_zip_rejects_traversal(tmp_path):
    import io
    import zipfile

    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as zf:
        zf.writestr("../escape.cob", "IDENTIFICATION DIVISION.")

    with pytest.raises(ingestion.IngestionError, match="Unsafe ZIP entry"):
        ingestion.ingest_zip(payload.getvalue(), "demo")
