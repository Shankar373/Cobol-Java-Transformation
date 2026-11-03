"""Add ``--hash`` entries to a pinned requirements file (pip ``--require-hashes``).

Usage::

    python scripts/supply-chain/hash_requirements_lock.py requirements.lock

Every ``name==version`` line (an environment marker after ``;`` is kept)
gets the sha256 of every file PyPI publishes for that version, so the lock
installs on every platform (CI and the production image are Linux,
development hosts may be Windows).  Lines that already carry hashes and
comments are left as they are.  Needs network access to pypi.org.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

_PIN = re.compile(r"([A-Za-z0-9_.-]+)(\[[^\]]*\])?==([A-Za-z0-9_.+!-]+)\s*(;.*)?")


def _hashes(name: str, version: str) -> list[str]:
    url = f"https://pypi.org/pypi/{name}/{version}/json"
    with urllib.request.urlopen(url, timeout=60) as response:
        data = json.load(response)
    hashes = sorted({item["digests"]["sha256"] for item in data["urls"]})
    if not hashes:
        raise SystemExit(f"PyPI lists no files for {name}=={version}")
    return hashes


def main(path: str) -> int:
    lock = Path(path)
    lines = lock.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        nxt = lines[index + 1].strip() if index + 1 < len(lines) else ""
        match = _PIN.fullmatch(stripped.rstrip("\\").strip())
        if not match or stripped.endswith("\\") or nxt.startswith("--hash"):
            out.append(line)
            continue
        hashes = _hashes(match.group(1), match.group(3))
        out.append(f"{stripped} \\")
        out.extend(
            f"    --hash=sha256:{h}" + (" \\" if i < len(hashes) - 1 else "")
            for i, h in enumerate(hashes)
        )
    lock.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "requirements.lock"))
