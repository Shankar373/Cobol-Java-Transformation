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


_LEDGER_NODE_KINDS = {"DB2": "DB2_TABLE", "MQ": "MQ_QUEUE", "IMS": "IMS_SEGMENT", "CICS": "CICS_RESOURCE"}


def _ledger_states(workspace: Path, document: dict) -> dict[tuple[str, str, str], tuple[str, str]]:
    """Proof states the DB2/MQ/IMS/CICS ledger assigns, keyed by what the graph already names.

    The graph supplies *which* program touches *which* resource; the ledger only supplies the state and the reason,
    so an entry the graph does not mention is not added as a second source of structure.
    """
    from engine.modernization.external_dependency_edges import (
        extract_cics_dependency_entries,
        extract_db2_dependency_entries,
        extract_external_dependency_entries,
    )

    root = workspace.resolve()
    states: dict[tuple[str, str, str], tuple[str, str]] = {}
    for node in document.get("nodes", ()):
        if node.get("kind") != "program" or node.get("origin") != "input" or not node.get("path"):
            continue
        program = str(node["id"]).split(":", 1)[1].upper()
        source = (workspace / node["path"]).resolve()
        if not source.is_relative_to(root):
            continue  # never read outside the workspace
        try:
            text = source.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for entry in (*extract_external_dependency_entries(text),
                      *extract_db2_dependency_entries(text, program),
                      *extract_cics_dependency_entries(text)):
            data = entry.to_dict()
            node_kind = _LEDGER_NODE_KINDS.get(str(data.get("kind", "")).split(".")[-1])
            if node_kind is None:
                continue
            bare = str(data["dependency_id"]).split(":", 1)[-1].split("=")[-1].upper()
            state = str(data.get("proof_state", "UNPROVEN")).split(".")[-1]
            states[(program, node_kind, bare)] = (state, str(data.get("reason", "")))
    return states


def compute_estate(workspace: Path, application_id: str) -> dict:
    """Read-only: the discovery graph of the workspace, viewed as the estate (the engine adds proof states only)."""
    from engine.estate.model import build_estate_from_graph
    from enterprise.discovery.graph_view import graph_from_directory

    document, problems = graph_from_directory(workspace)
    errors = [{"stage": "DISCOVERY_SCAN", "message": f"{p.file}:{p.line} {p.code}: {p.message}"[:300]}
              for p in problems]
    states: dict[tuple[str, str, str], tuple[str, str]] = {}
    try:
        states = _ledger_states(workspace, document)
    except Exception as exc:  # the graph is still complete; only the ledger's proof states are missing
        errors.append({"stage": "ESTATE_EXTERNAL", "message": str(exc)[:300]})

    body = build_estate_from_graph(document, states).to_dict()
    body["application_id"] = application_id
    body["graph_id"] = document.get("header", {}).get("graph_id", "")
    body["discovery_errors"] = errors
    return body
