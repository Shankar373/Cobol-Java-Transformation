"""Phase 4 — security and production-readiness fixes (2026-11-02).

One test class per finding of the Phase 4 audit
(``docs/reports/PHASE4_SECURITY_PRODUCTION_READINESS.md``).  Docker-free
except the sandbox symlink exploit, which runs real COBOL on the GnuCOBOL
oracle image (Docker lane).
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _symlink_or_skip(target: Path, link: Path, *, is_dir: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=is_dir)
    except (OSError, NotImplementedError) as exc:  # Windows without privilege
        pytest.skip(f"cannot create symlinks here: {exc}")


# ---------------------------------------------------------------------------
# P1: the host never follows links a sandbox leaves behind
# ---------------------------------------------------------------------------

class TestSandboxOutputIsReadWithoutFollowingLinks:
    def test_regular_files_are_collected(self, tmp_path):
        from engine.execution.workspace_files import collect_generated_files

        out = tmp_path / "out"
        ws = tmp_path / "ws"
        (ws / "sub").mkdir(parents=True)
        out.mkdir()
        (out / "REPORT.TXT").write_bytes(b"A\n")
        (ws / "sub" / "IDX.DAT").write_bytes(b"B")
        (ws / "src").mkdir()
        (ws / "src" / "PROG.cob").write_bytes(b"skipped mount")
        files = collect_generated_files(out, ws, ("src",))
        assert files == {"REPORT.TXT": b"A\n", "workspace/sub/IDX.DAT": b"B"}

    def test_symlinked_file_fails_closed(self, tmp_path):
        from engine.execution.workspace_files import (
            UnsafeSandboxOutput,
            collect_generated_files,
        )

        secret = tmp_path / "secret.env"
        secret.write_text("CONTROL_PLANE_API_TOKEN=leak")
        out = tmp_path / "out"
        out.mkdir()
        _symlink_or_skip(secret, out / "x")
        with pytest.raises(UnsafeSandboxOutput, match="symbolic link"):
            collect_generated_files(out, None)

    def test_symlinked_directory_fails_closed(self, tmp_path):
        from engine.execution.workspace_files import (
            UnsafeSandboxOutput,
            collect_generated_files,
        )

        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "db").write_bytes(b"sqlite")
        ws = tmp_path / "ws"
        ws.mkdir()
        _symlink_or_skip(outside, ws / "d", is_dir=True)
        with pytest.raises(UnsafeSandboxOutput, match="symbolic link"):
            collect_generated_files(tmp_path / "none", ws)

    def test_oversized_file_fails_closed(self, tmp_path):
        from engine.execution.workspace_files import UnsafeSandboxOutput, read_sandbox_file

        big = tmp_path / "big"
        big.write_bytes(b"x" * 11)
        assert read_sandbox_file(big, limit=11) == b"x" * 11
        with pytest.raises(UnsafeSandboxOutput, match="limit 10"):
            read_sandbox_file(big, limit=10)

    def test_total_output_is_bounded(self, tmp_path, monkeypatch):
        import engine.execution.workspace_files as wf

        out = tmp_path / "out"
        out.mkdir()
        for name in "abc":
            (out / name).write_bytes(b"x" * 4)
        monkeypatch.setattr(wf, "MAX_SANDBOX_TOTAL_BYTES", 10)
        with pytest.raises(wf.UnsafeSandboxOutput, match="in total"):
            wf.collect_generated_files(out, None)

    def test_every_lane_reads_through_the_safe_reader(self):
        # The oracle diagnostics and the Maven/javac read-backs were
        # ``read_bytes()`` on container-writable paths.
        oracle = (REPO / "engine/oracle/docker_adapter.py").read_text(encoding="utf-8")
        assert 'read_sandbox_file(diagnostics_dir / "stdout")' in oracle
        assert '(diagnostics_dir / "stdout").read_bytes()' not in oracle
        spring = (REPO / "engine/candidate/docker_spring_boot_adapter.py").read_text(encoding="utf-8")
        assert "jar_bytes = read_sandbox_file(jar)" in spring
        javac = (REPO / "engine/candidate/docker_java_adapter.py").read_text(encoding="utf-8")
        assert "class_files[str(rel)] = read_sandbox_file(f)" in javac


_SYMLINK_COBOL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. LEAK.
       PROCEDURE DIVISION.
           CALL "SYSTEM" USING
               "ln -s /etc/passwd /workspace/output/leak"
           DISPLAY "DONE"
           STOP RUN.
"""


