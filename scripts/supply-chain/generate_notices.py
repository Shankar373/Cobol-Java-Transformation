"""Regenerate the shipped-dependency tables in docs/THIRD_PARTY_NOTICES.md.

Usage::

    python scripts/supply-chain/generate_notices.py          # rewrite (needs pypi.org)
    python scripts/supply-chain/generate_notices.py --check  # offline drift check

The tables list every package that ships: the whole ``requirements.lock``
closure (the production image installs exactly that) and every non-dev
package in ``frontend/package-lock.json`` (what the built SPA bundles).
Python licenses come from PyPI metadata for the pinned version; npm
licenses from the lockfile. ``--check`` fails when a locked package is
missing from the tables or listed at another version (audit CI-F7).
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
NOTICES = REPO / "docs" / "THIRD_PARTY_NOTICES.md"
BEGIN = "<!-- BEGIN GENERATED: scripts/supply-chain/generate_notices.py -->"
END = "<!-- END GENERATED -->"
_PIN = re.compile(r"^([A-Za-z0-9_.-]+)(?:\[[^\]]*\])?==([A-Za-z0-9_.+!-]+)\s*(;[^\\]*)?")
_ROW = re.compile(r"^\| `([^`]+)` \| ([^ |]+) \|", re.M)


def python_packages() -> list[tuple[str, str, str]]:
    found = {}
    for line in (REPO / "requirements.lock").read_text(encoding="utf-8").splitlines():
        match = _PIN.match(line)
        if match:
            marker = (match.group(3) or "").lstrip(";").strip()
            found[match.group(1).lower()] = (match.group(1), match.group(2), marker)
    return sorted(found.values(), key=lambda p: p[0].lower())


def npm_packages() -> list[tuple[str, str, str]]:
    lock = json.loads((REPO / "frontend" / "package-lock.json").read_text(encoding="utf-8"))
    out = []
    for path, meta in lock.get("packages", {}).items():
        if not path or meta.get("dev") or meta.get("devOptional"):
            continue
        name = path.split("node_modules/")[-1]
        out.append((name, meta["version"], meta.get("license", "UNKNOWN")))
    return sorted(set(out))


def _pypi_license(name: str, version: str) -> str:
    url = f"https://pypi.org/pypi/{name}/{version}/json"
    with urllib.request.urlopen(url, timeout=60) as response:
        info = json.load(response)["info"]
    if info.get("license_expression"):
        return info["license_expression"]
    classifiers = [c.split(" :: ")[-1] for c in info.get("classifiers", [])
                   if c.startswith("License :: OSI Approved :: ")]
    if classifiers:
        return " / ".join(classifiers)
    text = (info.get("license") or "").strip().splitlines()
    return text[0][:60] if text else "UNKNOWN"


def render() -> str:
    lines = [BEGIN, "", "### Python (production image: `requirements.lock`)", "",
             "| Package | Version | License | Platform |", "|---|---|---|---|"]
    for name, version, marker in python_packages():
        lines.append(f"| `{name}` | {version} | {_pypi_license(name, version)} | {marker or 'all'} |")
    lines += ["", "### Frontend (bundled into the SPA: non-dev `frontend/package-lock.json`)", "",
              "| Package | Version | License |", "|---|---|---|"]
    for name, version, license_ in npm_packages():
        lines.append(f"| `{name}` | {version} | {license_} |")
    lines += ["", END]
    return "\n".join(lines)


def check() -> list[str]:
    text = NOTICES.read_text(encoding="utf-8")
    if BEGIN not in text or END not in text:
        return ["generated section missing"]
    listed = dict(_ROW.findall(text[text.index(BEGIN):text.index(END)]))
    problems = []
    for name, version, _ in python_packages() + npm_packages():
        if listed.get(name) != version:
            problems.append(f"{name}=={version} (notices: {listed.get(name)})")
    return problems


def main() -> int:
    if "--check" in sys.argv:
        problems = check()
        for problem in problems:
            print(f"THIRD_PARTY_NOTICES out of date: {problem}")
        return 1 if problems else 0
    text = NOTICES.read_text(encoding="utf-8")
    start, end = text.index(BEGIN), text.index(END) + len(END)
    NOTICES.write_text(text[:start] + render() + text[end:], encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
