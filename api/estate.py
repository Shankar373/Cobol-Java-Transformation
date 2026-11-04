"""Estate view of an ingested application: discovery plus external ledger entries, as a graph."""

from __future__ import annotations

from pathlib import Path


def compute_decomposition(workspace: Path, application_id: str) -> dict:
    """Read-only: the decomposition proposal for the application's estate (for human review)."""
    from engine.estate.decomposition import plan_decomposition
    from engine.estate.model import Edge, Estate, Node

    body = compute_estate(workspace, application_id)
    estate = Estate(
        nodes=[Node(**n) for n in body["nodes"]],
        edges=[Edge(**e) for e in body["edges"]],
    )
    plan = plan_decomposition(estate).to_dict()
    plan["application_id"] = application_id
    plan["discovery_errors"] = body["discovery_errors"]
    return plan


def compute_estate(workspace: Path, application_id: str) -> dict:
    """Read-only: discover the workspace, extract the DB2/MQ/IMS/CICS references, build the estate."""
    from api.ingestion import discover_application
    from engine.estate.model import build_estate
    from engine.modernization.external_dependency_edges import (
        extract_cics_dependency_entries,
        extract_db2_dependency_entries,
        extract_external_dependency_entries,
    )
    from engine.transformation.application_discovery import ApplicationDiscovery

    discovery = discover_application(workspace, application_id)
    external: dict[str, list[dict]] = {}
    try:
        application = ApplicationDiscovery().discover(str(workspace), application_id=application_id)
        root = workspace.resolve()
        for unit in application.programs:
            source = (workspace / unit.source_path).resolve()
            if not source.is_relative_to(root):
                continue  # never read outside the workspace
            try:
                text = source.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            entries = [
                *extract_external_dependency_entries(text),
                *extract_db2_dependency_entries(text, unit.program_id),
                *extract_cics_dependency_entries(text),
            ]
            if entries:
                external[unit.program_id] = [entry.to_dict() for entry in entries]
    except Exception as exc:  # discovery already records its own errors; the estate stays partial
        discovery.discovery_errors.append({"stage": "ESTATE_EXTERNAL", "message": str(exc)[:300]})

    estate = build_estate(discovery.to_dict(), external)
    body = estate.to_dict()
    body["application_id"] = application_id
    body["discovery_errors"] = discovery.discovery_errors
    return body