@pytest.mark.docker
def test_cobol_planting_a_symlink_fails_closed(tmp_path):
    """Real exploit: the program links /etc/passwd into its output mount.
    The oracle run fails (named reason) and no file content is captured."""
    import uuid

    from engine.domain.identities import RunId
    from engine.oracle.adapter import OracleAdapterConfig
    from engine.oracle.docker_adapter import DockerOracleAdapter

    src = tmp_path / "src"
    src.mkdir()
    (src / "LEAK.cob").write_text(_SYMLINK_COBOL, encoding="utf-8")
    oracle = DockerOracleAdapter(OracleAdapterConfig(
        oracle_id="phase4-symlink", image_digest="", compiler_version="3.1.2.0",
    ))
    result = oracle.execute(
        run_id=RunId(value=f"phase4-{uuid.uuid4().hex[:8]}"),
        source_path=str(src), entry_program="LEAK",
    )
    assert result.status.value == "FAILED", result
    # Linux hosts see the link itself; a Windows host sees a reparse point
    # it cannot stat - refused either way, naming the file, not its target.
    assert re.search(rb"symbolic link|without following links", result.stderr), result.stderr
    assert b"sandbox output 'leak'" in result.stderr
    assert b"root:" not in (result.stdout + result.stderr)


# ---------------------------------------------------------------------------
# P1: the generated bundle lives in the durable output directory
# ---------------------------------------------------------------------------

_HELLO = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HELLO.
       PROCEDURE DIVISION.
           DISPLAY "HI"
           STOP RUN.
