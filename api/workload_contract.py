"""Certification contract resolution for API-driven runs.

A "certification contract" is the set of artifacts a run is certified
against (STDOUT / EXIT_STATUS / TEXT_FILE / FIXED_RECORD / ...) plus their
comparator binding. The API resolves it explicitly for every validation:

1. **Declared contract** — the application's ``workload_id`` is looked up in
   the trusted repository fixture registry ``fixtures/<workload_id>/workload.py``
   (the same registry the verification tooling loads). When a declaration
   exists its artifacts become the certification contract. Fixtures are
   repository-controlled code, never uploaded content, and the workload id is
   validated against a strict character set before any filesystem access.

2. **Default contract** — otherwise the historical STDOUT + EXIT_STATUS
   contract is used, recorded with the explicit id
   ``default:stdout-exit-status`` so clients can see which contract a run was
   certified against instead of a hidden hard-coded assumption.

Fail-closed rules:

* a declared workload that needs staged *inputs* is rejected — the API does
  not stage fixture input files, so certifying it would silently degrade;
* a fixture that exists but cannot be loaded (missing/ambiguous factory,
  import error, wrong return type) is an explicit error, never a silent
  fallback to the default contract.
"""

from __future__ import annotations

import importlib.util
import inspect
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from api.errors import ServiceError
from engine.workload import WorkloadDefinition, WorkloadArtifact

#: Explicit id of the historical fallback contract (stdout + exit status).
DEFAULT_CONTRACT_ID = "default:stdout-exit-status"

#: Artifact types covered by the default contract.
DEFAULT_ARTIFACT_TYPES: tuple[str, ...] = ("STDOUT", "EXIT_STATUS")

_REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_ROOT = _REPO_ROOT / "fixtures"

#: Workload ids are used to build fixture paths — only this character set is
#: accepted before any filesystem access is attempted.
_SAFE_WORKLOAD_ID = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]*$")


@dataclass(frozen=True)
class CertificationContract:
    """Resolved certification contract for one (re)validation."""

    workload_id: str
    contract_id: str
    workload: WorkloadDefinition
    artifact_types: tuple[str, ...]

    @property
    def contract_source(self) -> str:
        """``declared`` for a fixture-backed contract, ``default`` otherwise."""
        if self.contract_id.startswith("declared:"):
            return "declared"
        if self.contract_id.startswith("default:"):
            return "default"
        return "unknown"


def default_contract(
    workload_id: str,
    description: str = "",
) -> CertificationContract:
    """Build the historical STDOUT + EXIT_STATUS contract explicitly."""
    workload = WorkloadDefinition(
        workload_id=workload_id,
        description=description or f"API-driven workload for {workload_id}",
        artifacts=(
            WorkloadArtifact(
                logical_name="stdout",
                artifact_type="STDOUT",
                comparator_id="stdout-exact",
            ),
            WorkloadArtifact(
                logical_name="exit-status",
                artifact_type="EXIT_STATUS",
                comparator_id="exit-status-exact",
            ),
        ),
    )
    return CertificationContract(
        workload_id=workload_id,
        contract_id=DEFAULT_CONTRACT_ID,
        workload=workload,
        artifact_types=DEFAULT_ARTIFACT_TYPES,
    )


def _factory_candidates(workload_id: str) -> tuple[str, ...]:
    exact = f"{workload_id.replace('-', '_')}_workload"
    candidates = [exact]
    if workload_id.startswith("workload_"):
        candidates.append(f"{workload_id[len('workload_'):]}_workload")
    return tuple(candidates)


def _load_declaration_module(workload_id: str, workload_py: Path):
    """Import a trusted fixture declaration module (repository-controlled)."""
    module_name = f"api_fixture_workload_{workload_id.replace('-', '_')}"
    spec = importlib.util.spec_from_file_location(module_name, workload_py)
    if spec is None or spec.loader is None:
        raise ServiceError(
            f"Workload declaration {workload_py.name} for {workload_id!r}"
            " could not be loaded"
        )
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # declaration code failed to import
        raise ServiceError(
            f"Workload declaration for {workload_id!r} failed to import:"
            f" {type(exc).__name__}: {exc}"
        ) from None
    return module


def _find_factory(module, workload_id: str) -> Callable[[], WorkloadDefinition]:
    for name in _factory_candidates(workload_id):
        factory = getattr(module, name, None)
        if callable(factory):
            return factory

    # Convention fallback: a single workload factory defined by this module.
    defined = [
        func
        for name, func in inspect.getmembers(module, inspect.isfunction)
        if name.endswith("_workload") and func.__module__ == module.__name__
    ]
    if len(defined) == 1:
        return defined[0]
    if not defined:
        raise ServiceError(
            f"Workload declaration for {workload_id!r} defines no"
            " '*_workload' factory"
        )
    raise ServiceError(
        f"Workload declaration for {workload_id!r} is ambiguous:"
        f" {len(defined)} '*_workload' factories found"
    )


def load_declared_workload(workload_id: str) -> WorkloadDefinition | None:
    """Return the fixture-declared workload, or ``None`` when undeclared.

    Raises :class:`ServiceError` when a declaration exists but cannot be
    trusted (never falls back to the default contract silently).
    """
    if _SAFE_WORKLOAD_ID.fullmatch(workload_id) is None:
        raise ServiceError(
            f"Workload id {workload_id!r} contains characters that are not"
            " allowed in a fixture reference"
        )

    candidates = [FIXTURES_ROOT / workload_id]
    if not workload_id.startswith("workload-"):
        # Allow a plain id ("payroll") to resolve to the registry
        # directory name ("workload-payroll").
        candidates.append(FIXTURES_ROOT / f"workload-{workload_id}")

    workload_py = next(
        (path / "workload.py" for path in candidates if (path / "workload.py").is_file()),
        None,
    )
    if workload_py is None:
        return None

    module = _load_declaration_module(workload_id, workload_py)
    factory = _find_factory(module, workload_id)
    try:
        declaration = factory()
    except Exception as exc:
        raise ServiceError(
            f"Workload declaration factory for {workload_id!r} raised"
            f" {type(exc).__name__}: {exc}"
        ) from None

    if not isinstance(declaration, WorkloadDefinition):
        raise ServiceError(
            f"Workload declaration for {workload_id!r} returned"
            f" {type(declaration).__name__}, expected WorkloadDefinition"
        )
    return declaration


def resolve_certification_contract(
    workload_id: str,
    *,
    description: str = "",
) -> CertificationContract:
    """Resolve the certification contract for a run (fail closed)."""
    declaration = load_declared_workload(workload_id)
    if declaration is None:
        return default_contract(workload_id, description=description)

    if declaration.inputs:
        raise ServiceError(
            f"Workload {workload_id!r} declares"
            f" {len(declaration.inputs)} input file(s); the control-plane API"
            " cannot stage fixture inputs, so this contract cannot be"
            " certified here"
        )

    return CertificationContract(
        workload_id=workload_id,
        contract_id=f"declared:{workload_py_name(workload_id)}",
        workload=declaration,
        artifact_types=tuple(a.artifact_type for a in declaration.artifacts),
    )


def workload_py_name(workload_id: str) -> str:
    """Fixture directory name a workload id resolves to."""
    if (FIXTURES_ROOT / workload_id / "workload.py").is_file():
        return workload_id
    return f"workload-{workload_id}"
