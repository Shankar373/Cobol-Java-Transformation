"""Hostile ZIPs, inherited-defect regressions (audit findings) and the no-LLM / no-network guard."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import zipfile
from pathlib import Path

import pytest

from enterprise.discovery.checkpoint import create_checkpoint
from enterprise.discovery.checkpoint_core import find_collision
from enterprise.discovery.discover import DiscoveryRequest, discover
from enterprise.discovery.errors import IngestionError
from enterprise.discovery.model import IngestedFile, IngestionResult, ingest_directory, rmtree_force
from enterprise.discovery.zipsource import ingest_zip
from tests.discovery.helpers import expect_refusal, make_zip, write_tree


@pytest.fixture()
def store(tmp_path: Path):
    path = tmp_path / "store"
    yield path
    rmtree_force(path)


def staged(tmp_path: Path, name: str = "stage") -> Path:
    path = tmp_path / name
    path.mkdir()
    return path


HOSTILE = [
    ("parent traversal", [{"name": "../evil.cbl", "data": b"x"}], "ARCHIVE_BAD_PATH"),
    ("absolute path", [{"name": "/etc/evil", "data": b"x"}], "ARCHIVE_BAD_PATH"),
    pytest.param("backslash", [{"name": "ok.cbl", "raw_name": "a\b.cbl", "data": b"x"}], "ARCHIVE_BAD_PATH",
                 marks=pytest.mark.skipif(os.sep == "\\", reason="zipfile rewrites backslashes when reading on Windows")),
    ("drive letter", [{"name": "C:evil.cbl", "data": b"x"}], "ARCHIVE_BAD_PATH"),
    ("windows device", [{"name": "dir/CON", "data": b"x"}], "ARCHIVE_BAD_PATH"),
    ("trailing dot", [{"name": "a.cbl.", "data": b"x"}], "ARCHIVE_BAD_PATH"),
    ("control char", [{"name": "a\x01b.cbl", "data": b"x"}], "ARCHIVE_BAD_PATH"),
    ("symlink", [{"name": "link", "data": b"/etc/passwd", "mode": 0o120777}], "ARCHIVE_SYMLINK"),
    ("device node", [{"name": "dev", "data": b"", "mode": 0o020666}], "ARCHIVE_SPECIAL"),
    ("zip bomb", [{"name": "bomb.dat", "data": b"\0" * 5_000_000}], "ARCHIVE_BOMB"),
]


@pytest.mark.parametrize("label, entries, code", HOSTILE, ids=[getattr(h, "values", h)[0] for h in HOSTILE])
def test_hostile_archives_are_refused_with_stable_codes_and_leave_nothing(label, entries, code, tmp_path, store) -> None:
    archive = make_zip(tmp_path / "evil.zip", entries)
    sentinel = write_tree(tmp_path / "outside", {"keep.txt": "untouched"})
    with pytest.raises(IngestionError) as excinfo:
        discover(DiscoveryRequest("zip", str(archive)), store)
    assert excinfo.value.code == code
    assert (sentinel / "keep.txt").read_text() == "untouched" and not (tmp_path / "evil.cbl").exists()
    assert not (store / "discoveries").exists() and not list(store.glob("discovery-stage-*"))
    checkpoints = store / "checkpoints"
    assert not checkpoints.exists() or not list(checkpoints.iterdir())


def test_duplicate_and_case_colliding_entries_are_refused(tmp_path: Path) -> None:
    with zipfile.ZipFile(tmp_path / "dup.zip", "w") as zf:
        zf.writestr("A.cbl", "1")
        zf.writestr("a.cbl", "2")
    assert expect_refusal(ingest_zip, tmp_path / "dup.zip", staged(tmp_path), origin="t") == "ARCHIVE_DUPLICATE_PATH"


def test_unicode_normalisation_collisions_are_refused(tmp_path: Path) -> None:
    make_zip(tmp_path / "nfc.zip", [("café.cbl", b"1"), ("café.cbl", b"2")])
    assert expect_refusal(ingest_zip, tmp_path / "nfc.zip", staged(tmp_path), origin="t") == "PATH_COLLISION"


def test_too_many_entries_and_encrypted_entries_are_refused(tmp_path: Path) -> None:
    from enterprise.discovery.limits import Limits

    make_zip(tmp_path / "many.zip", [(f"f{i}.cbl", b"x") for i in range(20)])
    assert expect_refusal(ingest_zip, tmp_path / "many.zip", staged(tmp_path), origin="t",
                          limits=Limits(max_entries=10)) == "ARCHIVE_TOO_MANY_FILES"
    with zipfile.ZipFile(tmp_path / "enc.zip", "w") as zf:
        zf.writestr("secret.cbl", b"x")
    raw = bytearray((tmp_path / "enc.zip").read_bytes())
    for signature, offset in ((b"PK", 6), (b"PK", 8)):  # set the "encrypted" general-purpose flag bit
        raw[raw.index(signature) + offset] |= 0x1
    (tmp_path / "enc.zip").write_bytes(bytes(raw))
    assert expect_refusal(ingest_zip, tmp_path / "enc.zip", staged(tmp_path, "s2"), origin="t") == "ARCHIVE_ENCRYPTED"


def test_not_a_zip_is_refused(tmp_path: Path) -> None:
    (tmp_path / "x.zip").write_bytes(b"this is not a zip")
    assert expect_refusal(ingest_zip, tmp_path / "x.zip", staged(tmp_path), origin="t") == "ARCHIVE_INVALID"


def test_file_and_directory_name_conflicts_are_typed_not_raw_os_errors(tmp_path: Path) -> None:
    make_zip(tmp_path / "conflict.zip", [("a", b"file"), ("a/b.cbl", b"x")])
    result = expect_refusal(ingest_zip, tmp_path / "conflict.zip", staged(tmp_path), origin="t")
    assert result in ("PATH_COLLISION", "ARCHIVE_CORRUPT")
    with zipfile.ZipFile(tmp_path / "decl.zip", "w") as zf:
        zf.writestr("x", "file")
        zf.writestr("x/", "")
    assert expect_refusal(ingest_zip, tmp_path / "decl.zip", staged(tmp_path, "s2"), origin="t") == "PATH_COLLISION"


# --- audit regressions --------------------------------------------------------------------------------------------------


def test_directory_spelling_collisions_are_detected() -> None:
    assert find_collision(["Foo/a.cbl", "foo/b.cbl"]) is not None
    assert find_collision(["Foo/a.cbl", "Foo/b.cbl"]) is None


def test_reuse_requires_identical_content_not_just_an_existing_id(tmp_path: Path, store: Path) -> None:
    root = write_tree(tmp_path / "t", {"a.cbl": "one"})
    first = create_checkpoint(ingest_directory(root, origin="t"), store, origin_label="t")
    forged = IngestionResult(kind="directory", origin="t", staging_root=root,
                             files=[IngestedFile("b.cbl", hashlib.sha256(b"two").hexdigest(), 3)])
    # Same id by construction is impossible with 128 bits; simulate a collision by pointing the forged id at the stored one.
    from enterprise.discovery import checkpoint as module

    original = module.make_checkpoint_id
    module.make_checkpoint_id = lambda kind, commit, digest: first.checkpoint_id  # type: ignore[assignment]
    try:
        with pytest.raises(IngestionError) as excinfo:
            create_checkpoint(forged, store, origin_label="t")
    finally:
        module.make_checkpoint_id = original
    assert excinfo.value.code == "CHECKPOINT_TAMPERED"


def test_checkpoint_ids_are_128_bits() -> None:
    root_id = create_checkpoint.__module__  # noqa: F841 - module import sanity
    from enterprise.discovery.checkpoint_core import make_checkpoint_id

    assert len(make_checkpoint_id("zip", "", "0" * 64)) == len("CP-") + 32


def test_archive_is_preserved_from_the_same_copy_that_was_extracted(tmp_path: Path, store: Path) -> None:
    archive = make_zip(tmp_path / "e.zip", [("A.cbl", b"       PROGRAM-ID. A.\n")])
    result = discover(DiscoveryRequest("zip", str(archive)), store)
    original = result.checkpoint.path / "original" / "input.zip"
    assert hashlib.sha256(original.read_bytes()).hexdigest() == result.checkpoint.archive_sha256
    with zipfile.ZipFile(original) as zf:
        assert zf.namelist() == ["A.cbl"]


def test_reused_checkpoint_report_does_not_contradict_the_stored_provenance(tmp_path: Path, store: Path) -> None:
    root = write_tree(tmp_path / "t", {"a.cbl": "       PROGRAM-ID. A.\n"})
    first = discover(DiscoveryRequest("directory", str(root), label="first"), store)
    second = discover(DiscoveryRequest("directory", str(root), label="renamed"), store)
    assert second.reused and second.report["provenance"]["origin"] == "first" == second.report["checkpoint"]["source"]["origin"] \
        if "source" in second.report["checkpoint"] else second.report["provenance"]["origin"] == "first"
    assert first.checkpoint.checkpoint_id == second.checkpoint.checkpoint_id


def test_unreadable_input_file_is_a_typed_refusal(tmp_path: Path, monkeypatch) -> None:
    root = write_tree(tmp_path / "t", {"a.cbl": "x"})
    from enterprise.discovery import model

    def boom(path):
        raise PermissionError("denied")

    monkeypatch.setattr(model, "sha256_file", boom)
    assert expect_refusal(ingest_directory, root, origin="t") == "INPUT_UNREADABLE"


def test_commit_pin_rejects_a_trailing_newline(tmp_path: Path) -> None:
    from enterprise.discovery.gitingest import _COMMIT_RE

    assert _COMMIT_RE.match("a" * 40) and not _COMMIT_RE.match("a" * 40 + "\n")


# --- no LLM and no network guard ------------------------------------------------------------------------------------------

FORBIDDEN_IMPORTS = {"openai", "anthropic", "langchain", "llama_index", "transformers", "torch", "tensorflow", "sklearn",
                     "numpy", "cohere", "google.generativeai", "ollama", "sentence_transformers", "chromadb", "faiss",
                     "requests", "httpx", "aiohttp", "urllib3"}
NETWORK_MODULES = {"socket", "http", "urllib", "ssl", "ftplib", "smtplib"}
#: Only the explicit remote-Git fetch path may resolve host names.
NETWORK_ALLOWED = {"remotegit_policy.py"}
DISCOVERY = Path(__file__).resolve().parents[2] / "enterprise" / "discovery"


def _imports(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
    return found


def test_discovery_imports_no_model_sdk_ml_library_or_http_client() -> None:
    for path in sorted(DISCOVERY.glob("*.py")):
        names = {name.split(".")[0] for name in _imports(path)} | _imports(path)
        assert not names & FORBIDDEN_IMPORTS, (path.name, names & FORBIDDEN_IMPORTS)


def test_only_the_remote_git_policy_touches_network_modules() -> None:
    offenders = {path.name for path in DISCOVERY.glob("*.py")
                 if {name.split(".")[0] for name in _imports(path)} & NETWORK_MODULES} - NETWORK_ALLOWED
    assert not offenders, offenders


def test_no_model_weight_files_or_ai_endpoints_in_the_package() -> None:
    text = "\n".join(path.read_text(encoding="utf-8") for path in DISCOVERY.glob("*.py"))
    for needle in ("api.openai.com", "api.anthropic.com", "generativelanguage.googleapis.com", ".safetensors", ".gguf"):
        assert needle not in text, needle
    assert not [p for p in DISCOVERY.rglob("*") if p.suffix in (".bin", ".pt", ".onnx", ".gguf", ".safetensors")]


def test_artefacts_are_json_serialisable_and_contain_no_nan(tmp_path: Path, store: Path) -> None:
    from tests.discovery.helpers import write_cobol_estate

    result = discover(DiscoveryRequest("directory", str(write_cobol_estate(tmp_path / "e"))), store)
    for name in result.outputs.values():
        if name.endswith(".json"):
            json.loads((result.outdir / name).read_text(encoding="utf-8"), parse_constant=lambda c: pytest.fail(c))
