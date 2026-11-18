"""End-to-end discovery: directory, ZIP and Git inputs; report content, gate, determinism, immutability, integrity."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import zipfile
from pathlib import Path

import pytest

from enterprise.discovery.checkpoint import verify_checkpoint
from enterprise.discovery.discover import DiscoveryRequest, discover
from enterprise.discovery.errors import IngestionError
from enterprise.discovery.limits import Limits
from enterprise.discovery.model import rmtree_force
from tests.discovery.helpers import COBOL_ESTATE, _fixed, make_zip, write_cobol_estate, write_tree

GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false"]


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run([*GIT, *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def zip_of(tmp: Path, files: dict[str, str | bytes], name: str = "estate.zip") -> Path:
    return make_zip(tmp / name, [(path, data.encode() if isinstance(data, str) else data) for path, data in files.items()])


@pytest.fixture()
def store(tmp_path: Path):
    path = tmp_path / "store"
    yield path
    rmtree_force(path)


def tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest.update(path.relative_to(root).as_posix().encode() + b"\0" + path.read_bytes())
    return digest.hexdigest()


def graph_of(result) -> dict:
    return json.loads((result.outdir / "dependency-graph.json").read_text(encoding="utf-8"))


# --- report content ---------------------------------------------------------------------------------------------------


def test_directory_discovery_reports_the_whole_estate(tmp_path: Path, store: Path) -> None:
    root = write_cobol_estate(tmp_path / "estate")
    (root / "empty" / "nested").mkdir(parents=True)
    report = discover(DiscoveryRequest("directory", str(root)), store).report

    assert report["schema_version"] == "systemaops.discovery-report/1.0"
    classes = report["summary"]["files_by_class"]
    assert classes["cobol"] == 4 and classes["copybook"] == 3 and classes["jcl-job"] == 1 and classes["jcl-proc"] == 1
    assert classes["bms"] == 1 and classes["sql"] == 1 and classes["build-config"] == 1 and classes["assembler"] == 1
    assert {p["name"] for p in report["programs"]} == {"AUDITLOG", "ORDERS", "PAYROLL", "TAXCALC"}
    payroll = next(p for p in report["programs"] if p["name"] == "PAYROLL")
    assert payroll["copybooks"] == ["EMPDCL", "EMPREC"] and payroll["db2_tables"] == ["HR.EMPLOYEE", "HR.PAYSTUB"]
    assert {"AUDITLOG", "MISSING1", "TAXCALC"} == set(payroll["calls"])

    inventory = json.loads((next(iter(store.glob("discoveries/*"))) / "file-inventory.json").read_text(encoding="utf-8"))
    directories = {d["path"]: d for d in inventory["directories"]}
    assert directories["empty/nested"]["empty"] is True and "empty" in directories
    assert len(inventory["files"]) == report["summary"]["files"] == 14


def test_subsystem_sections_cover_vsam_db2_cics_ims_mq_and_runtime(tmp_path: Path, store: Path) -> None:
    report = discover(DiscoveryRequest("directory", str(write_cobol_estate(tmp_path / "estate"))), store).report

    clusters = {c["name"]: c for c in report["vsam"]["defined_clusters"]}
    assert clusters["PROD.EMP.KSDS"]["organization"] == "KSDS" and clusters["PROD.EMP.KSDS"]["keys"] == "6 0"
    selects = {s["logical_file"]: s for s in report["vsam"]["cobol_file_selects"]}
    assert selects["EMP-FILE"]["vsam_candidate"] == "yes" and selects["RPT-FILE"]["vsam_candidate"] == "no"
    binding = report["vsam"]["dd_bindings"][0]
    assert (binding["program"], binding["ddname"], binding["dataset"], binding["vsam"]) == ("PAYROLL", "EMPFILE",
                                                                                           "PROD.EMP.KSDS", True)

    tables = {t["id"]: t for t in report["db2"]["tables"]}
    assert tables["table:HR.EMPLOYEE"]["origin"] == "input" and tables["table:HR.PAYSTUB"]["origin"] == "catalog"

    cics_ids = {n["id"] for n in report["cics"]}
    assert {"transaction:ORD1", "cics-file:ORDFILE", "bms-mapset:ORDSET"} <= cics_ids
    assert {"ims-interface:CBLTDLI"} <= {n["id"] for n in report["ims"]}
    assert {"mq-interface:MQPUT"} <= {n["id"] for n in report["mq"]}

    dependencies = {(d["category"], d["name"]) for d in report["runtime_dependencies"]}
    assert {("subsystem", "CICS"), ("subsystem", "DB2/SQL"), ("subsystem", "IMS"), ("subsystem", "MQ"),
            ("subsystem", "VSAM (indexed/relative files)"), ("build-tool", "cobc"), ("utility", "IDCAMS")} <= dependencies
    assert any(j["name"] == "PAYJOB" and len(j["steps"]) == 4 for j in report["jcl"]["jobs"])
    assert report["build"]["invocations"][0]["name"] == "cobc"


def test_dialect_evidence_is_indicative_and_traceable(tmp_path: Path, store: Path) -> None:
    files = {"ibm.cbl": "CBL SQL,CICS\n" + _fixed("PROGRAM-ID. IBM.", "PROCEDURE DIVISION.",
                                                  "    EXEC CICS RETURN END-EXEC."),
             "gc.cob": ">>SOURCE FORMAT FREE\nIDENTIFICATION DIVISION.\nPROGRAM-ID. GC.\nPROCEDURE DIVISION.\n"
                       "    ACCEPT X FROM ARGUMENT-NUMBER.\n    STOP RUN.\n",
             "plain.cbl": _fixed("PROGRAM-ID. PLAIN.", "PROCEDURE DIVISION.", "    STOP RUN.")}
    dialects = discover(DiscoveryRequest("directory", str(write_tree(tmp_path / "e", files))), store).report["dialects"]
    primary = {f["file"]: f["primary"] for f in dialects["files"]}
    assert primary == {"gc.cob": "gnucobol", "ibm.cbl": "ibm-enterprise", "plain.cbl": "undetermined"}
    assert dialects["basis"].startswith("indicative") and dialects["files"][1]["candidates"][0]["examples"]


def test_ebcdic_source_is_scanned_and_flagged_with_its_encoding(tmp_path: Path, store: Path) -> None:
    text = "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. EBCPGM.\n       PROCEDURE DIVISION.\n           CALL 'SUBX'.\n"
    root = write_tree(tmp_path / "e", {"EBCPGM": text.replace("\n", "\x25").encode("cp037")})
    result = discover(DiscoveryRequest("directory", str(root)), store)
    inventory = json.loads((result.outdir / "file-inventory.json").read_text(encoding="utf-8"))["files"][0]
    assert inventory["class"] == "cobol" and inventory["encoding"] == "ebcdic-cp037"
    assert [p["name"] for p in result.report["programs"]] == ["EBCPGM"]


# --- completeness gate ---------------------------------------------------------------------------------------------------


def test_gate_is_incomplete_with_blocking_references_and_names_them(tmp_path: Path, store: Path) -> None:
    gate = discover(DiscoveryRequest("directory", str(write_cobol_estate(tmp_path / "estate"))), store).report["completeness"]
    assert gate["status"] == "INCOMPLETE" and gate["ready_for_transformation"] is False
    assert gate["blockers"] == ["no-blocking-unresolved-references"]
    reasons = {(b["reason"], b["to"]) for b in gate["blocking_references"]}
    assert reasons == {("missing-program", "program:MISSING1"), ("missing-program", "program:GHOSTPGM"),
                       ("missing-procedure", "proc:NOPROC")}


def test_gate_opens_with_open_items_once_missing_artefacts_are_supplied(tmp_path: Path, store: Path) -> None:
    files = dict(COBOL_ESTATE)
    files["src/cobol/MISSING1.cbl"] = _fixed("PROGRAM-ID. MISSING1.", "PROCEDURE DIVISION.", "    GOBACK.")
    files["src/cobol/GHOSTPGM.cbl"] = _fixed("PROGRAM-ID. GHOSTPGM.", "PROCEDURE DIVISION.", "    GOBACK.")
    files["jcl/proclib/NOPROC.prc"] = "//NOPROC PROC\n//X EXEC PGM=IEFBR14\n// PEND\n"
    gate = discover(DiscoveryRequest("directory", str(write_tree(tmp_path / "e", files))), store).report["completeness"]
    assert gate["blockers"] == [] and gate["ready_for_transformation"] is True
    assert gate["status"] == "COMPLETE_WITH_OPEN_ITEMS"
    assert "non-blocking-unresolved" in {item["id"] for item in gate["open_items"]}


def test_a_fully_closed_estate_is_complete(tmp_path: Path, store: Path) -> None:
    files = {"src/A.cbl": _fixed("PROGRAM-ID. A.", "PROCEDURE DIVISION.", "    CALL 'B'.", "    GOBACK."),
             "src/B.cbl": _fixed("PROGRAM-ID. B.", "PROCEDURE DIVISION.", "    GOBACK.")}
    gate = discover(DiscoveryRequest("directory", str(write_tree(tmp_path / "e", files))), store).report["completeness"]
    assert gate["status"] == "COMPLETE" and gate["open_items"] == [] and all(c["passed"] for c in gate["checks"])


def test_oversized_source_file_blocks_the_gate_instead_of_being_skipped(tmp_path: Path, store: Path) -> None:
    root = write_tree(tmp_path / "e", {"BIG.cbl": _fixed("PROGRAM-ID. BIG.") + "      * " + "x" * 2000 + "\n"})
    gate = discover(DiscoveryRequest("directory", str(root)), store, limits=Limits(max_source_bytes=500)).report["completeness"]
    assert "every-source-file-scanned" in gate["blockers"]


def test_scanner_failure_becomes_a_blocking_finding(tmp_path: Path, store: Path, monkeypatch) -> None:
    import enterprise.discovery.discover as module

    def boom(path, cls, text):
        raise RuntimeError("scanner defect")

    monkeypatch.setattr(module, "scan_file", boom)
    result = discover(DiscoveryRequest("directory", str(write_cobol_estate(tmp_path / "e"))), store)
    assert "no-scanner-errors" in result.report["completeness"]["blockers"]
    assert {p["code"] for p in result.report["scanner_problems"]} == {"SCANNER_FAILED"}


def test_nested_archive_is_inventoried_and_blocks_the_gate(tmp_path: Path, store: Path) -> None:
    inner = tmp_path / "inner.zip"
    make_zip(inner, [("X.cbl", b"x")])
    root = write_tree(tmp_path / "e", {"A.cbl": _fixed("PROGRAM-ID. A.", "PROCEDURE DIVISION.", "    GOBACK."),
                                       "vendor/libs.zip": inner.read_bytes()})
    result = discover(DiscoveryRequest("directory", str(root)), store)
    assert result.report["summary"]["files_by_class"]["archive"] == 1
    assert "no-unexpanded-archives" in result.report["completeness"]["blockers"]


# --- ZIP and Git inputs, determinism -------------------------------------------------------------------------------------


def test_zip_checkpoint_preserves_the_original_archive_and_the_source(tmp_path: Path, store: Path) -> None:
    archive = zip_of(tmp_path, COBOL_ESTATE)
    result = discover(DiscoveryRequest("zip", str(archive)), store)
    info = result.checkpoint
    original = info.path / "original" / "input.zip"
    assert original.read_bytes() == archive.read_bytes() and info.archive_sha256 == hashlib.sha256(archive.read_bytes()).hexdigest()
    assert (info.source_root / "src/cobol/PAYROLL.cbl").read_bytes() == COBOL_ESTATE["src/cobol/PAYROLL.cbl"].encode()
    assert verify_checkpoint(info.path).ok


def test_zip_declared_empty_directories_are_preserved(tmp_path: Path, store: Path) -> None:
    archive = tmp_path / "d.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("keep/", "")
        zf.writestr("A.cbl", _fixed("PROGRAM-ID. A.", "PROCEDURE DIVISION.", "    GOBACK."))
    result = discover(DiscoveryRequest("zip", str(archive)), store)
    inventory = json.loads((result.outdir / "file-inventory.json").read_text(encoding="utf-8"))
    assert {d["path"]: d["empty"] for d in inventory["directories"]} == {"keep": True}


def test_directory_zip_and_git_inputs_give_the_same_graph_and_inventory(tmp_path: Path) -> None:
    root = write_cobol_estate(tmp_path / "estate")
    archive = zip_of(tmp_path, COBOL_ESTATE)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "estate")
    results = {kind: discover(DiscoveryRequest(kind, str(source)), tmp_path / f"store-{kind}")
               for kind, source in (("directory", root), ("zip", archive), ("git", root))}
    try:
        graphs = {kind: json.dumps(graph_of(r), sort_keys=True) for kind, r in results.items()}
        assert len(set(graphs.values())) == 1
        inventories = {kind: (r.outdir / "file-inventory.json").read_bytes() for kind, r in results.items()}
        assert len(set(inventories.values())) == 1
        assert results["directory"].checkpoint.source_digest == results["zip"].checkpoint.source_digest \
            == results["git"].checkpoint.source_digest
        assert results["git"].checkpoint.commit == _git(root, "rev-parse", "HEAD")
    finally:
        for kind in results:
            rmtree_force(tmp_path / f"store-{kind}")


def test_repeated_runs_are_byte_identical_across_stores_and_input_orders(tmp_path: Path) -> None:
    outputs = []
    for index, order in enumerate((sorted(COBOL_ESTATE), sorted(COBOL_ESTATE, reverse=True))):
        root = write_tree(tmp_path / f"e{index}", {name: COBOL_ESTATE[name] for name in order})
        result = discover(DiscoveryRequest("directory", str(root), label="estate"), tmp_path / f"s{index}")
        outputs.append({name: (result.outdir / name).read_bytes() for name in result.outputs.values() if name != "run-record.json"})
    for name in outputs[0]:
        assert outputs[0][name] == outputs[1][name], name
    for index in range(2):
        rmtree_force(tmp_path / f"s{index}")


def test_git_checkpoint_is_pinned_to_the_requested_commit_not_the_branch_tip(tmp_path: Path, store: Path) -> None:
    repo = write_cobol_estate(tmp_path / "repo")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "first")
    first = _git(repo, "rev-parse", "HEAD")
    (repo / "src/cobol/TAXCALC.cbl").write_text(_fixed("PROGRAM-ID. TAXCALC2.", "PROCEDURE DIVISION.", "    GOBACK."))
    _git(repo, "commit", "-q", "-am", "second")
    second = _git(repo, "rev-parse", "HEAD")
    assert first != second
    pinned = discover(DiscoveryRequest("git", str(repo), ref=first), store)
    tip = discover(DiscoveryRequest("git", str(repo)), store)
    assert pinned.checkpoint.commit == first and tip.checkpoint.commit == second
    assert pinned.checkpoint.checkpoint_id != tip.checkpoint.checkpoint_id
    assert "TAXCALC" in {p["name"] for p in pinned.report["programs"]}
    assert "TAXCALC2" in {p["name"] for p in tip.report["programs"]}
    assert not (pinned.checkpoint.source_root / ".git").exists()


def test_git_tag_resolves_to_the_commit_and_records_both(tmp_path: Path, store: Path) -> None:
    repo = write_cobol_estate(tmp_path / "repo")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "release")
    _git(repo, "tag", "v1.0")
    result = discover(DiscoveryRequest("git", str(repo), ref="v1.0"), store)
    assert result.report["provenance"]["ref"] == "v1.0" and result.report["provenance"]["commit"] == _git(repo, "rev-parse", "HEAD")
    assert len(result.report["provenance"]["tree_id"]) == 40


# --- integrity and immutability ------------------------------------------------------------------------------------------


def test_discovery_never_modifies_the_customer_input(tmp_path: Path, store: Path) -> None:
    root = write_cobol_estate(tmp_path / "estate")
    before = tree_hash(root)
    discover(DiscoveryRequest("directory", str(root)), store)
    assert tree_hash(root) == before


def test_rerun_reuses_the_verified_checkpoint_and_a_tampered_one_is_never_reused(tmp_path: Path, store: Path) -> None:
    root = write_cobol_estate(tmp_path / "estate")
    first = discover(DiscoveryRequest("directory", str(root)), store)
    again = discover(DiscoveryRequest("directory", str(root)), store)
    assert again.reused and again.checkpoint.checkpoint_id == first.checkpoint.checkpoint_id

    victim = first.checkpoint.source_root / "src/cobol/PAYROLL.cbl"
    os.chmod(victim, 0o644)
    victim.write_text("tampered", encoding="utf-8")
    report = verify_checkpoint(first.checkpoint.path)
    assert not report.ok and report.modified == ("src/cobol/PAYROLL.cbl",)
    with pytest.raises(IngestionError) as excinfo:
        discover(DiscoveryRequest("directory", str(root)), store)
    assert excinfo.value.code == "CHECKPOINT_TAMPERED"


def test_artefacts_contain_no_local_paths_and_no_staging_names(tmp_path: Path, store: Path) -> None:
    result = discover(DiscoveryRequest("directory", str(write_cobol_estate(tmp_path / "estate"))), store)
    for name in result.outputs.values():
        text = (result.outdir / name).read_text(encoding="utf-8")
        for forbidden in (str(tmp_path), str(tmp_path).replace("\\", "/"), "discovery-stage-"):
            assert forbidden not in text, (name, forbidden)
    assert not list(store.glob("discovery-stage-*")), "staging must be removed"


def test_a_refused_input_leaves_no_checkpoint_staging_or_report(tmp_path: Path, store: Path) -> None:
    archive = zip_of(tmp_path, {"A.cbl": "x"})
    make_zip(archive, [{"name": "../evil.cbl", "data": b"x"}])
    with pytest.raises(IngestionError):
        discover(DiscoveryRequest("zip", str(archive)), store)
    assert not (store / "checkpoints").exists() or not any((store / "checkpoints").iterdir())
    assert not (store / "discoveries").exists()
    assert not list(store.glob("discovery-stage-*"))


def test_store_inside_the_input_directory_is_refused(tmp_path: Path) -> None:
    root = write_cobol_estate(tmp_path / "estate")
    with pytest.raises(IngestionError) as excinfo:
        discover(DiscoveryRequest("directory", str(root)), root / "store")
    assert excinfo.value.code == "STORE_INSIDE_INPUT"


def test_progress_reports_every_step_in_order(tmp_path: Path, store: Path) -> None:
    seen: list[tuple[str, str]] = []
    discover(DiscoveryRequest("directory", str(write_cobol_estate(tmp_path / "estate"))), store,
             progress=lambda step, status, message: seen.append((step, status)))
    completed = [step for step, status in seen if status == "completed"]
    assert completed == ["ingestion", "checkpoint", "scanning_inventory", "dependency_analysis", "compiler_discovery", "report"]
