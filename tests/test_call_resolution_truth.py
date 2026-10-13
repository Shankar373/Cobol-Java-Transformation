"""BL-038 focused gate: `ProgramCall.resolution` equals the edge's resolution.

Two fields of one fact must agree (§77/§60 provenance): every
`ProgramCall.resolution` recorded by discovery carries the same decision
that stamps its `DependencyEdge` metadata — RESOLVED for a static target
that exists in the application, UNRESOLVED otherwise, and dynamic calls
never resolve even when the item name coincides with a program-id.

Acceptance (docs/BACKLOG.md BL-038):
1. `ProgramCall.resolution` equals the edge's resolution for every call;
2. a focused consistency test joins the gate;
3. no existing resolution contract weakened.
"""

from __future__ import annotations

from pathlib import Path

from engine.transformation.application_discovery import ApplicationDiscovery

HEADER = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. {pid}.\n"
)


def _write(tmp_path: Path, files: dict[str, str]) -> Path:
    src = tmp_path / "cobol"
    src.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (src / name).write_text(text, encoding="utf-8")
    return src


def _edge_resolutions(app) -> dict[tuple[str, str], str]:
    out: dict[tuple[str, str], str] = {}
    for edge in app.edges:
        if edge.edge_type != "CALL":
            continue
        meta = dict(
            part.split("=", 1)
            for part in edge.metadata.split(";")
            if "=" in part
        )
        out[(edge.source, edge.target)] = meta["resolution"]
    return out


class TestResolutionConsistency:
    def test_resolved_static_call_resolution_matches_edge(self, tmp_path):
        src = _write(tmp_path, {
            "A.cob": (
                HEADER.format(pid="A")
                + "       PROCEDURE DIVISION.\n"
                + "           CALL 'B'.\n"
                + "           STOP RUN.\n"
            ),
            "B.cob": HEADER.format(pid="B")
            + "       PROCEDURE DIVISION.\n"
            + "           STOP RUN.\n",
        })
        app = ApplicationDiscovery().discover(src, application_id="bl038")
        unit = next(u for u in app.programs if u.program_id == "A")
        edges = _edge_resolutions(app)
        assert unit.calls[0].resolution == "RESOLVED"
        assert edges[("A", "B")] == "RESOLVED"

    def test_unresolved_static_call_resolution_matches_edge(self, tmp_path):
        src = _write(tmp_path, {
            "A.cob": (
                HEADER.format(pid="A")
                + "       PROCEDURE DIVISION.\n"
                + "           CALL 'NOSUCH'.\n"
                + "           STOP RUN.\n"
            ),
        })
        app = ApplicationDiscovery().discover(src, application_id="bl038")
        unit = app.programs[0]
        edges = _edge_resolutions(app)
        assert unit.calls[0].resolution == "UNRESOLVED"
        assert edges[("A", "NOSUCH")] == "UNRESOLVED"

    def test_dynamic_call_stays_unresolved_even_with_matching_name(
        self, tmp_path,
    ):
        """A runtime target never resolves, whatever the data item holds."""
        src = _write(tmp_path, {
            "A.cob": (
                HEADER.format(pid="A")
                + "       DATA DIVISION.\n"
                + "       WORKING-STORAGE SECTION.\n"
                + "       01  WS-P PIC X(8) VALUE 'B'.\n"
                + "       PROCEDURE DIVISION.\n"
                + "           CALL WS-P.\n"
                + "           STOP RUN.\n"
            ),
            "B.cob": HEADER.format(pid="B")
            + "       PROCEDURE DIVISION.\n"
            + "           STOP RUN.\n",
        })
        app = ApplicationDiscovery().discover(src, application_id="bl038")
        unit = next(u for u in app.programs if u.program_id == "A")
        edges = _edge_resolutions(app)
        call = unit.calls[0]
        assert call.call_type == "DYNAMIC"
        assert call.resolution == "UNRESOLVED"
        # The dynamic edge's target is the data-item name — the runtime
        # value is never an edge target, so it can never be resolved.
        assert call.target == "WS-P"
        assert edges[("A", "WS-P")] == "UNRESOLVED"

    def test_every_call_resolution_matches_its_edge(self, tmp_path):
        """The invariant over a mixed application, call by call."""
        src = _write(tmp_path, {
            "MAIN.cob": (
                HEADER.format(pid="MAIN")
                + "       DATA DIVISION.\n"
                + "       WORKING-STORAGE SECTION.\n"
                + "       01  WS-P PIC X(8) VALUE 'SUB'.\n"
                + "       PROCEDURE DIVISION.\n"
                + "           CALL 'SUB'.\n"
                + "           CALL 'GHOST'.\n"
                + "           CALL WS-P.\n"
                + "           STOP RUN.\n"
            ),
            "SUB.cob": HEADER.format(pid="SUB")
            + "       PROCEDURE DIVISION.\n"
            + "           STOP RUN.\n",
        })
        app = ApplicationDiscovery().discover(src, application_id="bl038")
        edges = _edge_resolutions(app)
        checked = 0
        for unit in app.programs:
            for call in unit.calls:
                assert call.resolution == edges[(unit.program_id, call.target)], (
                    unit.program_id, call.target,
                    call.resolution, edges[(unit.program_id, call.target)],
                )
                checked += 1
        assert checked == 3, checked
