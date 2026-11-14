"""Product workflow, end to end: the bytes the migration API serves are what the generated Java consumes.

application source -> FD discovery -> VSAM assessment -> ``POST /vsam/migrate`` -> stored result -> status ->
``GET .../download`` -> generated Java (real transformation producer, compiled, run) and the original COBOL program
(GnuCOBOL 3.1.2) reading the *same downloaded bytes* -> both compared with each other and with values built
independently from the fixture rows (the migration engine never produces an expected value).

Proof class: GENERATED_JAVA + GNUCOBOL_DIFFERENTIAL for a fixed-length sequential dataset of DISPLAY, COMP and COMP-3
fields migrated IBM_ZOS (EBCDIC cp037, IBM 2/4/8 binary widths) -> GNUCOBOL_X86_DEFAULT.  Not proved: indexed or
variable files, COMP-5, or any IBM runtime.  The persisted artifact is a file under the workspace (ADR-0011).
Docker lane: RUN_DOCKER_TESTS=1, the GnuCOBOL image and a JDK on PATH.  ``VSAM_EVIDENCE_DIR`` makes the test keep its
evidence file there (CI uploads it); otherwise it is written under pytest's tmp_path.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api.app as api_app
from api.ingestion import discover_application

sys.path.insert(0, str(Path(__file__).parent))
import test_vsam_java_consumer as consumer  # noqa: E402  (shared fixture: program, rows, runners; not duplicated)

OPTIONS = {"file": "F", "source_platform": "IBM_ZOS", "target_platform": "GNUCOBOL_X86_DEFAULT",
           "source_encoding": "EBCDIC_CP037", "destination_encoding": "ASCII"}
APP = "app-e2e"


@pytest.fixture()
def product(tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    (src / "RDR.cob").write_text(consumer.program(), encoding="utf-8")

    class _App:
        cobol_source_path = str(src)

    class _Svc:
        def get_application(self, app_id):
            return _App()

    monkeypatch.setattr(api_app, "_svc", lambda: _Svc())
    monkeypatch.setenv("CONTROL_PLANE_WORKSPACE_DIR", str(tmp_path / "work"))
    return TestClient(api_app.app), src


def test_the_api_artifact_is_what_generated_java_and_cobol_both_read(product, tmp_path):
    consumer.need_lane()
    client, src = product

    # discovery and assessment through the real ingestion path
    discovered = discover_application(src, APP)
    assessment = discovered.cobol_programs[0]["vsam_assessment"]
    assert [a["file"] for a in assessment] == ["F"] and assessment[0]["organization"] == "SEQUENTIAL"
    assert assessment[0]["migration"]["status"] == "REQUIRES_PLATFORMS"
    assert assessment[0]["record_layouts"][0]["supported"] is True

    # submit the mainframe-format dataset
    mainframe = consumer.mainframe_bytes()
    created = client.post(f"/applications/{APP}/vsam/migrate",
                          files={"dataset": ("F.DAT", mainframe, "application/octet-stream")},
                          data={"options": json.dumps(OPTIONS)})
    assert created.status_code == 201, created.text
    report = created.json()
    assert report["state"] == "RECONCILED" and report["success"] is True and report["complete"] is True
    assert report["converted_record_count"] == len(consumer.ROWS) and report["rejected_record_count"] == 0

    # the stored result, read back through the status route
    base = f"/applications/{APP}/vsam/migrations/{report['migration_id']}"
    status = client.get(base)
    assert status.status_code == 200 and status.json()["output_sha256"] == report["output_sha256"]

    # the download is the persisted artifact whose checksum is in the report
    downloaded = client.get(base + "/download")
    assert downloaded.status_code == 200
    assert hashlib.sha256(downloaded.content).hexdigest() == report["output_sha256"]
    assert len(downloaded.content) == report["output_bytes"]
    assert downloaded.content != mainframe                                   # the file really was converted

    # the exact downloaded bytes are the input of both consumers
    java_work = consumer.build_java(tmp_path, "java")
    java_run = consumer.run_built_java(java_work, downloaded.content)
    assert java_run.returncode == 0, java_run.stderr.decode(errors="replace")
    java_out = java_run.stdout.decode().splitlines()
    cobol_out = consumer.run_cobol(tmp_path, downloaded.content)
    expected = consumer.expected()                                           # built from the fixture rows only
    assert java_out == cobol_out == expected

    evidence = {
        "fixture": {"program": "RDR.cob", "source_sha256": hashlib.sha256(consumer.program().encode()).hexdigest(),
                    "rows": len(consumer.ROWS), "mainframe_sha256": hashlib.sha256(mainframe).hexdigest()},
        "migration": {"id": report["migration_id"], "state": report["state"], "options": OPTIONS,
                      "engine_version": report["engine_version"]},
        "downloaded_artifact": {"sha256": hashlib.sha256(downloaded.content).hexdigest(),
                                "bytes": len(downloaded.content), "equals_report_hash": hashlib.sha256(downloaded.content).hexdigest() == report["output_sha256"]},
        "generated_java_files": sorted(p.name for p in java_work.glob("*.java")),
        "cobol_output": cobol_out, "java_output": java_out, "expected": expected,
        "comparison": {"java_equals_cobol": java_out == cobol_out, "both_equal_independent_expected": java_out == expected and cobol_out == expected},
        "proof_class": "GENERATED_JAVA + GNUCOBOL_DIFFERENTIAL (not IBM runtime)",
    }
    target = Path(os.environ.get("VSAM_EVIDENCE_DIR") or tmp_path)
    target.mkdir(parents=True, exist_ok=True)
    (target / "vsam-api-to-java-evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")


def test_the_unconverted_mainframe_bytes_do_not_satisfy_the_same_comparison(product, tmp_path):
    """Control: the API output, not the input file, is what makes Java and COBOL agree with the expected values."""
    consumer.need_lane()
    work = consumer.build_java(tmp_path, "control")
    run = consumer.run_built_java(work, consumer.mainframe_bytes())
    shown = run.stdout.decode(errors="replace").splitlines() if run.returncode == 0 else None
    assert shown != consumer.expected()
    assert consumer.run_cobol(tmp_path, consumer.mainframe_bytes()) != consumer.expected()


def test_a_second_identical_submission_yields_the_same_id_and_the_same_downloaded_bytes(product):
    client, _ = product
    post = lambda: client.post(f"/applications/{APP}/vsam/migrate",  # noqa: E731
                               files={"dataset": ("F.DAT", consumer.mainframe_bytes(), "application/octet-stream")},
                               data={"options": json.dumps(OPTIONS)})
    first, second = post().json(), post().json()
    assert first["migration_id"] == second["migration_id"] and first["output_sha256"] == second["output_sha256"]
    base = f"/applications/{APP}/vsam/migrations/{first['migration_id']}/download"
    assert client.get(base).content == client.get(base).content
