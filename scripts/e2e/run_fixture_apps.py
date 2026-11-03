"""Run every fixture application through the real API, one at a time.

Usage (Docker required)::

    E2E_OUT=out.jsonl [E2E_APPS=workload-a,workload-b] [E2E_TARGET=plain_java] \
        python scripts/e2e/run_fixture_apps.py

``E2E_TARGET`` selects the Java runtime target (default ``spring_boot``;
see ``engine/transformation/runtime_adapters.py``); it is recorded in
every result line.

For each ``fixtures/<app>/cobol`` directory: ZIP it -> POST /applications ->
/ingest -> GET /discovery -> /modernize -> poll -> /verdict, under the
default certification contract (``workload_id = e2e-<app>``).  Writes one
JSON line per app to $E2E_OUT (appending; apps already present are skipped
so an interrupted run resumes).
"""
from __future__ import annotations

import io
import json
import os
import sys
import time
import traceback
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = Path(os.environ.get("E2E_OUT", "e2e_results.jsonl")).resolve()
sys.path.insert(0, str(REPO))
os.chdir(REPO)

from fastapi.testclient import TestClient  # noqa: E402

import api.app as app_mod  # noqa: E402
import api.service as svc_mod  # noqa: E402
from api.service import Service  # noqa: E402
from api.store import Store  # noqa: E402

store = Store()
svc = Service(store)
app_mod._store = store
app_mod._service = svc
svc_mod._store = store
svc_mod._service = svc
client = TestClient(app_mod.app)

_SOURCE_SUFFIXES = (".cob", ".cbl", ".cpy", ".jcl", ".txt", ".dat")
TARGET = os.environ.get("E2E_TARGET", "spring_boot")


def _zip(cobol_dir: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(cobol_dir.rglob("*")):
            if f.is_file() and f.suffix.lower() in _SOURCE_SUFFIXES:
                zf.writestr(f.relative_to(cobol_dir).as_posix(), f.read_bytes())
    return buf.getvalue()


def _await(run_id: str, timeout_s: float = 900.0) -> dict:
    deadline = time.monotonic() + timeout_s
    while True:
        body = client.get(f"/runs/{run_id}").json()
        if body.get("stage") in ("COMPLETED", "FAILED"):
            return body
        if time.monotonic() > deadline:
            return {**body, "harness_timeout": True}
        time.sleep(3)


def run_app(name: str, cobol_dir: Path) -> dict:
    rec: dict = {"app": name}
    rec["target_runtime"] = TARGET
    resp = client.post("/applications", json={
        "name": f"e2e-{name}", "workload_id": f"e2e-{name}", "target_runtime": TARGET,
    })
    app_id = resp.json()["id"]
    resp = client.post(
        f"/applications/{app_id}/ingest",
        files=[("file", (f"{name}.zip", io.BytesIO(_zip(cobol_dir)), "application/zip"))],
    )
    rec["ingest_status"] = resp.status_code
    if resp.status_code != 201:
        rec["ingest_error"] = resp.text[:500]
        return rec
    disc = client.get(f"/applications/{app_id}/discovery").json()
    rec["programs"] = [p.get("program_id") for p in disc.get("cobol_programs", [])]
    rec["calls"] = [(e.get("source"), e.get("target")) for e in disc.get("call_dependencies", [])]
    resp = client.post(f"/applications/{app_id}/modernize")
    rec["modernize_status"] = resp.status_code
    if resp.status_code != 202:
        rec["modernize_error"] = resp.text[:500]
        return rec
    run_id = resp.json()["run_id"]
    run = _await(run_id)
    rec["stage"] = run.get("stage")
    rec["error"] = (run.get("error") or "")[:800]
    rec["timeout"] = run.get("harness_timeout", False)
    v = client.get(f"/runs/{run_id}/verdict")
    if v.status_code == 200:
        vj = v.json()
        rec["verdict"] = vj.get("state")
        rec["comparisons"] = [
            {"type": c.get("artifact_type"), "comparator": c.get("comparator_id"),
             "result": c.get("result"), "diff": json.dumps(c.get("differences"))[:300]}
            for c in vj.get("comparisons", [])
        ]
        rec["verdict_differences"] = json.dumps(vj.get("differences"))[:600]
    else:
        rec["verdict_http"] = v.status_code
    rec_run = store.get_run(run_id)
    app_rec = store.get_application(app_id)
    rec["entry"] = getattr(app_rec, "generated_entrypoint", None)
    rec["generated_app_path"] = getattr(app_rec, "generated_app_path", None)
    report = (rec_run.modernization_report or {}) if rec_run else {}
    rec["limitations"] = list(report.get("limitations", []))[:10]
    return rec


def main() -> None:
    done = set()
    if OUT.exists():
        done = {json.loads(line)["app"] for line in OUT.read_text().splitlines() if line.strip()}
    wanted = [s for s in os.environ.get("E2E_APPS", "").split(",") if s]
    apps = sorted(p.parent for p in (REPO / "fixtures").glob("*/cobol"))
    for cobol_dir in [p / "cobol" for p in apps]:
        name = cobol_dir.parent.name
        if name in done or (wanted and name not in wanted):
            continue
        t0 = time.monotonic()
        try:
            rec = run_app(name, cobol_dir)
        except Exception:
            rec = {"app": name, "harness_error": traceback.format_exc()[-1500:]}
        rec["seconds"] = round(time.monotonic() - t0, 1)
        with OUT.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
        print(name, rec.get("stage"), rec.get("verdict"), rec["seconds"], flush=True)


if __name__ == "__main__":
    main()
