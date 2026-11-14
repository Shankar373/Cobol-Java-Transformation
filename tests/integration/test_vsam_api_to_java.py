"""Product workflow, end to end: the bytes the migration API serves are what the generated Java consumes.

application source (HTTP create + ingest) -> ``GET /discovery`` (FD + VSAM assessment) -> ``POST /vsam/migrate`` -> stored result -> status ->
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
import io
import json
import os
import sys
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api.app as api_app
from api.service import Service
from api.store import Store

sys.path.insert(0, str(Path(__file__).parent))
import test_vsam_java_consumer as consumer  # noqa: E402  (shared fixture: program, rows, runners; not duplicated)

OPTIONS = {"file": "F", "source_platform": "IBM_ZOS", "target_platform": "GNUCOBOL_X86_DEFAULT",
           "source_encoding": "EBCDIC_CP037", "destination_encoding": "ASCII"}


@pytest.fixture()
def product(tmp_path, monkeypatch):
    """The real service and store behind the real routes: the application is created and its source ingested over HTTP."""
    monkeypatch.setenv("CONTROL_PLANE_WORKSPACE_DIR", str(tmp_path / "work"))
    store = Store()
    monkeypatch.setattr(api_app, "_store", store)
    monkeypatch.setattr(api_app, "_service", Service(store))
    client = TestClient(api_app.app)
    created = client.post("/applications", json={"target_runtime": "spring_boot", "name": "vsam-e2e", "workload_id": "w"})
    assert created.status_code == 201, created.text
    app_id = created.json()["id"]
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("RDR.cob", consumer.program())
    ingested = client.post(f"/applications/{app_id}/ingest",
                           files={"file": ("src.zip", archive.getvalue(), "application/zip")})
    assert ingested.status_code == 201, ingested.text
    return client, app_id


def test_the_api_artifact_is_what_generated_java_and_cobol_both_read(product, tmp_path):
    consumer.need_lane()
    client, app_id = product

    # discovery and assessment through the real HTTP route (create, ingest and discovery are all HTTP calls here)
    discovered = client.get(f"/applications/{app_id}/discovery")
    assert discovered.status_code == 200, discovered.text
    assessment = discovered.json()["cobol_programs"][0]["vsam_assessment"]
    assert [a["file"] for a in assessment] == ["F"] and assessment[0]["organization"] == "SEQUENTIAL"
    assert assessment[0]["migration"]["status"] == "REQUIRES_PLATFORMS"
    assert assessment[0]["record_layouts"][0]["supported"] is True

    # submit the mainframe-format dataset
    mainframe = consumer.mainframe_bytes()
    created = client.post(f"/applications/{app_id}/vsam/migrate",
                          files={"dataset": ("F.DAT", mainframe, "application/octet-stream")},
                          data={"options": json.dumps(OPTIONS)})
    assert created.status_code == 201, created.text
    report = created.json()
    assert report["state"] == "RECONCILED" and report["success"] is True and report["complete"] is True
    assert report["converted_record_count"] == len(consumer.ROWS) and report["rejected_record_count"] == 0

    # the stored result, read back through the status route
    base = f"/applications/{app_id}/vsam/migrations/{report['migration_id']}"
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
    client, app_id = product

    def submit():
        return client.post(f"/applications/{app_id}/vsam/migrate",
                           files={"dataset": ("F.DAT", consumer.mainframe_bytes(), "application/octet-stream")},
                           data={"options": json.dumps(OPTIONS)})

    first = submit().json()
    base = f"/applications/{app_id}/vsam/migrations/{first['migration_id']}/download"
    first_bytes = client.get(base).content                           # retained before the second submission
    second = submit().json()
    assert second["migration_id"] == first["migration_id"]
    assert second["output_sha256"] == first["output_sha256"]
    second_bytes = client.get(f"/applications/{app_id}/vsam/migrations/{second['migration_id']}/download").content
    assert second_bytes == first_bytes
    assert hashlib.sha256(first_bytes).hexdigest() == hashlib.sha256(second_bytes).hexdigest() == first["output_sha256"]
