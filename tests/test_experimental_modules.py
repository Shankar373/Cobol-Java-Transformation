"""Experimental modules stay out of the product (architecture audit, 2026-11-03).

Owner decision: modules with no production caller are kept but labelled
EXPERIMENTAL. This pins both halves - each carries the label, and nothing in
``api/`` or ``engine/`` imports it except package re-exports and other
experimental modules - so a test-only path cannot quietly become a product
path.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

EXPERIMENTAL = {
    "engine.modernization.modernization_planner",
    "engine.transformation.jcl_spring_boot_adapter",
    "engine.transformation.sql_repository_mapping",
    "engine.sql.repository_model",
    "engine.verification.runtime_catalog",
    "engine.modernization.application_assembler",
    "engine.transformation.producers.internal_native",
    # Labelled in roadmap unit 1 (they were unlabelled but equally unreachable).
    "engine.transformation.producers.opensource4j",
    "engine.sql.db2_sqlite",
    "engine.sql.execution",
    "engine.sql.harness",
}

# Package re-exports keep the public import paths the tests use.
ALLOWED_IMPORTERS = {
    "engine.modernization",               # __init__ re-exports ModernizationPlanner
    "engine.verification",                # __init__ re-exports the catalog
    "engine.transformation.producers",    # __init__ re-exports the producer
}


def _module_name(path: Path) -> str:
    rel = path.relative_to(REPO).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    package = _module_name(path)
    if path.name != "__init__.py":
        package = package.rsplit(".", 1)[0]
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                anchor = package.split(".")
                anchor = anchor[: len(anchor) - (node.level - 1)]
                base = ".".join(anchor + ([base] if base else []))
            found.add(base)
            found.update(f"{base}.{alias.name}" for alias in node.names)
    return found


@pytest.mark.parametrize("module", sorted(EXPERIMENTAL))
def test_experimental_module_is_labelled(module):
    path = REPO / (module.replace(".", "/") + ".py")
    assert path.read_text(encoding="utf-8").startswith(
        '"""EXPERIMENTAL - not wired into the product'), module


def test_no_production_module_imports_an_experimental_one():
    offenders = []
    for root in ("api", "engine"):
        for path in sorted((REPO / root).rglob("*.py")):
            name = _module_name(path)
            if name in EXPERIMENTAL or name in ALLOWED_IMPORTERS:
                continue
            hits = _imports(path) & EXPERIMENTAL
            if hits:
                offenders.append(f"{name} -> {sorted(hits)}")
    # sql_repository_mapping -> repository_model: both experimental (skipped above)
    assert not offenders, offenders
