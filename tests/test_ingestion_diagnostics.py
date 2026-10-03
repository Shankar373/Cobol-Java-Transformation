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


def test_discovery_scans_cobol_once_and_reuses_that_result(monkeypatch, tmp_path):
    """Regression guard for single-pass discovery.

    ``discover_application`` used to run COBOL discovery a second time to
    build the JCL link graph, walking the whole workspace twice and
    producing two divergent ``CobolApplication`` views. The JCL stage must
    instead reuse the first scan's object identity.
    """
    (tmp_path / "MAIN.cbl").write_text(
        "IDENTIFICATION DIVISION.\nPROGRAM-ID. MAIN.\n"
    )
    (tmp_path / "RUN.JCL").write_text("//RUNJOB JOB\n//S1 EXEC PGM=MAIN\n")

    calls = {"cobol_scans": 0, "linked_with": []}

    class FakeUnit:
        program_id = "MAIN"
        source_path = "MAIN.cbl"
        file_dependencies = []
        calls = []
        copybooks = []
        entry_points = ["MAIN"]

    cobol_app = type(
        "FakeCobolApp",
        (),
        {"programs": [FakeUnit()], "copybooks": ["CPYLIB"], "edges": []},
    )()

    class CountingCobolDiscovery:
        def discover(self, *args, **kwargs):
            calls["cobol_scans"] += 1
            return cobol_app

    class FakeStepExec:
        program = "MAIN"
        procedure = None

    class FakeStep:
        name = "S1"
        exec_ = FakeStepExec()

    class FakeJob:
        name = "RUNJOB"
        steps = [FakeStep()]

    class FakeJclApp:
        jobs = [FakeJob()]
        dependencies = []

    class LinkingJclDiscovery:
        def discover(self, *args, **kwargs):
            return FakeJclApp()

        def link_with_cobol(self, jcl_app, cobol_app_arg):
            calls["linked_with"].append(cobol_app_arg)
            jcl_app.dependencies.append(
                type(
                    "FakeDep",
                    (),
                    {
                        "source": "RUNJOB",
                        "target": "MAIN",
                        "dependency_type": "EXEC_PGM",
                    },
                )()
            )
            return jcl_app

    monkeypatch.setattr(
        "engine.transformation.application_discovery.ApplicationDiscovery",
        CountingCobolDiscovery,
    )
    monkeypatch.setattr(
        "engine.transformation.jcl_discovery.JclDiscovery",
        LinkingJclDiscovery,
    )

    result = ingestion.discover_application(tmp_path, "demo")

    assert result.discovery_success is True
    assert calls["cobol_scans"] == 1
    assert len(calls["linked_with"]) == 1
    assert calls["linked_with"][0] is cobol_app
    assert [p["program_id"] for p in result.cobol_programs] == ["MAIN"]
    assert result.copybooks == ["CPYLIB"]
    assert [job["name"] for job in result.jcl_jobs] == ["RUNJOB"]
    assert any(
        edge["source"] == "RUNJOB" and edge["target"] == "MAIN"
        for edge in result.dependency_edges
    )
