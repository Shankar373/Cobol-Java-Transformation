#!/usr/bin/env python3
"""Build a release dependency manifest (stdlib only, no network).

Answers: "What exact dependencies are contained in this release?"

Reads (all local, all committed):
  * requirements.lock            (pinned Python deps)
  * frontend/package.json + package-lock.json (npm deps)
  * Dockerfile.production / Dockerfile.maven-offline / Dockerfile.gnucobol
  * docker-compose.production.yml (nginx image)
  * .github/workflows/ci.yml + supply-chain.yml (action pins)
  * .python-version / .nvmrc      (runtime pins)
  * git HEAD SHA                  (best effort; "UNKNOWN" when unavailable)

Usage:
  python scripts/supply-chain/build_release_manifest.py --output <path>

Exit code is always 0 on success; missing optional files degrade to
"UNKNOWN" entries rather than failing the release job.
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def parse_lock(text: str) -> list[str]:
    out: list[str] = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        out.append(line)
    return out


def parse_npm_package_lock() -> dict:
    """Return {name: version} for packages/ root + packages."" if parseable."""
    result: dict = {"packages": {}, "lockfileVersion": "UNKNOWN"}
    lock_path = ROOT / "frontend" / "package-lock.json"
    text = read_text(lock_path)
    if text is None:
        return result
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return result
    result["lockfileVersion"] = str(data.get("lockfileVersion", "UNKNOWN"))
    result["name"] = str(data.get("name", "UNKNOWN"))
    result["version"] = str(data.get("version", "UNKNOWN"))
    pkgs = data.get("packages") or {}
    # packages[""] is the root project; keep only real deps to stay small.
    interesting = {}
    for key, val in pkgs.items():
        if not key:
            continue
        if key.startswith("node_modules/") and key.count("/") == 1:
            name = key.split("/", 1)[1]
            if isinstance(val, dict) and val.get("version"):
                interesting[name] = str(val["version"])
    result["packages"] = interesting
    # root declared deps for cross-check
    root = pkgs.get("", {})
    result["rootDependencies"] = dict(root.get("dependencies", {})) if isinstance(root, dict) else {}
    result["rootDevDependencies"] = dict(root.get("devDependencies", {})) if isinstance(root, dict) else {}
    return result


def parse_from_images() -> dict:
    images: dict[str, str] = {}
    for name in ("Dockerfile.production", "Dockerfile.maven-offline", "Dockerfile.gnucobol"):
        text = read_text(ROOT / name)
        found = []
        if text:
            for line in text.splitlines():
                m = re.match(r"\s*FROM\s+(\S+)", line, re.IGNORECASE)
                if m:
                    found.append(m.group(1))
        images[name] = found[0] if found else "UNKNOWN"
    compose = read_text(ROOT / "docker-compose.production.yml") or ""
    nginx = re.search(r"image:\s*(nginx:\S+)", compose)
    images["compose:nginx"] = nginx.group(1) if nginx else "UNKNOWN"
    return images


def parse_action_pins() -> dict:
    pins: dict[str, list[str]] = {}
    for wf in ("ci.yml", "supply-chain.yml"):
        text = read_text(ROOT / ".github" / "workflows" / wf) or ""
        uses = sorted(set(re.findall(r"uses:\s*(\S+)", text)))
        pins[wf] = uses
    return pins


def python_version_pin() -> str:
    direct = (read_text(ROOT / ".python-version") or "").strip()
    if direct:
        return direct
    # .python-version is git-ignored in this repo; fall back to the CI pin.
    for wf in ("supply-chain.yml", "ci.yml"):
        text = read_text(ROOT / ".github" / "workflows" / wf) or ""
        m = re.search(r"python-version:\s*['\"]?([\d.]+)['\"]?", text)
        if m:
            return f"{m.group(1)} (CI pin; .python-version git-ignored)"
    return "UNKNOWN"


def git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(ROOT),
        )
        sha = (out.stdout or "").strip()
        return sha if re.fullmatch(r"[0-9a-f]{40}", sha) else "UNKNOWN"
    except Exception:
        return "UNKNOWN"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    lock_text = read_text(ROOT / "requirements.lock")
    pkg_json_text = read_text(ROOT / "frontend" / "package.json")
    try:
        pkg_json = json.loads(pkg_json_text) if pkg_json_text else {}
    except json.JSONDecodeError:
        pkg_json = {"_parseError": True}

    manifest = {
        "schemaVersion": 1,
        "generatedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "gitSha": git_sha(),
        "python": {
            "versionPin": python_version_pin(),
            "lockFile": "requirements.lock",
            "pinned": parse_lock(lock_text or ""),
        },
        "frontend": {
            "nodePin": (read_text(ROOT / ".nvmrc") or "").strip() or "UNKNOWN",
            "packageJson": {
                "dependencies": dict(pkg_json.get("dependencies", {})),
                "devDependencies": dict(pkg_json.get("devDependencies", {})),
            },
            "packageLock": parse_npm_package_lock(),
        },
        "containers": parse_from_images(),
        "githubActions": parse_action_pins(),
        "notes": [
            "requirements.txt keeps compatible ranges; requirements.lock is the release pin.",
            "Spring Boot 3.2.5 (generator-emitted) intentionally unchanged; see DEPENDENCY_AUDIT.md.",
            "Java runtime digest is enforced in engine code (DockerSpringBootConfig.runtime_digest); "
            "updating it requires engine-scope approval and is out of scope for workstream-5.",
        ],
    }

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out_path} ({len(manifest['python']['pinned'])} python pins, "
          f"{len(manifest['frontend']['packageLock'].get('packages', {}))} npm packages)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
