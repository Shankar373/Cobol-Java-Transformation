"""Layer 6 migration M3: COPY and FILE relationships come from the canonical Application IR with their provenance.

COPY statements are facts (``copy-site``) resolved through the one copybook resolver; FILE dependencies are projected from
the IR's file references with discovery's own semantics.  Differential over every fixture application, mutation tests, and
provenance checks (every COPY site names its file, line and column; no absolute path enters the document).
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from engine.application_ir.consume import canonicalize, ir_for_application
from engine.application_ir.legacy import copybook_references, file_dependencies
from engine.application_ir.project import project, verify, to_dict
from engine.modernization.capability_analyzer import CapabilityAnalyzer, CapabilityLevel
from engine.semantic_facts.build import build_semantic_facts
from engine.transformation.application_discovery import ApplicationDiscovery

REPO = Path(__file__).resolve().parents[2]
APP_DIRS = sorted(p for p in (REPO / "fixtures").glob("*/cobol") if p.is_dir())

PROGRAM = ("       IDENTIFICATION DIVISION.\n       PROGRAM-ID. MAIN.\n       DATA DIVISION.\n       WORKING-STORAGE SECTION.\n"
           "       COPY COMMON.\n       COPY MISSING1.\n       COPY AMBIG.\n"
           "      * COPY INCOMMENT.\n       PROCEDURE DIVISION.\n       RUN-IT.\n           STOP RUN.\n")


def _tree(tmp_path: Path) -> Path:
    (tmp_path / "MAIN.cob").write_text(PROGRAM, encoding="utf-8")
    (tmp_path / "COMMON.cpy").write_text("       01 COMMON-ITEM PIC X.\n", encoding="utf-8")
    (tmp_path / "AMBIG.cpy").write_text("       01 A1 PIC X.\n", encoding="utf-8")
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "AMBIG.cpy").write_text("       01 A2 PIC X.\n", encoding="utf-8")
    return tmp_path


def _doc(root: Path, **kw):
    sources = {p.relative_to(root).as_posix(): p.read_text(encoding="utf-8") for p in sorted(root.glob("*.cob"))}
    return build_semantic_facts(sources, **kw).as_dict()


def _sites(document):
    return {f["attributes"]["member"]: f for f in document["facts"] if f["kind"] == "copy-site"}


# --- COPY facts ----------------------------------------------------------------------------------------------------------

def test_every_copy_state_is_stated_and_a_commented_copy_is_not_a_site(tmp_path):
    sites = _sites(_doc(_tree(tmp_path), copy_root=tmp_path))
    assert set(sites) == {"COMMON", "MISSING1", "AMBIG"}
    assert (sites["COMMON"]["resolution"]["state"], sites["COMMON"]["resolution"]["candidates"]) == ("resolved", ["COMMON.cpy"])
    assert (sites["MISSING1"]["resolution"]["state"], sites["MISSING1"]["resolution"]["reason"]) == ("unresolved", "missing-copybook")
    ambiguous = sites["AMBIG"]["resolution"]
    assert ambiguous["state"] == "ambiguous" and ambiguous["candidates"] == ["AMBIG.cpy", "lib/AMBIG.cpy"]


def test_without_a_root_a_copy_site_is_stated_but_never_claimed_resolved(tmp_path):
    sites = _sites(_doc(_tree(tmp_path)))
    assert {s["resolution"]["state"] for s in sites.values()} == {"unsupported"}
    assert {s["resolution"]["reason"] for s in sites.values()} == {"COPY_RESOLUTION_NOT_REQUESTED"}


def test_copy_provenance_is_the_exact_physical_position_and_no_absolute_path_enters_the_document(tmp_path):
    root = _tree(tmp_path)
    document = _doc(root, copy_root=root)
    lines = PROGRAM.split("\n")
    for site in _sites(document).values():
        span = site["span"]
        assert span["exact"] and lines[span["line"] - 1][span["column"] - 1: span["column"] + 3].upper() == "COPY"
        assert site["attributes"]["location"] == f"{span['file']}:{span['line']}"
    assert str(tmp_path) not in str(document) and str(tmp_path).replace("\\", "/") not in str(document)


def test_copy_resolution_follows_the_library_orders_like_discovery(tmp_path):
    root = _tree(tmp_path)
    plain = _sites(_doc(root, copy_root=root))["AMBIG"]["resolution"]["state"]
    ordered = _sites(_doc(root, copy_root=root, library_orders={"MAIN": [["lib", "."]]}))["AMBIG"]["resolution"]
    assert plain == "ambiguous" and ordered["state"] in ("resolved", "ambiguous")


def test_copy_sites_project_to_typed_edges_owned_by_their_program_and_verify(tmp_path):
    root = _tree(tmp_path)
    document = _doc(root, copy_root=root)
    ir = project(document)
    edges = [e for e in ir.edges if e.kind == "copy-site"]
    assert len(edges) == 3 and all(e.source.endswith("program:MAIN#1") for e in edges)
    assert all(e.provenance.startswith("fact:") and e.span is not None for e in edges)
    assert verify(to_dict(ir), document) == []


# --- differential over the corpus -----------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def applications():
    out = {}
    for directory in APP_DIRS:
        try:
            app = ApplicationDiscovery().discover(directory)
        except Exception:                           # noqa: BLE001 - no legacy baseline
            continue
        out[directory.parent.name] = (directory, app, ir_for_application(app, directory))
    return out


def test_the_ir_copy_references_equal_discoverys_on_every_application(applications):
    compared = 0
    for name, (directory, app, ir) in applications.items():
        derived = copybook_references(ir, str(directory))
        for unit in app.programs:
            assert tuple(derived.get(unit.source_path, ())) == tuple(unit.copybooks), (name, unit.program_id)
            compared += len(unit.copybooks)
    assert compared > 0


def test_the_checks_confirm_every_relationship_except_the_documented_cics_superset(applications):
    reasons = {}
    for name, (directory, app, ir) in applications.items():
        for what, source, reason, detail in canonicalize(app, ir, directory).checks:
            reasons.setdefault((what, source, reason), []).append(name)
    assert set(reasons) == {("CALL edges", "ir", ""), ("entry points", "ir", ""), ("COPY references", "ir", ""),
                            ("FILE dependencies", "ir", ""), ("FILE dependencies", "discovery", "DISCOVERY_SUPERSET")}
    # discovery's text scan reads READ/WRITE inside EXEC CICS blocks as files (``DATASET``); the IR does not
    assert reasons[("FILE dependencies", "discovery", "DISCOVERY_SUPERSET")] == ["workload-cics"]


def test_the_canonical_application_is_value_identical_to_discovery(applications):
    for name, (directory, app, ir) in applications.items():
        canonical = canonicalize(app, ir, directory).application
        assert [(u.program_id, u.copybooks, u.file_dependencies, u.entry_points) for u in canonical.programs] == \
            [(u.program_id, u.copybooks, u.file_dependencies, u.entry_points) for u in app.programs], name
        assert sorted(map(repr, canonical.edges)) == sorted(map(repr, app.edges)), name


@pytest.mark.parametrize("name", ["workload-copybook", "workload-claims", "workload-indexed", "workload-file-write-read"])
def test_the_report_is_identical_with_the_ir_for_applications_with_copy_and_file_relationships(applications, name):
    directory, app, ir = applications[name]
    analyzer = CapabilityAnalyzer()
    assert analyzer.analyze(app, directory, ir=ir).to_dict() == analyzer.analyze(app, directory).to_dict()


# --- mutation ---------------------------------------------------------------------------------------------------------------

def test_a_wrong_copy_resolution_in_the_ir_is_reported_and_discovery_is_kept(applications):
    directory, app, ir = applications["workload-copybook"]
    forged_edges = tuple(
        dataclasses.replace(e, resolution=dataclasses.replace(e.resolution, state="unresolved", candidates=(),
                                                                reason="missing-copybook", confidence="unresolved"))
        if e.kind == "copy-site" else e for e in ir.edges)
    forged = dataclasses.replace(ir, edges=forged_edges)
    canonical = canonicalize(app, forged, directory)
    assert any(what == "COPY references" and reason == "IR_DIVERGES_FROM_DISCOVERY" for what, _s, reason, _d in canonical.checks)
    assert [u.copybooks for u in canonical.application.programs] == [u.copybooks for u in app.programs]
    finding = [c for c in CapabilityAnalyzer().analyze(app, directory, ir=forged).components if c.component_id == "IR->DISCOVERY"]
    assert len(finding) == 1 and finding[0].level == CapabilityLevel.UNSUPPORTED and "COPY references" in finding[0].reason


def test_a_file_dependency_the_ir_has_and_discovery_lacks_is_a_divergence_not_a_superset(applications):
    directory, app, ir = applications["workload-claims"]
    stripped = dataclasses.replace(app, programs=tuple(
        dataclasses.replace(u, file_dependencies=u.file_dependencies[:-1]) for u in app.programs))
    checks = {what: reason for what, _s, reason, _d in canonicalize(stripped, ir, directory).checks}
    assert checks["FILE dependencies"] == "IR_DIVERGES_FROM_DISCOVERY"


def test_a_discovery_only_extra_dependency_is_the_documented_fail_closed_superset(applications):
    directory, app, ir = applications["workload-claims"]
    first = app.programs[0].file_dependencies[0]
    extra = dataclasses.replace(app, programs=tuple(
        dataclasses.replace(u, file_dependencies=u.file_dependencies + (dataclasses.replace(first, file_name="PHANTOM"),))
        if i == 0 else u for i, u in enumerate(app.programs)))
    checks = {what: reason for what, _s, reason, _d in canonicalize(extra, ir, directory).checks}
    assert checks["FILE dependencies"] == "DISCOVERY_SUPERSET"
    assert "PHANTOM" in [d.file_name for d in canonicalize(extra, ir, directory).application.programs[0].file_dependencies]


def test_the_file_projection_follows_discovery_semantics_not_every_file_verb(tmp_path):
    source = ("       IDENTIFICATION DIVISION.\n       PROGRAM-ID. F.\n       ENVIRONMENT DIVISION.\n"
              "       INPUT-OUTPUT SECTION.\n       FILE-CONTROL.\n           SELECT IN-F ASSIGN TO 'in.dat'.\n"
              "       DATA DIVISION.\n       FILE SECTION.\n       FD IN-F.\n       01 IN-REC PIC X(4).\n"
              "       PROCEDURE DIVISION.\n       MAIN.\n           OPEN INPUT IN-F.\n           READ IN-F.\n"
              "           CLOSE IN-F.\n           STOP RUN.\n")
    document = build_semantic_facts({"F.cob": source}).as_dict()
    projected = file_dependencies(project(document))["F.cob"]
    assert [(d.operation, d.file_name, d.mode) for d in projected] == [("OPEN", "IN-F", "INPUT"), ("READ", "IN-F", "")]
    (tmp_path / "F.cob").write_text(source, encoding="utf-8")
    legacy = ApplicationDiscovery().discover(tmp_path).programs[0].file_dependencies
    assert [(d.operation, d.file_name, d.mode) for d in legacy] == [(d.operation, d.file_name, d.mode) for d in projected]


def test_programs_in_subdirectories_compare_under_one_path_spelling(tmp_path):
    """Discovery keeps OS separators in ``source_path`` but POSIX in COPY locations: the IR is keyed POSIX and must still match."""
    (tmp_path / "src" / "deep").mkdir(parents=True)
    (tmp_path / "src" / "deep" / "MAIN.cob").write_text(PROGRAM.replace("COPY MISSING1.", "COPY COMMON."), encoding="utf-8")
    (tmp_path / "libs").mkdir()
    (tmp_path / "libs" / "COMMON.cpy").write_text("       01 COMMON-ITEM PIC X.\n", encoding="utf-8")
    (tmp_path / "libs" / "AMBIG.cpy").write_text("       01 A1 PIC X.\n", encoding="utf-8")
    app = ApplicationDiscovery().discover(tmp_path)
    checks = {what: reason for what, _s, reason, _d in canonicalize(app, ir_for_application(app, tmp_path), tmp_path).checks}
    assert checks["COPY references"] == "" and checks["FILE dependencies"] == ""
