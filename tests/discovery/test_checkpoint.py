"""Unit tests for ``p1.checkpoint`` (Stage 1 design, section 3).

Covers identity, determinism, idempotence, read-only enforcement, atomicity,
copy verification, empty directories, the ZIP original and concurrency.
Tamper scenarios live in ``tests/security/test_checkpoint_integrity.py``.
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from tests.discovery.helpers import REPO_ROOT, codes_of, expect_refusal, make_zip, read_json, write_enterprise_app, write_tree  # noqa: F401



from enterprise.discovery import checkpoint as cp  # noqa: E402
from enterprise.discovery.checkpoint import (  # noqa: E402
    CheckpointInfo,
    checkpoint_dir,
    compute_source_digest,
    create_checkpoint,
    list_checkpoints,
    load_checkpoint,
    make_checkpoint_id,
    verify_checkpoint,
)
from enterprise.discovery.errors import IngestionError  # noqa: E402
from enterprise.discovery.hashing import sha256_bytes  # noqa: E402
from enterprise.discovery.model import IngestedFile, ingest_directory, rmtree_force  # noqa: E402

COMMIT_A = "a" * 40
COMMIT_B = "b" * 40


@pytest.fixture(autouse=True)
def _no_store_key(monkeypatch):
    monkeypatch.delenv("SYSTEMAOPS_STORE_KEY", raising=False)


@pytest.fixture()
def store(tmp_path: Path):
    path = tmp_path / "store"
    yield path
    rmtree_force(path)


@pytest.fixture()
def second_store(tmp_path: Path):
    path = tmp_path / "store2"
    yield path
    rmtree_force(path)


def _ingest(root: Path, *, kind: str = "directory", commit: str | None = None):
    result = ingest_directory(root, origin="fixture", kind=kind)
    result.commit = commit
    return result


@pytest.fixture()
def staged(tmp_path: Path) -> Path:
    return write_enterprise_app(tmp_path / "staging")


def _make(staged: Path, store: Path, **kwargs):
    ingestion = kwargs.pop("ingestion", None) or _ingest(staged)
    kwargs.setdefault("origin_label", "enterprise-app")
    return create_checkpoint(ingestion, store, **kwargs)


# --- identity -----------------------------------------------------------------


def test_source_digest_is_order_independent_and_accepts_tuples() -> None:
    a = IngestedFile("a.pas", sha256_bytes(b"a"), 1)
    b = IngestedFile("b.pas", sha256_bytes(b"b"), 1)
    triples = [("b.pas", b.sha256, 1), ("a.pas", a.sha256, 1)]
    assert compute_source_digest([a, b]) == compute_source_digest(triples)
    assert re.fullmatch(r"[0-9a-f]{64}", compute_source_digest([]))


def test_source_digest_follows_documented_record_format() -> None:
    import hashlib

    sha = sha256_bytes(b"x")
    expected = hashlib.sha256(f"p.pas\0{sha}\0{1}\n".encode()).hexdigest()
    assert compute_source_digest([("p.pas", sha, 1)]) == expected


def test_source_digest_changes_with_content_path_or_size() -> None:
    base = compute_source_digest([("a", "0" * 64, 1)])
    assert compute_source_digest([("a", "1" * 64, 1)]) != base
    assert compute_source_digest([("b", "0" * 64, 1)]) != base
    assert compute_source_digest([("a", "0" * 64, 2)]) != base


def test_checkpoint_id_shape_and_inputs() -> None:
    digest = "0" * 64
    cid = make_checkpoint_id("git", COMMIT_A, digest)
    assert re.fullmatch(r"CP-[0-9a-f]{32}", cid)
    assert make_checkpoint_id("git", COMMIT_B, digest) != cid
    assert make_checkpoint_id("zip", COMMIT_A, digest) != cid
    assert make_checkpoint_id("git", COMMIT_A, "1" * 64) != cid
    assert make_checkpoint_id("directory", None, digest) == make_checkpoint_id(
        "directory", "", digest
    )


@pytest.mark.parametrize(
    "bad",
    ["", "CP-", "cp-0123456789ab", "CP-0123456789AB", "CP-0123456789abcdef0123456789abcdefc",
     "CP-0123456789abcdef0123456789abcdef\n", "../CP-0123456789abcdef0123456789abcdef", "CP-0123456789abcdef0123456789abcdef/..",
     "CP-..\\..\\x", "CP-0123456789a\x00", None, 5],
)
def test_checkpoint_dir_rejects_malformed_ids(store: Path, bad) -> None:
    with pytest.raises(IngestionError) as info:
        checkpoint_dir(store, bad)
    assert info.value.code == "CHECKPOINT_INVALID"


def test_checkpoint_dir_builds_path_under_store(store: Path) -> None:
    path = checkpoint_dir(store, "CP-0123456789abcdef0123456789abcdef")
    assert path == store / "checkpoints" / "CP-0123456789abcdef0123456789abcdef"


# --- create / determinism -----------------------------------------------------


def test_create_returns_populated_info(staged: Path, store: Path) -> None:
    info = _make(staged, store, ref="main", tree_id=COMMIT_B)

    assert isinstance(info, CheckpointInfo)
    assert info.reused is False
    assert info.source_kind == "directory"
    assert info.ref == "main" and info.tree_id == COMMIT_B
    assert info.path == store / "checkpoints" / info.checkpoint_id
    assert info.source_root == info.path / "source"
    assert info.file_count == len(_ingest(staged).files) > 5
    assert info.total_bytes == sum(f.size for f in _ingest(staged).files)
    assert info.directory_count == len(
        [p for p in staged.rglob("*") if p.is_dir()]
    )
    with pytest.raises(FrozenInstanceError):
        info.ref = "x"  # type: ignore[misc]


def test_preserved_files_are_byte_identical(staged: Path, store: Path) -> None:
    info = _make(staged, store)
    for entry in _ingest(staged).files:
        preserved = info.source_root.joinpath(*entry.path.split("/"))
        assert preserved.read_bytes() == staged.joinpath(*entry.path.split("/")).read_bytes()
    assert verify_checkpoint(info.path).ok


def test_checkpoint_json_schema_and_canonical_format(staged: Path, store: Path) -> None:
    info = _make(staged, store, ref="main")
    raw = (info.path / "checkpoint.json").read_bytes()

    assert raw.endswith(b"\n") and b"\r" not in raw
    doc = json.loads(raw)
    assert doc["schema_version"] == "systemaops.checkpoint/1.0"
    assert doc["read_only"] is True
    assert doc["source"]["origin"] == "enterprise-app"
    assert "archive_sha256" not in doc["source"]
    assert doc["seal_kind"] == "sha256" and re.fullmatch(r"[0-9a-f]{64}", doc["seal"])
    assert info.seal_kind == "sha256"
    assert "seal" not in info.as_dict() and "seal_kind" not in info.as_dict()
    skipped = ("files", "directories", "seal", "seal_kind")
    assert {k: v for k, v in doc.items() if k not in skipped} == info.as_dict()
    assert doc["source_digest"] == compute_source_digest(
        (f["path"], f["sha256"], f["size"]) for f in doc["files"]
    )
    assert raw == (json.dumps(doc, sort_keys=True, indent=2) + "\n").encode()


def test_as_dict_excludes_runtime_fields(staged: Path, store: Path) -> None:
    info = _make(staged, store)
    text = json.dumps(info.as_dict())
    assert "files" not in info.as_dict()
    assert str(store) not in text and "reused" not in text and "source_root" not in text


def test_same_input_in_two_stores_is_byte_identical(
    staged: Path, store: Path, second_store: Path
) -> None:
    first = _make(staged, store, ref="main")
    second = _make(staged, second_store, ref="main")

    assert first.checkpoint_id == second.checkpoint_id
    assert (first.path / "checkpoint.json").read_bytes() == (
        second.path / "checkpoint.json"
    ).read_bytes()


def test_different_commit_or_kind_gives_different_id(staged: Path, store: Path) -> None:
    ids = {
        _make(staged, store, ingestion=_ingest(staged)).checkpoint_id,
        _make(staged, store, ingestion=_ingest(staged, kind="git", commit=COMMIT_A)).checkpoint_id,
        _make(staged, store, ingestion=_ingest(staged, kind="git", commit=COMMIT_B)).checkpoint_id,
        _make(staged, store, ingestion=_ingest(staged, kind="zip")).checkpoint_id,
    }
    assert len(ids) == 4
    assert list_checkpoints(store) == sorted(ids)


def test_git_provenance_is_recorded(staged: Path, store: Path) -> None:
    ingestion = _ingest(staged, kind="git", commit=COMMIT_A)
    ingestion.commit_timestamp = "2026-11-16T10:24:00+00:00"
    info = _make(staged, store, ingestion=ingestion, ref="v1.0", tree_id=COMMIT_B)

    doc = json.loads((info.path / "checkpoint.json").read_text())
    assert doc["source"]["commit"] == COMMIT_A
    assert doc["source"]["tree_id"] == COMMIT_B
    assert doc["source"]["ref"] == "v1.0"
    assert doc["source"]["commit_timestamp"] == "2026-11-16T10:24:00+00:00"
    assert load_checkpoint(info.path).commit == COMMIT_A


def test_no_wall_clock_or_absolute_path_in_checkpoint_json(
    staged: Path, store: Path
) -> None:
    info = _make(staged, store)
    text = (info.path / "checkpoint.json").read_text()
    for forbidden in (str(store), str(staged), str(store.resolve()), str(staged.resolve())):
        assert forbidden not in text
    assert not re.search(r"\b20\d\d-\d\d-\d\dT", text)


def test_expected_digest_must_match(staged: Path, store: Path) -> None:
    ingestion = _ingest(staged)
    good = compute_source_digest(ingestion.files)
    assert _make(staged, store, ingestion=ingestion, source_digest_override=good).source_digest == good
    with pytest.raises(IngestionError) as info:
        _make(staged, store, ingestion=ingestion, source_digest_override="0" * 64)
    assert info.value.code == "CHECKPOINT_COPY_MISMATCH"


# --- input validation ---------------------------------------------------------


def test_origin_label_with_store_path_is_refused(staged: Path, store: Path) -> None:
    with pytest.raises(IngestionError) as info:
        _make(staged, store, origin_label=f"x {store}")
    assert info.value.code == "CHECKPOINT_INVALID"
    assert not (store / "checkpoints").exists() or list_checkpoints(store) == []


@pytest.mark.parametrize("field", ["origin_label", "ref", "tree_id"])
def test_control_characters_and_bad_formats_refused(
    staged: Path, store: Path, field: str
) -> None:
    value = "bad\nvalue" if field != "tree_id" else "not-hex"
    with pytest.raises(IngestionError) as info:
        _make(staged, store, **{field: value})
    assert info.value.code == "CHECKPOINT_INVALID"


def test_unknown_kind_and_bad_commit_refused(staged: Path, store: Path) -> None:
    bad_kind = _ingest(staged, kind="svn")
    with pytest.raises(IngestionError) as kind_err:
        _make(staged, store, ingestion=bad_kind)
    bad_commit = _ingest(staged, kind="git", commit="main")
    with pytest.raises(IngestionError) as commit_err:
        _make(staged, store, ingestion=bad_commit)
    assert kind_err.value.code == commit_err.value.code == "CHECKPOINT_INVALID"


def test_store_inside_staging_is_refused(staged: Path) -> None:
    with pytest.raises(IngestionError) as info:
        _make(staged, staged / "store")
    assert info.value.code == "CHECKPOINT_INVALID"


@pytest.mark.parametrize("bad", ["../escape.pas", "/abs.pas", "a\\b.pas", "C:x.pas", "a//b", ""])
def test_unsafe_recorded_paths_are_refused(staged: Path, store: Path, bad: str) -> None:
    ingestion = _ingest(staged)
    ingestion.files.append(IngestedFile(bad, "0" * 64, 0))
    with pytest.raises(IngestionError) as info:
        _make(staged, store, ingestion=ingestion)
    assert info.value.code == "CHECKPOINT_INVALID"


def test_duplicate_and_malformed_file_records_refused(staged: Path, store: Path) -> None:
    dup = _ingest(staged)
    dup.files.append(dup.files[0])
    bad_hash = _ingest(staged)
    bad_hash.files[0] = IngestedFile(bad_hash.files[0].path, "xyz", 1)
    for ingestion in (dup, bad_hash):
        with pytest.raises(IngestionError) as info:
            _make(staged, store, ingestion=ingestion)
        assert info.value.code == "CHECKPOINT_INVALID"


def test_original_archive_only_for_zip(staged: Path, store: Path, tmp_path: Path) -> None:
    archive = make_zip(tmp_path / "in.zip", [("a.pas", b"unit a;")])
    with pytest.raises(IngestionError) as info:
        _make(staged, store, original_archive=archive)
    assert info.value.code == "CHECKPOINT_INVALID"
    ingestion = _ingest(staged, kind="zip")
    with pytest.raises(IngestionError):
        _make(staged, store, ingestion=ingestion, original_archive=tmp_path / "missing.zip")


# --- idempotence --------------------------------------------------------------


def test_second_create_reuses_without_rewriting(staged: Path, store: Path) -> None:
    first = _make(staged, store, ref="main")
    stamp = (first.path / "checkpoint.json").stat().st_mtime_ns

    second = _make(staged, store, ref="other-label")

    assert second.reused is True and first.reused is False
    assert second.checkpoint_id == first.checkpoint_id
    assert second.ref == "main"  # first writer's provenance is kept
    assert (first.path / "checkpoint.json").stat().st_mtime_ns == stamp
    assert list_checkpoints(store) == [first.checkpoint_id]


def test_reuse_does_not_need_staging_to_be_present(staged: Path, store: Path) -> None:
    ingestion = _ingest(staged)
    first = _make(staged, store, ingestion=ingestion)
    rmtree_force(staged)
    again = create_checkpoint(ingestion, store, origin_label="enterprise-app")
    assert again.reused and again.checkpoint_id == first.checkpoint_id


# --- read-only ----------------------------------------------------------------


def test_preserved_files_cannot_be_written(staged: Path, store: Path) -> None:
    info = _make(staged, store)
    victim = info.source_root / "README.md"
    victim = next(p for p in info.source_root.rglob("*") if p.is_file())
    with pytest.raises(OSError):
        victim.open("ab")
    with pytest.raises(OSError):
        (info.path / "checkpoint.json").open("wb")
    assert not os.access(victim, os.W_OK)
    assert verify_checkpoint(info.path).ok


def test_release_makes_tree_deletable_by_operator(staged: Path, store: Path) -> None:
    info = _make(staged, store)
    cp.release(info.path)
    victim = next(p for p in info.source_root.rglob("*") if p.is_file())
    assert os.access(victim, os.W_OK)
    rmtree_force(info.path)
    assert not info.path.exists()
    cp.release(info.path)  # missing path is a no-op


def test_rmtree_force_removes_read_only_checkpoint(staged: Path, store: Path) -> None:
    info = _make(staged, store)
    rmtree_force(info.path)
    assert not info.path.exists()


# --- atomicity ----------------------------------------------------------------


def test_failure_mid_copy_leaves_nothing(staged: Path, store: Path, monkeypatch) -> None:
    real = cp._copy_file_verified
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 3:
            raise OSError("disk full")
        return real(*args, **kwargs)

    monkeypatch.setattr(cp, "_copy_file_verified", flaky)
    with pytest.raises(IngestionError) as err:
        _make(staged, store)

    assert err.value.code == "CHECKPOINT_COPY_FAILED"
    assert str(store) not in err.value.message
    assert calls["n"] == 3
    assert list((store / "checkpoints").iterdir()) == []
    assert list_checkpoints(store) == []


def test_failure_at_publish_leaves_nothing_and_retry_succeeds(
    staged: Path, store: Path, monkeypatch
) -> None:
    def boom(src, dst):
        raise PermissionError("denied")

    monkeypatch.setattr(cp.os, "replace", boom)
    monkeypatch.setattr(cp.time, "sleep", lambda _s: None)
    with pytest.raises(IngestionError) as info:
        _make(staged, store)
    assert info.value.code == "CHECKPOINT_PUBLISH_FAILED"
    assert list((store / "checkpoints").iterdir()) == []

    monkeypatch.undo()
    assert _make(staged, store).reused is False


def test_keyboard_interrupt_cleans_up(staged: Path, store: Path, monkeypatch) -> None:
    def interrupt(*_a, **_k):
        raise KeyboardInterrupt

    monkeypatch.setattr(cp, "_copy_file_verified", interrupt)
    with pytest.raises(KeyboardInterrupt):
        _make(staged, store)
    assert list((store / "checkpoints").iterdir()) == []


# --- copy verification --------------------------------------------------------


def test_file_changed_after_hashing_is_detected(staged: Path, store: Path) -> None:
    ingestion = _ingest(staged)
    target = staged / "README.md" if (staged / "README.md").exists() else staged / ingestion.files[0].path
    target.write_bytes(target.read_bytes() + b"changed after hashing")

    with pytest.raises(IngestionError) as info:
        create_checkpoint(ingestion, store, origin_label="x")

    assert info.value.code == "CHECKPOINT_COPY_MISMATCH"
    assert list((store / "checkpoints").iterdir()) == []


def test_same_size_content_swap_is_detected(staged: Path, store: Path) -> None:
    ingestion = _ingest(staged)
    entry = next(f for f in ingestion.files if f.size > 3)
    target = staged.joinpath(*entry.path.split("/"))
    target.write_bytes(b"Z" * entry.size)
    with pytest.raises(IngestionError) as info:
        create_checkpoint(ingestion, store, origin_label="x")
    assert info.value.code == "CHECKPOINT_COPY_MISMATCH"


def test_file_missing_from_staging_is_detected(staged: Path, store: Path) -> None:
    ingestion = _ingest(staged)
    staged.joinpath(*ingestion.files[0].path.split("/")).unlink()
    with pytest.raises(IngestionError) as info:
        create_checkpoint(ingestion, store, origin_label="x")
    assert info.value.code == "CHECKPOINT_COPY_MISMATCH"


def test_files_not_listed_in_ingestion_are_not_copied(staged: Path, store: Path) -> None:
    ingestion = _ingest(staged)
    (staged / "unlisted.secret").write_bytes(b"do not preserve")
    info = create_checkpoint(ingestion, store, origin_label="x")
    assert not (info.source_root / "unlisted.secret").exists()
    assert verify_checkpoint(info.path).ok


def test_growing_file_is_detected(staged: Path, store: Path, monkeypatch) -> None:
    ingestion = _ingest(staged)
    monkeypatch.setattr(cp, "_CHUNK", 4)
    entry = next(f for f in ingestion.files if f.size > 10)
    target = staged.joinpath(*entry.path.split("/"))
    target.write_bytes(target.read_bytes() + b"more")
    with pytest.raises(IngestionError) as info:
        create_checkpoint(ingestion, store, origin_label="x")
    assert info.value.code == "CHECKPOINT_COPY_MISMATCH"


# --- empty directories --------------------------------------------------------


def test_empty_directories_are_preserved_and_counted(tmp_path: Path, store: Path) -> None:
    root = write_tree(tmp_path / "t", {"src/a.pas": "unit a;\n", "src/sub/b.pas": "unit b;\n"})
    (root / "empty").mkdir()
    (root / "deep" / "er" / "still").mkdir(parents=True)
    (root / "src" / "sub" / "hollow").mkdir()
    info = create_checkpoint(_ingest(root), store, origin_label="t")

    for rel in ("empty", "deep/er/still", "src/sub/hollow"):
        assert (info.source_root / rel).is_dir()
    assert info.directory_count == len(
        {"src", "src/sub", "empty", "deep", "deep/er", "deep/er/still", "src/sub/hollow"}
    )
    assert verify_checkpoint(info.path).ok


def test_vcs_directory_is_not_preserved(tmp_path: Path, store: Path) -> None:
    root = write_tree(tmp_path / "t", {"a.pas": "unit a;\n"})
    (root / ".git" / "refs" / "tags").mkdir(parents=True)
    (root / ".git" / "HEAD").write_bytes(b"ref: x")
    ingestion = ingest_directory(root, origin="t", skip=(".git",))
    info = create_checkpoint(ingestion, store, origin_label="t")
    assert not (info.source_root / ".git").exists()
    assert info.file_count == 1 and info.directory_count == 0


def test_empty_tree_is_a_valid_checkpoint(tmp_path: Path, store: Path) -> None:
    root = tmp_path / "nothing"
    root.mkdir()
    info = create_checkpoint(_ingest(root), store, origin_label="t")
    assert info.file_count == 0 and info.total_bytes == 0
    assert verify_checkpoint(info.path).ok


def test_unicode_and_odd_names_roundtrip(tmp_path: Path, store: Path) -> None:
    root = write_tree(
        tmp_path / "t",
        {"dir with space/Übung ✓.pas": "unit u;\n", "x'y;[1].inc": "{}", "zero.bin": b""},
    )
    info = create_checkpoint(_ingest(root), store, origin_label="t")
    assert (info.source_root / "dir with space" / "Übung ✓.pas").is_file()
    assert verify_checkpoint(info.path).ok
    assert load_checkpoint(info.path).checkpoint_id == info.checkpoint_id


# --- ZIP original -------------------------------------------------------------


def test_zip_original_is_preserved_and_hash_recorded(
    staged: Path, store: Path, tmp_path: Path
) -> None:
    archive = make_zip(tmp_path / "in.zip", [("a.pas", b"unit a;\n")])
    ingestion = _ingest(staged, kind="zip")
    info = create_checkpoint(
        ingestion, store, origin_label="in.zip", original_archive=archive
    )

    preserved = info.path / "original" / "input.zip"
    assert preserved.read_bytes() == archive.read_bytes()
    assert info.archive_sha256 == sha256_bytes(archive.read_bytes())
    doc = json.loads((info.path / "checkpoint.json").read_text())
    assert doc["source"]["archive_sha256"] == info.archive_sha256
    assert verify_checkpoint(info.path).ok
    assert load_checkpoint(info.path).archive_sha256 == info.archive_sha256


def test_zip_without_archive_is_allowed_and_has_no_original(
    staged: Path, store: Path
) -> None:
    info = create_checkpoint(_ingest(staged, kind="zip"), store, origin_label="z")
    assert not (info.path / "original").exists()
    assert info.archive_sha256 == ""


# --- list / load --------------------------------------------------------------


def test_list_checkpoints_ignores_temp_and_foreign_entries(staged: Path, store: Path) -> None:
    info = _make(staged, store)
    (store / "checkpoints" / ".CP-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.tmp-x").mkdir()
    (store / "checkpoints" / "notes").mkdir()
    (store / "checkpoints" / "CP-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb").write_text("file, not dir")
    assert list_checkpoints(store) == [info.checkpoint_id]
    assert list_checkpoints(store / "absent") == []


def test_load_roundtrips_info(staged: Path, store: Path) -> None:
    info = _make(staged, store, ref="main")
    loaded = load_checkpoint(info.path)
    assert loaded == info
    assert loaded.reused is False


def test_load_invalid_metadata_codes(store: Path, tmp_path: Path) -> None:
    empty = tmp_path / "CP-0123456789abcdef0123456789abcdef"
    empty.mkdir()
    with pytest.raises(IngestionError) as info:
        load_checkpoint(empty)
    assert info.value.code == "CHECKPOINT_INVALID"
    report = verify_checkpoint(empty)
    assert not report.ok and report.errors
    assert not verify_checkpoint(tmp_path / "does-not-exist").ok


# --- concurrency --------------------------------------------------------------


def test_concurrent_creation_of_one_id_is_safe(staged: Path, store: Path) -> None:
    ingestion = _ingest(staged)
    results: list[CheckpointInfo] = []
    errors: list[BaseException] = []
    barrier = threading.Barrier(6)

    def worker() -> None:
        try:
            barrier.wait()
            results.append(create_checkpoint(ingestion, store, origin_label="race"))
        except BaseException as exc:  # noqa: BLE001 - surfaced by the assertion
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)

    assert not errors, errors
    assert len(results) == 6
    assert len({r.checkpoint_id for r in results}) == 1
    assert sum(1 for r in results if not r.reused) == 1
    assert verify_checkpoint(results[0].path).ok
    assert [p.name for p in (store / "checkpoints").iterdir()] == [results[0].checkpoint_id]


def test_error_codes_are_ingestion_errors() -> None:
    try:
        checkpoint_dir(Path("."), "bad")
    except IngestionError as exc:
        assert "CHECKPOINT_INVALID" in codes_of(exc)


# --- seal ---------------------------------------------------------------------


def test_seal_kind_follows_key_configuration(staged: Path, store: Path, monkeypatch) -> None:
    plain = _make(staged, store)
    assert plain.seal_kind == "sha256"

    monkeypatch.setenv("SYSTEMAOPS_STORE_KEY", "operator-secret")
    keyed_store = store.parent / "keyed"
    keyed = _make(staged, keyed_store)
    try:
        assert keyed.seal_kind == "hmac-sha256"
        doc = json.loads((keyed.path / "checkpoint.json").read_text())
        assert doc["seal_kind"] == "hmac-sha256" and "operator-secret" not in json.dumps(doc)
        assert verify_checkpoint(keyed.path).ok
    finally:
        rmtree_force(keyed_store)


@pytest.mark.parametrize("key", [None, "k1"])
def test_same_input_same_key_mode_is_byte_identical(
    staged: Path, store: Path, second_store: Path, monkeypatch, key
) -> None:
    if key:
        monkeypatch.setenv("SYSTEMAOPS_STORE_KEY", key)
    first = _make(staged, store, ref="main")
    second = _make(staged, second_store, ref="main")
    assert (first.path / "checkpoint.json").read_bytes() == (
        second.path / "checkpoint.json"
    ).read_bytes()


def test_different_keys_give_different_seals(
    staged: Path, store: Path, second_store: Path, monkeypatch
) -> None:
    monkeypatch.setenv("SYSTEMAOPS_STORE_KEY", "a")
    one = _make(staged, store)
    monkeypatch.setenv("SYSTEMAOPS_STORE_KEY", "b")
    two = _make(staged, second_store)
    seals = [json.loads((i.path / "checkpoint.json").read_text())["seal"] for i in (one, two)]
    assert seals[0] != seals[1]


# --- collisions and names -----------------------------------------------------


def _with_paths(staged: Path, *paths: str):
    ingestion = _ingest(staged)
    for path in paths:
        ingestion.files.append(IngestedFile(path, "0" * 64, 0))
    return ingestion


@pytest.mark.parametrize(
    "pair",
    [
        ("Unit1.pas", "unit1.pas"),
        ("caf\u00e9.pas", "cafe\u0301.pas"),
        ("stra\u00dfe.pas", "STRASSE.pas"),
        ("lib", "Lib/x.pas"),
        ("a/B.pas", "A/b.pas"),
    ],
)
def test_case_and_unicode_collisions_are_refused(staged: Path, store: Path, pair) -> None:
    with pytest.raises(IngestionError) as err:
        _make(staged, store, ingestion=_with_paths(staged, *pair))
    assert err.value.code == "PATH_COLLISION"
    assert not (store / "checkpoints").exists() or list_checkpoints(store) == []


@pytest.mark.parametrize(
    "bad",
    ["aux.pas", "dir/CON", "nul.txt", "COM1", "lpt9.tar.gz", "a/Prn.dat",
     "name.", "dir /x.pas", "x.pas ", "d./x"],
)
def test_windows_reserved_and_trailing_names_are_refused(
    staged: Path, store: Path, bad: str
) -> None:
    with pytest.raises(IngestionError) as err:
        _make(staged, store, ingestion=_with_paths(staged, bad))
    assert err.value.code == "CHECKPOINT_INVALID"


def test_raw_oserror_from_copy_is_wrapped(staged: Path, store: Path, monkeypatch) -> None:
    def clash(*_a, **_k):
        raise FileExistsError(17, "exists", str(store / "secret-location"))

    monkeypatch.setattr(cp, "_copy_file_verified", clash)
    with pytest.raises(IngestionError) as err:
        _make(staged, store)
    assert err.value.code == "CHECKPOINT_COPY_FAILED"
    assert "secret-location" not in err.value.message
    assert list((store / "checkpoints").iterdir()) == []
