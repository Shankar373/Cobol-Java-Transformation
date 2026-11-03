"""BL-044: CALL name joins must be case-insensitive (COBOL semantics).

Discovery stamped `resolution` with a case-sensitive membership check
(`call.target in known_programs`) while the capability analyzer matched
names case-insensitively (`program_name.upper()`), so a mixed-case CALL
literal against an uppercase PROGRAM-ID produced contradictory facts on
one CALL: the edge/record read UNRESOLVED ("Unresolved static call
target") while the LINKAGE-arity lane resolved the same callee and could
emit ARITY_MISMATCH — two lanes, one CALL, two verdicts (BL-038 class).

These tests prove the contradiction first (red), then pin the fix: one
shared uppercase normalization (`normalize_cobol_name` in
`engine.transformation.ir`) applied in both lanes for every program-id
join — resolution stamping, callee-level lookup, self-call detection and
LINKAGE arity. Same-case resolution, genuinely missing targets and
dynamic calls keep their existing contracts (regression).
"""

from pathlib import Path

from engine.modernization.capability_analyzer import (
    CapabilityAnalyzer,
    CapabilityLevel,
)
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


def _main_calling(target: str, using: str = "") -> str:
    using_clause = f" USING {using}" if using else ""
    return (
        HEADER.format(pid="MAIN")
        + "       DATA DIVISION.\n"
        + "       WORKING-STORAGE SECTION.\n"
        + "       01  WS-A PIC X(1).\n"
        + "       PROCEDURE DIVISION.\n"
        + f"           CALL '{target}'{using_clause}.\n"
        + "           STOP RUN.\n"
    )


def _subprog(linkage_items: int) -> str:
    linkage = "".join(
        f"       01  LK-{i} PIC X(1).\n" for i in range(linkage_items)
    )
    return (
        HEADER.format(pid="SUBPROG")
        + "       DATA DIVISION.\n"
        + ("       LINKAGE SECTION.\n" if linkage else "")
        + linkage
        + "       PROCEDURE DIVISION.\n"
        + "           EXIT PROGRAM.\n"
    )


def _edge_meta(app, source: str, target: str) -> dict[str, str]:
    edge = next(
        e for e in app.edges
        if e.edge_type == "CALL" and e.source == source and e.target == target
    )
    return dict(
        part.split("=", 1)
        for part in edge.metadata.split(";")
        if "=" in part
    )


def _call_resolution(app, program_id: str) -> str:
    unit = next(u for u in app.programs if u.program_id == program_id)
    return unit.calls[0].resolution


def test_mixed_case_call_target_resolves_in_record_and_edge(tmp_path):
    """A lowercase CALL literal against an uppercase PROGRAM-ID resolves."""
    src = _write(tmp_path, {
        "MAIN.cob": _main_calling("subprog"),
        "SUBPROG.cob": _subprog(0),
    })

    app = ApplicationDiscovery().discover(src, application_id="bl044")

    unit = next(u for u in app.programs if u.program_id == "MAIN")
    assert unit.calls[0].target == "subprog"  # spelling preserved
    assert unit.calls[0].resolution == "RESOLVED"
    assert _edge_meta(app, "MAIN", "subprog")["resolution"] == "RESOLVED"


def test_mixed_case_matching_arity_call_is_supported_end_to_end(tmp_path):
    """Both lanes agree: the call is resolved and supported."""
    src = _write(tmp_path, {
        "MAIN.cob": _main_calling("subprog", using="WS-A"),
        "SUBPROG.cob": _subprog(1),
    })
    app = ApplicationDiscovery().discover(src, application_id="bl044")

    report = CapabilityAnalyzer(docker_available=True).analyze(app)

    call_caps = [
        c for c in report.components
        if c.component_type == "CALL" and c.component_id == "MAIN->subprog"
    ]
    assert len(call_caps) == 1
    assert call_caps[0].level == CapabilityLevel.SUPPORTED
    assert "Unresolved" not in call_caps[0].reason
    arity = [c for c in report.components if "arity mismatch" in c.reason]
    assert arity == []


def test_mixed_case_arity_mismatch_agrees_with_resolution(tmp_path):
    """Resolution and arity must not contradict each other."""
    src = _write(tmp_path, {
        "MAIN.cob": _main_calling("subprog", using="WS-A"),
        "SUBPROG.cob": _subprog(2),
    })
    app = ApplicationDiscovery().discover(src, application_id="bl044")

    assert _call_resolution(app, "MAIN") == "RESOLVED"
    assert _edge_meta(app, "MAIN", "subprog")["resolution"] == "RESOLVED"

    report = CapabilityAnalyzer(docker_available=True).analyze(app)
    reasons = [c.reason for c in report.components if c.component_type == "CALL"]
    # the arity lane sees the callee and flags the mismatch …
    assert any("arity mismatch" in reason for reason in reasons)
    # … and no lane claims the target is unresolved any more
    assert not any("Unresolved" in reason for reason in reasons)


def test_mixed_case_self_call_is_still_recursive_unsupported(tmp_path):
    """A case-variant self CALL stays classified as recursive, not resolved."""
    src = _write(tmp_path, {
        "MAIN.cob": _main_calling("main"),
    })
    app = ApplicationDiscovery().discover(src, application_id="bl044")

    report = CapabilityAnalyzer(docker_available=True).analyze(app)

    call_caps = [
        c for c in report.components
        if c.component_type == "CALL" and c.component_id == "MAIN->main"
    ]
    assert len(call_caps) == 1
    assert call_caps[0].level == CapabilityLevel.UNSUPPORTED
    assert "Recursive/self CALL" in call_caps[0].reason


def test_same_case_static_call_still_resolves_regression(tmp_path):
    """Uppercase CALL literal against uppercase PROGRAM-ID keeps resolving."""
    src = _write(tmp_path, {
        "MAIN.cob": _main_calling("SUBPROG"),
        "SUBPROG.cob": _subprog(0),
    })
    app = ApplicationDiscovery().discover(src, application_id="bl044")

    assert _call_resolution(app, "MAIN") == "RESOLVED"
    assert _edge_meta(app, "MAIN", "SUBPROG")["resolution"] == "RESOLVED"


def test_missing_target_still_unresolved_regression(tmp_path):
    """A genuinely missing target keeps its UNRESOLVED verdict."""
    src = _write(tmp_path, {
        "MAIN.cob": _main_calling("nosuch"),
    })
    app = ApplicationDiscovery().discover(src, application_id="bl044")

    assert _call_resolution(app, "MAIN") == "UNRESOLVED"
    assert _edge_meta(app, "MAIN", "nosuch")["resolution"] == "UNRESOLVED"


def test_dynamic_call_still_unresolved_regression(tmp_path):
    """A data-item target never resolves, whatever its name spelling."""
    src = _write(tmp_path, {
        "MAIN.cob": (
            HEADER.format(pid="MAIN")
            + "       DATA DIVISION.\n"
            + "       WORKING-STORAGE SECTION.\n"
            + "       01  WS-P PIC X(8) VALUE 'SUBPROG'.\n"
            + "       PROCEDURE DIVISION.\n"
            + "           CALL WS-P.\n"
            + "           STOP RUN.\n"
        ),
        "SUBPROG.cob": _subprog(0),
    })
    app = ApplicationDiscovery().discover(src, application_id="bl044")

    unit = next(u for u in app.programs if u.program_id == "MAIN")
    assert unit.calls[0].call_type == "DYNAMIC"
    assert unit.calls[0].resolution == "UNRESOLVED"
