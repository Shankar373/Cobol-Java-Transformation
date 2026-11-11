#!/usr/bin/env python3
"""End-to-end check of a deployed stack over HTTPS: auth, explicit runtime selection, upload, modernize, verdict, download.

stdlib only; verifies TLS against --ca (never disables verification).

    python3 scripts/deploy/staging_e2e.py --base https://127.0.0.1:8443 --token-file ~/stage/token \
        --ca deployment/tls/fullchain.pem --cobol-dir fixtures/workload-balance-check/cobol --runtime quarkus

Exit 0 only when every step passed. Prints one line per step.
"""

from __future__ import annotations

import argparse
import io
import json
import ssl
import sys
import time
import urllib.error
import urllib.request
import uuid
import zipfile
from pathlib import Path

FAILS: list[str] = []


def step(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}: {name}" + (f"  [{detail}]" if detail else ""))
    if not ok:
        FAILS.append(name)


class Client:
    def __init__(self, base: str, token: str | None, ca: str) -> None:
        self.base, self.token = base.rstrip("/"), token
        self.ctx = ssl.create_default_context(cafile=ca)

    def call(self, method: str, path: str, body: bytes | None = None, headers: dict | None = None, auth: bool = True):
        req = urllib.request.Request(self.base + path, data=body, method=method, headers=dict(headers or {}))
        if auth and self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(req, context=self.ctx, timeout=120) as resp:  # noqa: S310 - https base only
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    def json(self, method: str, path: str, payload: dict | None = None, auth: bool = True):
        body = json.dumps(payload).encode() if payload is not None else None
        status, raw = self.call(method, path, body, {"Content-Type": "application/json"} if body else None, auth)
        try:
            return status, json.loads(raw or b"null")
        except ValueError:
            return status, raw.decode("utf-8", "replace")


def multipart(field: str, filename: str, data: bytes) -> tuple[bytes, dict]:
    boundary = uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; filename=\"{filename}\"\r\n"
            "Content-Type: application/zip\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()
    return body, {"Content-Type": f"multipart/form-data; boundary={boundary}"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--token-file", required=True)
    ap.add_argument("--ca", required=True)
    ap.add_argument("--cobol-dir", required=True)
    ap.add_argument("--runtime", required=True, choices=["spring_boot", "plain_java", "quarkus", "micronaut"])
    ap.add_argument("--timeout", type=int, default=900)
    args = ap.parse_args()
    token = Path(args.token_file).read_text().strip()
    anon, api = Client(args.base, None, args.ca), Client(args.base, token, args.ca)

    status, _ = anon.json("GET", "/health", auth=False)
    step("GET /health (no token)", status == 200, str(status))
    status, _ = anon.json("GET", "/ready", auth=False)
    step("GET /ready (no token)", status == 200, str(status))
    status, _ = anon.json("GET", "/applications", auth=False)
    step("GET /applications without a token is 401", status == 401, str(status))
    wrong = Client(args.base, "x" * 48, args.ca)
    status, _ = wrong.json("GET", "/applications")
    step("a wrong token is 401", status == 401, str(status))

    status, body = api.json("POST", "/applications", {"name": "e2e", "workload_id": "wl-e2e"})
    step("create without a runtime is rejected (422)", status == 422, str(status))
    status, body = api.json("POST", "/applications", {"name": "e2e", "workload_id": "wl-e2e", "target_runtime": "jakarta_ee"})
    step("create with an uncertified runtime is rejected", status in (400, 422), str(status))
    status, app = api.json("POST", "/applications", {"name": "e2e", "workload_id": "wl-e2e", "target_runtime": args.runtime})
    step(f"create with target_runtime={args.runtime}", status == 201 and app.get("target_runtime") == args.runtime, str(status))
    if status != 201:
        return 1
    app_id = app["id"]

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(Path(args.cobol_dir).rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(args.cobol_dir).as_posix())
    body, headers = multipart("file", "source.zip", buf.getvalue())
    status, raw = api.call("POST", f"/applications/{app_id}/ingest", body, headers)
    step("ingest the COBOL archive", status == 201, f"{status} {raw[:120]!r}" if status != 201 else str(status))
    status, run = api.json("POST", f"/applications/{app_id}/modernize")
    step("start modernization", status == 202, str(status))
    if status != 202:
        return 1
    run_id, deadline = run["run_id"], time.monotonic() + args.timeout
    stage = ""
    while time.monotonic() < deadline:
        _, state = api.json("GET", f"/runs/{run_id}")
        stage = state.get("stage", "")
        if stage in ("COMPLETED", "FAILED"):
            break
        time.sleep(5)
    step("run reaches COMPLETED", stage == "COMPLETED", f"stage={stage} error={state.get('error')}")
    _, detail = api.json("GET", f"/runs/{run_id}/detail")
    print("  verdict_state:", detail.get("verdict_state"), " generated_files:", len(detail.get("generated_files") or []))
    status, verdict = api.json("GET", f"/runs/{run_id}/verdict")
    step("verdict is readable", status == 200, str(status))
    state = verdict.get("state") if isinstance(verdict, dict) else None
    step("the oracle comparison verdict is VERIFIED", state == "VERIFIED", f"state={state}")
    if isinstance(verdict, dict):
        print("  verdict:", json.dumps({k: verdict[k] for k in list(verdict)[:8]}, default=str)[:400])
    status, _ = api.json("GET", f"/applications/{app_id}")
    app_now = _ if isinstance(_, dict) else {}
    step("the application still carries the chosen runtime", app_now.get("target_runtime") == args.runtime)
    status, raw = api.call("GET", f"/runs/{run_id}/download")
    step("download the generated project", status == 200, f"{status} {len(raw)} bytes")
    if status == 200:
        names = zipfile.ZipFile(io.BytesIO(raw)).namelist()
        pom = next((n for n in names if n.endswith("pom.xml")), None)
        text = zipfile.ZipFile(io.BytesIO(raw)).read(pom).decode().lower() if pom else ""
        marker = {"spring_boot": "spring-boot", "quarkus": "quarkus", "micronaut": "micronaut"}
        for rt, word in marker.items():
            step(f"generated project {'is' if rt == args.runtime else 'is not'} {rt}", (word in text) is (rt == args.runtime))
        print("  files:", len(names))
    print("E2E:", "FAILED" if FAILS else "OK", FAILS or "")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
