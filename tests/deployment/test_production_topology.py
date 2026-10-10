"""Production deployment topology tests (Phase E-A: R1 + R8).

Pins the production execution and frontend routing contracts with
stdlib-only parsing (no PyYAML dependency):

R1 — the API container must stage Docker bind sources on a host-visible
bind mount (SANDBOX_STAGING_DIR container view <-> SANDBOX_HOST_STAGING_DIR
host view), because the host daemon resolves `-v` sources on the host
filesystem. The container-private /app/tmp tmpfs and named volumes are
invisible there. Security/resource controls must stay intact and the API
must NOT gain unrestricted Docker privileges.

R8 — nginx must serve the SPA under /app/ (Vite base '/app/'), keep API
routes proxied, fall back to index.html for client navigation, and serve
hashed assets immutably.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
COMPOSE = REPO / "docker-compose.production.yml"
NGINX_CONF = REPO / "deployment" / "nginx" / "systemaops.conf"
VITE_CONFIG = REPO / "frontend" / "vite.config.ts"
ENV_EXAMPLE = REPO / ".env.production.example"
DOCKERFILE = REPO / "Dockerfile.production"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# R1 — production execution topology
# ---------------------------------------------------------------------------


class TestSandboxStagingTopology:
    def test_compose_declares_staging_pair(self):
        text = _read(COMPOSE)
        assert "SANDBOX_STAGING_DIR: /app/sandbox-staging" in text
        assert "SANDBOX_HOST_STAGING_DIR:" in text
        assert "HOST_SANDBOX_STAGING_DIR" in text

    def test_compose_binds_host_staging_dir(self):
        text = _read(COMPOSE)
        assert "${HOST_SANDBOX_STAGING_DIR" in text
        assert "/app/sandbox-staging" in text

    def test_compose_keeps_tmpfs_scratch(self):
        text = _read(COMPOSE)
        assert "/app/tmp:rw,noexec,nosuid" in text

    def test_compose_keeps_resource_caps(self):
        text = _read(COMPOSE)
        assert "mem_limit: 2g" in text
        assert "cpus: 2.0" in text
        assert "pids_limit: 512" in text
        assert "no-new-privileges:true" in text

    def test_compose_grants_no_extra_privileges(self):
        text = _read(COMPOSE)
        assert "privileged: true" not in text
        assert "network_mode:" not in text
        assert "cap_add" not in text

    def test_compose_keeps_network_isolation(self):
        text = _read(COMPOSE)
        assert "--network none" in text  # documented sandbox enforcement

    def test_dockerfile_creates_staging_dir_owned(self):
        text = _read(DOCKERFILE)
        assert "/app/sandbox-staging" in text
        assert "10001:10001" in text

    def test_env_example_documents_host_dir(self):
        text = _read(ENV_EXAMPLE)
        assert "HOST_SANDBOX_STAGING_DIR" in text
        assert "10001" in text

    def test_engine_stages_outside_tmpfs_by_default(self):
        """With production env, the staging root must not be the tmpfs."""
        text = _read(COMPOSE)
        assert "SANDBOX_STAGING_DIR: /app/tmp" not in text
        assert "SANDBOX_STAGING_DIR: /app/sandbox-staging" in text


# ---------------------------------------------------------------------------
# R8 — frontend production routing
# ---------------------------------------------------------------------------


class TestNginxRouting:
    def test_health_bypasses_static(self):
        text = _read(NGINX_CONF)
        assert "location = /health" in text

    def test_root_redirects_to_app(self):
        text = _read(NGINX_CONF)
        assert re.search(r"location\s*=\s*/\s*\{[^}]*return\s+302\s+/app/;", text)

    def test_app_serves_static_with_spa_fallback(self):
        text = _read(NGINX_CONF)
        block = re.search(
            r"location\s+\^~\s+/app/\s*\{(.*?)\n\}", text, re.DOTALL
        )
        assert block is not None, "missing ^~ /app/ static location"
        body = block.group(1)
        assert "alias /usr/share/nginx/html/" in body
        assert "try_files" in body
        assert "/app/index.html" in body

    def test_hashed_assets_cached_immutably(self):
        text = _read(NGINX_CONF)
        block = re.search(
            r"location\s+\^~\s+/app/assets/\s*\{(.*?)\n\}", text, re.DOTALL
        )
        assert block is not None, "missing ^~ /app/assets/ location"
        body = block.group(1)
        assert "immutable" in body

    def test_api_catch_all_proxies(self):
        text = _read(NGINX_CONF)
        block = re.search(r"location\s+/\s*\{(.*?)\n\}", text, re.DOTALL)
        assert block is not None, "missing API catch-all location"
        assert "proxy_pass http://control_plane" in block.group(1)

    def test_static_locations_pin_precedence(self):
        """^~ guarantees static subtrees win over the API catch-all."""
        text = _read(NGINX_CONF)
        assert "location ^~ /app/" in text
        assert "location ^~ /app/assets/" in text


class TestViteBase:
    def test_vite_base_is_app(self):
        text = _read(VITE_CONFIG)
        assert re.search(r"base:\s*['\"]\/app\/['\"]", text), (
            "Vite base must be '/app/' so built assets resolve under "
            "the nginx /app/ subtree"
        )

    def test_no_root_absolute_asset_refs_in_sources(self):
        """Root-absolute /assets/* or /logo.svg bypass /app/ -> API 404."""
        offenders: list[str] = []
        for path in sorted((REPO / "frontend" / "src").rglob("*.tsx")):
            text = path.read_text(encoding="utf-8")
            for match in re.finditer(r'src="/(assets/|logo\.svg)"', text):
                offenders.append(f"{path.relative_to(REPO)}: {match.group(0)}")
        assert offenders == [], f"root-absolute asset refs: {offenders}"

    def test_logo_resolves_through_base_url(self):
        text = _read(REPO / "frontend" / "src" / "components" / "Sidebar.tsx")
        assert "import.meta.env.BASE_URL" in text
        text = _read(REPO / "frontend" / "src" / "components" / "Header.tsx")
        assert "import.meta.env.BASE_URL" in text
