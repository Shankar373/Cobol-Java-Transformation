"""Discovery must prove dependencies and identities before allowing planning."""

import hashlib
from pathlib import Path

import pytest

from engine.modernization.modernization_planner import ModernizationPlanner
from engine.transformation.application_discovery import ApplicationDiscovery


SOURCE = """IDENTIFICATION DIVISION.
PROGRAM-ID. MAIN-PROG.
DATA DIVISION.
WORKING-STORAGE SECTION.
COPY COMMON.
PROCEDURE DIVISION.
MAIN.
    DISPLAY 'OK'.
    STOP RUN.
"""
COPYBOOK = "01 WS-COUNT PIC 9(3) VALUE 1.\n"


def workspace(tmp_path):
    (tmp_path / "main.cob").write_text(SOURCE, encoding="utf-8")
    return tmp_path


def test_resolved_copy_retains_content_and_graph_provenance(tmp_path):
    root = workspace(tmp_path)
    (root / "COMMON.cpy").write_text(COPYBOOK, encoding="utf-8")
    app = ApplicationDiscovery().discover(root)
    assert app.discovery_complete
    assert not app.discovery_issues
    ref = app.programs[0].copybooks[0]
    assert ref.resolution == "RESOLVED"
    assert ref.resolved_path == "COMMON.cpy"
    assert ref.source_hash == hashlib.sha256((root / "COMMON.cpy").read_bytes()).hexdigest()
    assert ref.location
    edge = next(edge for edge in app.edges if edge.edge_type == "COPY")
    assert ref.source_hash in edge.metadata
    assert "resolution=RESOLVED" in edge.metadata
    assert ModernizationPlanner(docker_available=True).plan(root).overall_status.value != "BLOCKED"


@pytest.mark.parametrize("failure", ["MISSING", "AMBIGUOUS", "UNREADABLE", "INVALID"])
def test_copy_failure_is_distinct_and_blocks_planning(tmp_path, monkeypatch, failure):
    root = workspace(tmp_path)
    copy = root / "COMMON.cpy"
    if failure != "MISSING":
        copy.write_text("NOT COBOL" if failure == "INVALID" else COPYBOOK, encoding="utf-8")
    if failure == "AMBIGUOUS":
        (root / "other").mkdir()
        (root / "other" / "COMMON.cpy").write_text(COPYBOOK, encoding="utf-8")
    if failure == "UNREADABLE":
        original = Path.read_text

        def read(path, *args, **kwargs):
            if path == copy:
                raise PermissionError("test copybook access denied")
            return original(path, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", read)
    app = ApplicationDiscovery().discover(root)
    assert not app.discovery_complete
    assert len(app.programs) == 1
    assert app.programs[0].copybooks[0].resolution == failure
    assert any(issue.status == f"COPY_{failure}" and "COMMON" in issue.message
               for issue in app.discovery_issues)
    assert ModernizationPlanner(docker_available=True).plan(root).overall_status.value == "BLOCKED"


def test_duplicate_ids_report_every_source_and_lookup_refuses_choice(tmp_path):
    source = SOURCE.replace("COPY COMMON.", "")
    for name in ("z.cob", "a.cob", "m.cob"):
        (tmp_path / name).write_text(source, encoding="utf-8")
    app = ApplicationDiscovery().discover(tmp_path)
    assert not app.discovery_complete
    duplicates = [issue for issue in app.discovery_issues if issue.status == "DUPLICATE_PROGRAM_ID"]
    assert [issue.source_path for issue in duplicates] == ["a.cob", "m.cob", "z.cob"]
    assert all("a.cob, m.cob, z.cob" in issue.message for issue in duplicates)
    with pytest.raises(ValueError, match="Ambiguous PROGRAM-ID"):
        app.get_program("MAIN-PROG")
    assert ModernizationPlanner(docker_available=True).plan(tmp_path).overall_status.value == "BLOCKED"


def test_complete_multi_program_application(tmp_path):
    source = SOURCE.replace("COPY COMMON.", "")
    (tmp_path / "main.cob").write_text(source.replace("DISPLAY 'OK'.", 'CALL "CHILD".'), encoding="utf-8")
    (tmp_path / "child.cob").write_text(source.replace("MAIN-PROG", "CHILD"), encoding="utf-8")
    app = ApplicationDiscovery().discover(tmp_path)
    assert app.discovery_complete
    assert len(app.programs) == 2
    assert not app.validate()
    assert ModernizationPlanner(docker_available=True).plan(tmp_path).overall_status.value != "BLOCKED"


def test_nested_copy_is_explicitly_blocked_until_materialization_supports_it(tmp_path):
    root = workspace(tmp_path)
    (root / "COMMON.cpy").write_text(COPYBOOK + "COPY NESTED.\n", encoding="utf-8")
    app = ApplicationDiscovery().discover(root)
    assert not app.discovery_complete
    assert app.programs[0].copybooks[0].resolution == "INVALID"
    assert "nested COPY" in app.discovery_issues[0].message


def test_copy_extraction_ignores_comments_and_literals_and_keeps_inline_directives():
    source = '''      * COPY COMMENTED.
*> COPY COMMENTED2.
DISPLAY "COPY LITERAL".
01 X PIC X. COPY 'REAL'. *> COPY IGNORED.
'''
    refs = ApplicationDiscovery()._extract_copybooks(source, "MAIN")
    assert [ref.copybook_name for ref in refs] == ["REAL"]
    assert refs[0].location == "4"


def test_partially_invalid_copybook_cannot_be_resolved(tmp_path):
    root = workspace(tmp_path)
    (root / "COMMON.cpy").write_text(COPYBOOK + "THIS IS NOT A DATA DESCRIPTION.\n", encoding="utf-8")
    app = ApplicationDiscovery().discover(root)
    assert not app.discovery_complete
    assert app.programs[0].copybooks[0].resolution == "INVALID"
