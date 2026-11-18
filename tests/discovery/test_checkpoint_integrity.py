"""Security tests for checkpoint integrity (tamper, symlinks, traversal).

A tampered checkpoint must be *reported* by ``verify_checkpoint``, refused by
``load_checkpoint`` and never silently reused or overwritten by
``create_checkpoint``.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from tests.discovery.helpers import REPO_ROOT, codes_of, expect_refusal, make_zip, read_json, write_enterprise_app, write_tree  # noqa: F401



from enterprise.discovery import checkpoint as cp  # noqa: E402
from enterprise.discovery.checkpoint import (  # noqa: E402
    checkpoint_dir,
    create_checkpoint,
    load_checkpoint,
    release,
    verify_checkpoint,
)
from enterprise.discovery.checkpoint_core import compute_seal  # noqa: E402
from enterprise.discovery.errors import IngestionError  # noqa: E402
from enterprise.discovery.model import ingest_directory, rmtree_force  # noqa: E402


@pytest.fixture(autouse=True)
def _no_store_key(monkeypatch):
    monkeypatch.delenv("SYSTEMAOPS_STORE_KEY", raising=False)


@pytest.fixture()
def store(tmp_path: Path):
    path = tmp_path / "store"
    yield path
    rmtree_force(path)


@pytest.fixture()
def staged(tmp_path: Path) -> Path:
    return write_enterprise_app(tmp_path / "staging")


@pytest.fixture()
def made(staged: Path, store: Path):
    """A valid checkpoint plus the ingestion that produced it."""

    ingestion = ingest_directory(staged, origin="fx")
    info = create_checkpoint(ingestion, store, origin_label="fx")
    _unlock_dirs(info.path)
    yield info, ingestion


def _a_file(info) -> Path:
    return sorted(p for p in info.source_root.rglob("*") if p.is_file())[0]


def _rel(info, path: Path) -> str:
    return path.relative_to(info.source_root).as_posix()


def _unlock(path: Path) -> None:
    os.chmod(path, 0o666)


def _unlock_dirs(root: Path) -> None:
    """POSIX checkpoints have read-only directories; a tamper simulation needs to add, rename or delete entries."""
    for dirpath, dirnames, _ in os.walk(root):
        os.chmod(dirpath, 0o755)
        for name in dirnames:
            os.chmod(os.path.join(dirpath, name), 0o755)


def _rewrite_json(info, mutate) -> None:
    target = info.path / "checkpoint.json"
    _unlock(target)
    doc = json.loads(target.read_text())
    mutate(doc)
    target.write_text(json.dumps(doc, sort_keys=True, indent=2) + "\n")


def _assert_reuse_refused(info, ingestion, store: Path) -> None:
    before = sorted(p.name for p in (store / "checkpoints").iterdir())
    with pytest.raises(IngestionError) as err:
        create_checkpoint(ingestion, store, origin_label="fx")
    assert err.value.code == "CHECKPOINT_TAMPERED"
    assert sorted(p.name for p in (store / "checkpoints").iterdir()) == before
    with pytest.raises(IngestionError) as load_err:
        load_checkpoint(info.path)
    assert load_err.value.code == "CHECKPOINT_TAMPERED"


# --- tamper of preserved content ---------------------------------------------


def test_modified_file_is_detected_and_not_reused(made, store: Path) -> None:
    info, ingestion = made
    victim = _a_file(info)
    _unlock(victim)
    victim.write_bytes(victim.read_bytes() + b"// injected")

    report = verify_checkpoint(info.path)

    assert not report.ok and not report.digest_ok
    assert report.modified == (_rel(info, victim),)
    assert not report.missing and not report.extra
    _assert_reuse_refused(info, ingestion, store)


def test_same_size_modification_is_detected(made) -> None:
    info, _ = made
    victim = _a_file(info)
    original = victim.read_bytes()
    _unlock(victim)
    victim.write_bytes(bytes((original[0] ^ 1,)) + original[1:])
    assert verify_checkpoint(info.path).modified == (_rel(info, victim),)


def test_deleted_file_is_detected(made, store: Path) -> None:
    info, ingestion = made
    victim = _a_file(info)
    _unlock(victim)
    victim.unlink()

    report = verify_checkpoint(info.path)

    assert report.missing == (_rel(info, victim),)
    assert not report.ok and not report.digest_ok
    _assert_reuse_refused(info, ingestion, store)


def test_added_file_is_detected(made, store: Path) -> None:
    info, ingestion = made
    (info.source_root / "backdoor.pas").write_bytes(b"unit evil;")

    report = verify_checkpoint(info.path)

    assert report.extra == ("backdoor.pas",)
    assert not report.ok and not report.digest_ok
    _assert_reuse_refused(info, ingestion, store)


def test_renamed_file_is_missing_plus_extra(made) -> None:
    info, _ = made
    victim = _a_file(info)
    renamed = victim.with_name("renamed_" + victim.name)
    victim.rename(renamed)

    report = verify_checkpoint(info.path)

    assert _rel(info, victim) in report.missing
    assert _rel(info, renamed) in report.extra
    assert not report.ok


def test_added_and_removed_directories_are_detected(tmp_path: Path, store: Path) -> None:
    root = write_tree(tmp_path / "t", {"a.pas": "unit a;\n"})
    (root / "empty").mkdir()
    info = create_checkpoint(ingest_directory(root, origin="t"), store, origin_label="t")
    release(info.path)

    (info.source_root / "empty").rmdir()
    (info.source_root / "planted").mkdir()
    report = verify_checkpoint(info.path)

    assert report.missing == ("empty/",)
    assert report.extra == ("planted/",)
    assert not report.ok


def test_extra_top_level_entries_are_detected(made) -> None:
    info, _ = made
    (info.path / "notes.txt").write_text("hi")
    (info.path / "original").mkdir()
    report = verify_checkpoint(info.path)
    assert set(report.extra) == {"notes.txt", "original/"}
    assert not report.ok


# --- tamper of checkpoint.json ------------------------------------------------


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: d["files"][0].update(sha256="0" * 64),
        lambda d: d["files"][0].update(size=d["files"][0]["size"] + 1),
        lambda d: d.update(source_digest="1" * 64),
        lambda d: d["source"].update(commit="c" * 40),
        lambda d: d["source"].update(kind="git"),
        lambda d: d.update(checkpoint_id="CP-00000000000000000000000000000000"),
        lambda d: d.update(file_count=d["file_count"] + 1),
        lambda d: d.update(total_bytes=d["total_bytes"] + 1),
        lambda d: d.update(directory_count=d["directory_count"] + 1),
        lambda d: d["files"].pop(),
        lambda d: d["directories"].append("ghost"),
        lambda d: d["files"].append({"path": "x.pas", "sha256": "2" * 64, "size": 1}),
    ],
)
def test_edited_checkpoint_json_is_detected(made, store: Path, mutation) -> None:
    info, ingestion = made
    _rewrite_json(info, mutation)

    report = verify_checkpoint(info.path)

    assert not report.ok
    with pytest.raises(IngestionError) as err:
        load_checkpoint(info.path)
    assert err.value.code in ("CHECKPOINT_TAMPERED", "CHECKPOINT_INVALID")
    with pytest.raises(IngestionError):
        create_checkpoint(ingestion, store, origin_label="fx")
    assert (info.path / "source").is_dir()  # nothing overwritten or removed


@pytest.mark.parametrize(
    "raw",
    [b"", b"not json", b"[]", b"{}", b'{"schema_version": "systemaops.checkpoint/9.9"}',
     b"\xff\xfe\x00bad"],
)
def test_corrupt_checkpoint_json_is_invalid_not_a_crash(made, store: Path, raw: bytes) -> None:
    info, ingestion = made
    _unlock(info.path / "checkpoint.json")
    (info.path / "checkpoint.json").write_bytes(raw)

    report = verify_checkpoint(info.path)
    assert not report.ok and report.errors
    with pytest.raises(IngestionError) as err:
        load_checkpoint(info.path)
    assert err.value.code == "CHECKPOINT_INVALID"
    with pytest.raises(IngestionError) as reuse_err:
        create_checkpoint(ingestion, store, origin_label="fx")
    assert reuse_err.value.code == "CHECKPOINT_TAMPERED"


def test_missing_checkpoint_json_is_reported(made) -> None:
    info, _ = made
    target = info.path / "checkpoint.json"
    _unlock(target)
    target.unlink()
    assert not verify_checkpoint(info.path).ok


def test_traversal_paths_inside_checkpoint_json_are_rejected(made, tmp_path: Path) -> None:
    info, _ = made
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"secret")
    _rewrite_json(info, lambda d: d["files"].append(
        {"path": "../../../outside.txt", "sha256": "0" * 64, "size": 6}))
    report = verify_checkpoint(info.path)
    assert not report.ok
    assert outside.read_bytes() == b"secret"


def test_wrong_directory_name_is_tampering(made, tmp_path: Path) -> None:
    info, _ = made
    release(info.path)
    moved = info.path.with_name("CP-ffffffffffffffffffffffffffffffff")
    info.path.rename(moved)
    assert not verify_checkpoint(moved).ok


def test_verification_messages_hold_no_absolute_paths(made) -> None:
    info, _ = made
    victim = _a_file(info)
    _unlock(victim)
    victim.write_bytes(b"x")
    report = verify_checkpoint(info.path)
    text = json.dumps([report.modified, report.missing, report.extra, report.errors])
    assert str(info.path) not in text and str(info.path.parent.parent) not in text


# --- ZIP original -------------------------------------------------------------


@pytest.fixture()
def zip_made(staged: Path, store: Path, tmp_path: Path):
    archive = make_zip(tmp_path / "in.zip", [("a.pas", b"unit a;\n")])
    ingestion = ingest_directory(staged, origin="in.zip", kind="zip")
    info = create_checkpoint(ingestion, store, origin_label="in.zip", original_archive=archive)
    _unlock_dirs(info.path)
    return info, ingestion, archive


def test_tampered_original_archive_is_detected(zip_made, store: Path) -> None:
    info, ingestion, _ = zip_made
    target = info.path / "original" / "input.zip"
    _unlock(target)
    target.write_bytes(target.read_bytes() + b"\x00")

    report = verify_checkpoint(info.path)

    assert report.modified == ("original/input.zip",)
    assert not report.ok
    # The source tree itself is intact: the digest alone is not the only gate.
    assert report.digest_ok
    with pytest.raises(IngestionError) as err:
        create_checkpoint(ingestion, store, origin_label="in.zip")
    assert err.value.code == "CHECKPOINT_TAMPERED"


def test_deleted_original_archive_is_detected(zip_made) -> None:
    info, _, _ = zip_made
    target = info.path / "original" / "input.zip"
    _unlock(target)
    target.unlink()
    assert verify_checkpoint(info.path).missing == ("original/input.zip",)


def test_extra_file_beside_original_archive_is_detected(zip_made) -> None:
    info, _, _ = zip_made
    (info.path / "original" / "second.zip").write_bytes(b"x")
    assert verify_checkpoint(info.path).extra == ("original/second.zip",)


def test_archive_changed_between_hashing_and_copy_is_detected(
    staged: Path, store: Path, tmp_path: Path, monkeypatch
) -> None:
    archive = make_zip(tmp_path / "in.zip", [("a.pas", b"unit a;\n")])
    ingestion = ingest_directory(staged, origin="in.zip", kind="zip")
    real = cp._archive_sha

    def swap_after_hash(kind, path):
        digest = real(kind, path)
        path.write_bytes(path.read_bytes() + b"tail")
        return digest

    monkeypatch.setattr(cp, "_archive_sha", swap_after_hash)
    with pytest.raises(IngestionError) as err:
        create_checkpoint(ingestion, store, origin_label="in.zip", original_archive=archive)
    assert err.value.code == "CHECKPOINT_COPY_MISMATCH"
    assert list((store / "checkpoints").iterdir()) == []


# --- symlinks ----------------------------------------------------------------


def _symlink_or_skip(link: Path, target: Path, *, directory: bool) -> None:
    try:
        os.symlink(target, link, target_is_directory=directory)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is not permitted on this platform")


def test_symlinked_file_in_staging_is_refused(tmp_path: Path, store: Path) -> None:
    root = write_tree(tmp_path / "t", {"a.pas": "unit a;\n"})
    secret = tmp_path / "secret.txt"
    secret.write_bytes(b"top secret")
    ingestion = ingest_directory(root, origin="t")
    (root / "a.pas").unlink()
    _symlink_or_skip(root / "a.pas", secret, directory=False)

    with pytest.raises(IngestionError) as err:
        create_checkpoint(ingestion, store, origin_label="t")

    assert err.value.code in ("CHECKPOINT_SYMLINK", "CHECKPOINT_COPY_MISMATCH")
    assert list((store / "checkpoints").iterdir()) == []


def test_symlinked_directory_in_staging_is_refused(tmp_path: Path, store: Path) -> None:
    root = write_tree(tmp_path / "t", {"a.pas": "unit a;\n"})
    outside = write_tree(tmp_path / "outside", {"leak.pas": "unit leak;\n"})
    ingestion = ingest_directory(root, origin="t")
    _symlink_or_skip(root / "link", outside, directory=True)

    with pytest.raises(IngestionError) as err:
        create_checkpoint(ingestion, store, origin_label="t")

    assert err.value.code == "CHECKPOINT_SYMLINK"
    assert list((store / "checkpoints").iterdir()) == []


def test_symlink_planted_in_checkpoint_is_reported_not_followed(made, tmp_path: Path) -> None:
    info, _ = made
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"external")
    release(info.path)
    victim = _a_file(info)
    victim.unlink()
    _symlink_or_skip(victim, outside, directory=False)

    report = verify_checkpoint(info.path)

    assert not report.ok
    assert _rel(info, victim) in report.missing or _rel(info, victim) in report.extra


# --- ids and misc -------------------------------------------------------------


@pytest.mark.parametrize("bad", ["..", "../x", "CP-../../etc", "CP-0123456789abcdef0123456789abcdef/../..", "C:\\x", "/abs"])
def test_ids_cannot_traverse(store: Path, bad: str) -> None:
    with pytest.raises(IngestionError):
        checkpoint_dir(store, bad)


def test_failed_creation_never_modifies_an_existing_tampered_checkpoint(
    made, store: Path
) -> None:
    info, ingestion = made
    victim = _a_file(info)
    _unlock(victim)
    victim.write_bytes(b"tampered")
    snapshot = victim.read_bytes()

    for _ in range(2):
        with pytest.raises(IngestionError):
            create_checkpoint(ingestion, store, origin_label="fx")

    assert victim.read_bytes() == snapshot  # still tampered: never overwritten


def test_large_tree_verifies(tmp_path: Path, store: Path) -> None:
    files = {f"d{i % 20}/f{i}.pas": f"unit f{i};\n" for i in range(300)}
    root = write_tree(tmp_path / "big", files)
    info = create_checkpoint(ingest_directory(root, origin="big"), store, origin_label="big")
    assert info.file_count == 300
    assert verify_checkpoint(info.path).ok


@pytest.mark.skipif(os.name != "nt", reason="NTFS junctions are Windows-only")
def test_junction_in_staging_is_refused(tmp_path: Path, store: Path) -> None:
    import subprocess

    root = write_tree(tmp_path / "t", {"a.pas": "unit a;\n"})
    outside = write_tree(tmp_path / "outside", {"leak.pas": "unit leak;\n"})
    ingestion = ingest_directory(root, origin="t")
    made_link = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(root / "jn"), str(outside)],
        capture_output=True, check=False,
    )
    if made_link.returncode != 0:
        pytest.skip("junction creation failed")

    with pytest.raises(IngestionError) as err:
        create_checkpoint(ingestion, store, origin_label="t")

    assert err.value.code == "CHECKPOINT_SYMLINK"
    assert list((store / "checkpoints").iterdir()) == []
    os.rmdir(root / "jn")


# --- seal: binding of every metadata field -------------------------------------


def _resealed_rewrite(info, mutate, key: str | None = None) -> None:
    """Edit checkpoint.json *and* recompute the seal, as a capable attacker would."""

    target = info.path / "checkpoint.json"
    _unlock(target)
    doc = json.loads(target.read_text())
    mutate(doc)
    doc.pop("seal", None)
    doc["seal"] = compute_seal(doc, key.encode() if key else None)
    target.write_text(json.dumps(doc, sort_keys=True, indent=2) + "\n")


def _swap_original(info, tmp_path: Path) -> str:
    import hashlib

    evil = make_zip(tmp_path / "evil.zip", [("a.pas", b"unit evil;\n")])
    target = info.path / "original" / "input.zip"
    _unlock(target)
    target.write_bytes(evil.read_bytes())
    return hashlib.sha256(evil.read_bytes()).hexdigest()


def _zip_checkpoint(staged: Path, store: Path, tmp_path: Path):
    archive = make_zip(tmp_path / "in.zip", [("a.pas", b"unit a;\n")])
    ingestion = ingest_directory(staged, origin="z", kind="zip")
    return create_checkpoint(ingestion, store, origin_label="z", original_archive=archive)


def test_unresealed_edit_of_provenance_fields_is_detected(made) -> None:
    info, _ = made
    _rewrite_json(info, lambda d: d["source"].update(origin="evil", ref="x"))
    report = verify_checkpoint(info.path)
    assert not report.ok and any("seal" in e for e in report.errors)
    with pytest.raises(IngestionError) as err:
        load_checkpoint(info.path)
    assert err.value.code == "CHECKPOINT_TAMPERED"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: d["source"].update(origin="evil"),
        lambda d: d["source"].update(ref="refs/heads/evil"),
        lambda d: d["source"].update(tree_id="d" * 40),
        lambda d: d["source"].update(commit_timestamp="2001-01-01T00:00:00+00:00"),
        lambda d: d["source"].update(archive_sha256="e" * 64),
        lambda d: d.update(seal_kind="sha256"),
    ],
)
def test_keyed_seal_blocks_consistent_edit_without_key(
    staged: Path, store: Path, monkeypatch, mutation
) -> None:
    monkeypatch.setenv("SYSTEMAOPS_STORE_KEY", "operator-secret")
    ingestion = ingest_directory(staged, origin="fx")
    info = create_checkpoint(ingestion, store, origin_label="fx")
    _resealed_rewrite(info, mutation, key=None)  # the attacker has no key

    assert not verify_checkpoint(info.path).ok
    with pytest.raises(IngestionError) as err:
        load_checkpoint(info.path)
    assert err.value.code == "CHECKPOINT_TAMPERED"
    with pytest.raises(IngestionError):
        create_checkpoint(ingestion, store, origin_label="fx")


def test_keyed_checkpoint_swapped_original_archive_is_detected(
    staged: Path, store: Path, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("SYSTEMAOPS_STORE_KEY", "operator-secret")
    info = _zip_checkpoint(staged, store, tmp_path)
    sha = _swap_original(info, tmp_path)
    _resealed_rewrite(info, lambda d: d["source"].update(archive_sha256=sha))
    assert not verify_checkpoint(info.path).ok


def test_unkeyed_swapped_original_with_stale_seal_is_detected(
    staged: Path, store: Path, tmp_path: Path
) -> None:
    info = _zip_checkpoint(staged, store, tmp_path)
    sha = _swap_original(info, tmp_path)
    _rewrite_json(info, lambda d: d["source"].update(archive_sha256=sha))
    assert not verify_checkpoint(info.path).ok


def test_keyed_checkpoint_without_key_is_reported(staged: Path, store: Path, monkeypatch) -> None:
    monkeypatch.setenv("SYSTEMAOPS_STORE_KEY", "operator-secret")
    ingestion = ingest_directory(staged, origin="fx")
    info = create_checkpoint(ingestion, store, origin_label="fx")
    monkeypatch.delenv("SYSTEMAOPS_STORE_KEY")

    report = verify_checkpoint(info.path)

    assert not report.ok
    assert any("sealed with a key that is not configured" in e for e in report.errors)
    with pytest.raises(IngestionError) as err:
        load_checkpoint(info.path)
    assert err.value.code == "CHECKPOINT_TAMPERED"


def test_wrong_key_is_tampered(staged: Path, store: Path, monkeypatch) -> None:
    monkeypatch.setenv("SYSTEMAOPS_STORE_KEY", "right")
    info = create_checkpoint(ingest_directory(staged, origin="fx"), store, origin_label="fx")
    monkeypatch.setenv("SYSTEMAOPS_STORE_KEY", "wrong")
    assert not verify_checkpoint(info.path).ok


def test_unkeyed_checkpoint_is_refused_once_a_key_is_configured(made, monkeypatch) -> None:
    info, _ = made
    monkeypatch.setenv("SYSTEMAOPS_STORE_KEY", "operator-secret")
    report = verify_checkpoint(info.path)
    assert not report.ok and any("unkeyed" in e for e in report.errors)


def test_missing_or_malformed_seal_is_invalid(made) -> None:
    info, _ = made
    for mutate in (
        lambda d: d.pop("seal"),
        lambda d: d.update(seal="xyz"),
        lambda d: d.update(seal_kind="md5"),
        lambda d: d.pop("seal_kind"),
    ):
        release(info.path)
        _resealed_original = json.loads((info.path / "checkpoint.json").read_text())
        _rewrite_json(info, mutate)
        assert not verify_checkpoint(info.path).ok
        with pytest.raises(IngestionError) as err:
            load_checkpoint(info.path)
        assert err.value.code == "CHECKPOINT_INVALID"
        (info.path / "checkpoint.json").write_text(
            json.dumps(_resealed_original, sort_keys=True, indent=2) + "\n"
        )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: d["source"].update(commit="zzz"),
        lambda d: d["source"].update(commit="A" * 40),
        lambda d: d["source"].update(tree_id="12345"),
        lambda d: d["source"].update(commit_timestamp="yesterday"),
        lambda d: d["source"].update(archive_sha256="abc"),
        lambda d: d["source"].update(origin="bad\nlabel"),
        lambda d: d["source"].update(ref=5),
        lambda d: d["directories"].extend(["dup", "dup"]),
    ],
)
def test_field_formats_are_revalidated_on_load_even_when_resealed(made, mutation) -> None:
    info, _ = made
    _resealed_rewrite(info, mutation)
    assert not verify_checkpoint(info.path).ok
    with pytest.raises(IngestionError) as err:
        load_checkpoint(info.path)
    assert err.value.code in ("CHECKPOINT_INVALID", "CHECKPOINT_TAMPERED")


def test_recorded_collisions_and_reserved_names_are_rejected_on_load(made) -> None:
    info, _ = made
    first = json.loads((info.path / "checkpoint.json").read_text())["files"][0]
    alt = first["path"].upper() if first["path"].upper() != first["path"] else first["path"].lower()
    clash = {"path": alt, "sha256": first["sha256"], "size": first["size"]}
    _resealed_rewrite(info, lambda d: d["files"].append(clash))
    assert not verify_checkpoint(info.path).ok
    _resealed_rewrite(
        info,
        lambda d: d["files"].__setitem__(-1, {"path": "aux.pas", "sha256": "0" * 64, "size": 0}),
    )
    with pytest.raises(IngestionError) as err:
        load_checkpoint(info.path)
    assert err.value.code == "CHECKPOINT_INVALID"
