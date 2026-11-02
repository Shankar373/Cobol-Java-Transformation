"""Regenerate docker/maven-precache from the Quarkus / Micronaut runtime adapters.

Usage::

    python scripts/generate_framework_precache.py [--check]

Dockerfile.maven-offline builds each project under docker/maven-precache
online so the offline Maven repository holds every plugin and dependency a
generated framework project builds with.  Each project is exactly what the
adapter emits (pom, entry class, resources) around a no-op ``Precache``
program.  ``--check`` exits 1 when the committed tree differs.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from engine.transformation.runtime_adapters import (  # noqa: E402
    MicronautRuntimeAdapter,
    QuarkusRuntimeAdapter,
)

PRECACHE_DIR = REPO / "docker" / "maven-precache"
_PROGRAM = "Precache"
_PROGRAM_SOURCE = (
    "public class Precache {\n"
    "    public static void main(String[] args) {\n"
    "    }\n"
    "}\n"
)


def expected_files() -> dict[str, str]:
    """Relative path under docker/maven-precache -> content."""
    files: dict[str, str] = {}
    for adapter in (QuarkusRuntimeAdapter(), MicronautRuntimeAdapter()):
        root = adapter.target_runtime
        files[f"{root}/pom.xml"] = adapter._render_pom(
            application_id="precache", entry_class=_PROGRAM, java_version="21"
        )
        files[f"{root}/src/main/java/{_PROGRAM}.java"] = _PROGRAM_SOURCE
        for rel, content in adapter._framework_files(_PROGRAM).items():
            files[f"{root}/{rel}"] = content
    return files


def committed_files() -> dict[str, str]:
    return {
        path.relative_to(PRECACHE_DIR).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(PRECACHE_DIR.rglob("*"))
        if path.is_file()
    }


def main(argv: list[str]) -> int:
    expected = expected_files()
    if "--check" in argv:
        if committed_files() != expected:
            print("docker/maven-precache is out of date: run "
                  "python scripts/generate_framework_precache.py")
            return 1
        return 0
    for rel, content in expected.items():
        target = PRECACHE_DIR / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
    for rel in set(committed_files()) - set(expected):
        (PRECACHE_DIR / rel).unlink()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