"""


@pytest.mark.parametrize("target", ["spring_boot", "plain_java", "quarkus"])
def test_generated_project_is_created_inside_output_dir(tmp_path, target):
    from engine.modernization.pipeline import (
        ModernizationConfig,
        UniversalModernizationPipeline,
    )

    src = tmp_path / "src"
    src.mkdir()
    (src / "HELLO.cob").write_text(_HELLO, encoding="utf-8")
    out = tmp_path / "durable-output"
    report = UniversalModernizationPipeline(ModernizationConfig(
        source_dir=str(src), output_dir=str(out), application_id="p4",
        entrypoint="HELLO", docker_available=True, target_runtime=target,
    )).execute()
    assert report.generation_success, report.generation_errors
    project = Path(report.generated_project_dir).resolve()
    assert project.parent == out.resolve()
    assert project.name.startswith("pipeline-")
    assert Path(tempfile.gettempdir()).resolve() not in project.parents or (
        out.resolve() in project.parents
    )


# ---------------------------------------------------------------------------
# P2: client-visible errors carry no server paths or raw exception text
# ---------------------------------------------------------------------------

class TestClientVisibleErrors:
    def test_api_errors_pass_through_others_are_generic(self):
        from api.errors import ServiceError
        from api.service import _public_run_error

        assert _public_run_error(ServiceError("No source"), "run-1") == "No source"
        text = _public_run_error(OSError("/app/workspaces/x: denied"), "run-1")
        assert "/app" not in text and "OSError" in text and "run-1" in text

    def test_discovery_messages_name_files_relative_to_the_upload(self, tmp_path):
        from api.ingestion import _without_root

        msg = f"cannot parse {tmp_path / 'src' / 'A.cob'} under {tmp_path}"
        cleaned = _without_root(msg, tmp_path)
        assert str(tmp_path) not in cleaned
        assert "A.cob" in cleaned

    def test_extraction_failure_hides_the_os_error_text(self, tmp_path, monkeypatch):
        import io
        import zipfile

        import api.ingestion as ingestion

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("A.cob", "x")

        def _boom(*args, **kwargs):
            raise PermissionError(13, "denied", "/srv/secret/layout")

        monkeypatch.setattr(ingestion.shutil, "copyfileobj", _boom, raising=False)
        monkeypatch.setattr("builtins.open", _boom)
        with pytest.raises(ingestion.IngestionError) as excinfo:
            ingestion.ingest_zip(buf.getvalue(), "app-1")
        assert "/srv/secret" not in str(excinfo.value)
        assert "PermissionError" in str(excinfo.value)


class TestProductionWithholdsServerPaths:
    def test_paths_under_server_roots_become_server_relative(self, tmp_path, monkeypatch):
        import api.app as app_module

        root = tmp_path / "workspaces"
        monkeypatch.setenv("CONTROL_PLANE_WORKSPACE_DIR", str(root))
        monkeypatch.setenv("CONTROL_PLANE_ENV", "production")
        value = {"generated_app_path": str(root / "pipeline-output-1" / "pipeline-x"),
                 "programs": [{"source_path": str(root / "ingest" / "A.cob")}]}
        public = app_module._public(value)
        flat = repr(public)
        assert str(root) not in flat and root.as_posix() not in flat
        assert "<server>" in public["generated_app_path"]
        assert public["programs"][0]["source_path"].endswith("A.cob")

    def test_development_keeps_real_paths(self, tmp_path, monkeypatch):
        import api.app as app_module

        monkeypatch.delenv("CONTROL_PLANE_ENV", raising=False)
        assert app_module._public(str(tmp_path)) == str(tmp_path)


# ---------------------------------------------------------------------------
# P2/P3: probes, 401s, docs, audit events
# ---------------------------------------------------------------------------

_TOKEN = "t" * 40


@pytest.fixture
def production_client(monkeypatch):
    from fastapi.testclient import TestClient

    import api.app as app_module

    monkeypatch.setenv("CONTROL_PLANE_ENV", "production")
    monkeypatch.setenv("CONTROL_PLANE_API_TOKEN", _TOKEN)
    return TestClient(app_module.app)


class TestProbesAndAuthResponses:
    def test_anonymous_ready_reports_booleans_only(self, production_client):
        body = production_client.get("/ready").json()
        assert set(body["checks"]) == {"database", "workspace", "staging", "docker"}
        for check in body["checks"].values():
            assert set(check) == {"ok"}

    def test_authenticated_ready_keeps_details(self, production_client):
        body = production_client.get(
            "/ready", headers={"Authorization": f"Bearer {_TOKEN}"}
        ).json()
        assert "detail" in body["checks"]["database"]
        assert "jobs" in body["checks"]

    def test_401_carries_security_headers_and_is_audited(self, production_client, caplog):
        with caplog.at_level(logging.WARNING, logger="api.app"):
            response = production_client.get(
                "/applications", headers={"Authorization": "Bearer wrong"}
            )
        assert response.status_code == 401
        assert response.headers["X-Frame-Options"] == "DENY"
        assert "no-store" in response.headers["Cache-Control"]
        events = [r for r in caplog.records if getattr(r, "event", "") == "auth.failed"]
        assert events and events[0].credential_presented is True
        assert "wrong" not in caplog.text

    def test_docs_are_not_served_in_production(self):
        code = (
            "import os;os.environ['CONTROL_PLANE_ENV']='production';"
            f"os.environ['CONTROL_PLANE_API_TOKEN']='{_TOKEN}';"
            "os.environ['SYSTEMAOPS_ORACLE_DIGEST']='sha256:' + 'a' * 64;"
            "from fastapi.testclient import TestClient;import api.app as a;"
            "c=TestClient(a.app);h={'Authorization':'Bearer " + _TOKEN + "'};"
            "print(c.get('/docs',headers=h).status_code,"
            "c.get('/openapi.json',headers=h).status_code)"
        )
        proc = subprocess.run([sys.executable, "-c", code], cwd=REPO,
                              capture_output=True, text=True, timeout=120)
        assert proc.stdout.split()[-2:] == ["404", "404"], proc.stderr[-2000:]


class TestApprovalAuditTrail:
    def test_decisions_and_resets_are_appended(self):
        from api.models import RunStage
        from api.store import ApplicationRecord, RunRecord, Store

        store = Store()
        store.add_application(ApplicationRecord(
            id="app-1", name="a", description="", workload_id="w",
            java_entrypoint="Main",
        ))
        store.add_run(RunRecord(
            id="run-1", application_id="app-1", workload_id="w",
            stage=RunStage.COMPLETED,
        ))
        store.set_run_approval("run-1", state="REJECTED", approver="qa", reason="r1")
        store.set_run_approval("run-1", state="APPROVED", approver="cfo", reason="ok")
        store.begin_revalidation("run-1", certification_contract="c")
        history = store.approval_history("run-1")
        assert [h["state"] for h in history] == ["REJECTED", "APPROVED", "RESET"]
        assert history[0]["approver"] == "qa" and history[1]["approver"] == "cfo"


# ---------------------------------------------------------------------------
# P3: input bounds, log lines
# ---------------------------------------------------------------------------

class TestInputBounds:
    @pytest.mark.parametrize("value", ["Main", "FILE-WRITE-READ", "com.acme.Main"])
    def test_entrypoint_names_accepted(self, value):
        from api.models import ApplicationCreate

        ApplicationCreate(name="n", workload_id="w", java_entrypoint=value)

    @pytest.mark.parametrize("value", ["a;rm -rf /", "$(id)", "x y", "`id`", "a|b"])
    def test_entrypoint_shell_syntax_rejected(self, value):
        from pydantic import ValidationError

        from api.models import ApplicationCreate

        with pytest.raises(ValidationError):
            ApplicationCreate(name="n", workload_id="w", java_entrypoint=value)

    def test_free_text_fields_are_bounded(self):
        from pydantic import ValidationError

        from api.models import ApplicationCreate, ApprovalRequest

        with pytest.raises(ValidationError):
            ApplicationCreate(name="n", workload_id="w", description="d" * 4097)
        with pytest.raises(ValidationError):
            ApprovalRequest(decision="APPROVED", approver="")
        with pytest.raises(ValidationError):
            ApprovalRequest(decision="APPROVED", approver="a", reason="r" * 4097)


@pytest.mark.parametrize("name", ["A\x00.cob", "src/B\n.cob", "PROG.cob:stream"])
def test_upload_names_with_control_characters_or_streams_are_rejected(name):
    from api.errors import ServiceError
    from api.service import _safe_relative_path

    with pytest.raises(ServiceError):
        _safe_relative_path(name)


def test_text_log_lines_cannot_be_forged():
    from api.logging_config import TextFormatter

    record = logging.LogRecord("x", logging.INFO, "p", 1, "path %s", ("/a\nFAKE ERROR",), None)
    line = TextFormatter("%(message)s").format(record)
    assert "\n" not in line and "\\nFAKE ERROR" in line


def test_ingest_counts_against_the_job_limit(monkeypatch):
    from api.errors import BusyError
    from api.service import Service
    from api.store import Store

    monkeypatch.setenv("CONTROL_PLANE_MAX_CONCURRENT_JOBS", "1")
    service = Service(Store())
    service._acquire_job_slot()  # a running job holds the only slot
    with pytest.raises(BusyError):
        service.ingest_application("app-x", b"PK", "a.zip")
    assert service.job_slots() == (1, 1)  # ingest released nothing it did not take


# ---------------------------------------------------------------------------
# Supply chain and deployment configuration
# ---------------------------------------------------------------------------

class TestSupplyChainConfiguration:
    @staticmethod
    def _pins(lock: str) -> dict[str, str]:
        text = (REPO / lock).read_text(encoding="utf-8")
        blocks = re.split(r"^(?=[A-Za-z0-9_.\[\]-]+==)", text, flags=re.M)[1:]
        for block in blocks:
            assert "--hash=sha256:" in block, (lock, block.splitlines()[0])
        return {b.split("==")[0].lower(): b.split()[0] for b in blocks}

    @pytest.mark.parametrize("lock,minimum", [("requirements.lock", 20),
                                              ("requirements-dev.lock", 30)])
    def test_every_python_pin_is_hashed(self, lock, minimum):
        assert len(self._pins(lock)) >= minimum

    def test_runtime_lock_holds_no_test_tooling(self):
        # Audit D4 (owner decision): the production image installs the
        # runtime lock only; test tooling lives in the dev lock.
        runtime = self._pins("requirements.lock")
        dev = self._pins("requirements-dev.lock")
        for tool in ("pytest", "httpx", "pytest-asyncio", "iniconfig", "pluggy"):
            assert tool not in runtime, tool
        assert "pytest-asyncio" not in dev  # unused, dropped
        for name, pin in runtime.items():   # dev = runtime + tooling, same pins
            assert dev.get(name) == pin, (name, pin, dev.get(name))

    def test_installs_require_hashes(self):
        assert "--require-hashes -r /app/requirements.lock" in (
            REPO / "Dockerfile.production").read_text(encoding="utf-8")
        lock = re.compile(r"requirements(-dev)?\.lock")
        for wf in sorted(p.name for p in (REPO / ".github/workflows").glob("*.yml")):
            text = (REPO / ".github/workflows" / wf).read_text(encoding="utf-8")
            for line in text.splitlines():
                if "pip install" in line and lock.search(line):
                    assert "--require-hashes" in line, (wf, line)
                if "pip install" in line and not lock.search(line):
                    assert "==" in line, (wf, line)  # tools pinned too

    def test_checkouts_do_not_persist_credentials(self):
        import yaml

        for wf in sorted(p.name for p in (REPO / ".github/workflows").glob("*.yml")):
            data = yaml.safe_load((REPO / ".github/workflows" / wf).read_text(encoding="utf-8"))
            for job in data["jobs"].values():
                for step in job["steps"]:
                    if "actions/checkout" in step.get("uses", ""):
                        assert step["with"]["persist-credentials"] is False
                    if "uses" in step:
                        assert re.search(r"@[0-9a-f]{40}\b", step["uses"]), step["uses"]

    def test_maven_precache_uses_strict_checksums(self):
        text = (REPO / "Dockerfile.maven-offline").read_text(encoding="utf-8")
        builds = re.findall(r"mvn -B[^\n]*go-offline", text)
        assert len(builds) == 2 and all(" -C " in b for b in builds)

    def test_image_scan_is_pinned_by_digest(self):
        text = (REPO / ".github/workflows/supply-chain.yml").read_text(encoding="utf-8")
        assert re.search(r"aquasec/trivy@sha256:[0-9a-f]{64}", text)


class TestDeploymentConfiguration:
    def test_production_image_fails_closed_by_default(self):
        text = (REPO / "Dockerfile.production").read_text(encoding="utf-8")
        assert "ENV CONTROL_PLANE_ENV=production" in text

    def test_production_image_drops_packaging_tools(self):
        # wheel / setuptools (vendored jaraco.context) carried CVEs and are
        # not used at runtime (first image scan, Phase 4).
        text = (REPO / "Dockerfile.production").read_text(encoding="utf-8")
        assert "pip uninstall -y --no-cache-dir setuptools wheel" in text

    def test_docker_group_has_no_root_default(self):
        text = (REPO / "docker-compose.production.yml").read_text(encoding="utf-8")
        assert "${DOCKER_GID:-0}" not in text
        assert "${DOCKER_GID:?" in text

    def test_every_compose_entry_point_resolves_docker_gid(self):
        # Compose interpolates the required DOCKER_GID on every command
        # (config/ps/up/down): a script that calls compose without resolving
        # it aborts - rollback and restore did (Phase 5 audit).
        for script in sorted((REPO / "scripts").rglob("*.sh")):
            if script.name == "lib-docker-gid.sh":
                continue  # the helper itself
            text = script.read_text(encoding="utf-8")
            if "docker compose" in text and "docker-compose.production.yml" in text:
                assert "resolve_docker_gid" in text, script.name
                assert text.index("resolve_docker_gid") < text.index("docker compose"), script.name

    def test_nginx_rate_limits_writes(self):
        text = (REPO / "deployment/nginx/systemaops.conf").read_text(encoding="utf-8")
        assert "limit_req zone=control_plane_writes" in text
        assert "limit_req_status 429;" in text

    def test_backup_and_rollback_files_are_owner_only(self):
        assert "umask 077" in (REPO / "scripts/backup/backup.sh").read_text(encoding="utf-8")
        assert "umask 077" in (REPO / "scripts/deploy/rollback.sh").read_text(encoding="utf-8")

    def test_independent_verifier_runs_hardened(self):
        text = (REPO / "scripts/e2e/verify_independent.py").read_text(encoding="utf-8")
        for flag in ('"--cap-drop", "ALL"', '"--user", "10001:10001"',
                     '"--network", "none"', '"no-new-privileges=true"'):
            assert flag in text
        assert 'docker(["run"' not in text
