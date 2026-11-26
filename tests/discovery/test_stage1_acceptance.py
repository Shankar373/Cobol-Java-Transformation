"""Stage 1 acceptance: ZIP, Git and directory sources of the same estate give the same blueprint, are sealed, and fail closed when tampered."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from enterprise.discovery.blueprint import verify_blueprint
from enterprise.discovery.checkpoint import checkpoint_dir, release, verify_checkpoint
from enterprise.discovery.discover import DiscoveryRequest, discover
from enterprise.discovery.model import rmtree_force
from tests.discovery.helpers import COBOL_ESTATE, make_zip, read_json, write_cobol_estate

GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false"]
#: Blueprint sections that describe the estate itself; they must not depend on how the bytes arrived.
ESTATE_SECTIONS = ("applications", "architecture", "build", "entry_points", "estate", "integrations", "programs", "relationships",
                   "resources", "unresolved")


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run([*GIT, *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture()
def sources(tmp_path: Path) -> dict[str, DiscoveryRequest]:
    directory = write_cobol_estate(tmp_path / "estate")
    archive = make_zip(tmp_path / "estate.zip", [(name, text.encode()) for name, text in COBOL_ESTATE.items()])
    repo = write_cobol_estate(tmp_path / "repo")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    return {"directory": DiscoveryRequest("directory", str(directory)), "zip": DiscoveryRequest("zip", str(archive)),
            "git": DiscoveryRequest("git", str(repo), ref="main")}


@pytest.fixture()
def results(sources, tmp_path: Path):
    store = tmp_path / "store"
    out = {kind: discover(request, store) for kind, request in sources.items()}
    yield store, out
    rmtree_force(store)


def test_every_source_kind_is_sealed_and_has_a_verified_blueprint(results) -> None:
    store, out = results
    for kind, result in out.items():
        blueprint = read_json(result.outdir / result.outputs["blueprint"])
        assert verify_blueprint(blueprint) and blueprint["blueprint_id"] == result.blueprint_id, kind
        assert blueprint["identity"]["checkpoint_id"] == result.checkpoint.checkpoint_id
        assert blueprint["identity"]["source"]["kind"] == kind
        assert verify_checkpoint(checkpoint_dir(store, result.checkpoint.checkpoint_id)).ok, kind
    assert out["git"].checkpoint.commit and len(out["git"].checkpoint.commit) == 40
    assert out["zip"].checkpoint.archive_sha256


def test_the_same_estate_gives_the_same_description_whatever_the_source_kind(results) -> None:
    _, out = results
    blueprints = {kind: read_json(r.outdir / r.outputs["blueprint"]) for kind, r in out.items()}
    assert len({r.checkpoint.source_digest for r in out.values()}) == 1  # same bytes, same digest
    assert len({r.checkpoint.checkpoint_id for r in out.values()}) == 3  # but identity also names how they arrived
    for section in ESTATE_SECTIONS:
        reference = blueprints["directory"][section]
        for kind in ("zip", "git"):
            assert blueprints[kind][section] == reference, f"{section} differs for {kind}"
    assert len({b["architecture"]["graph_id"] for b in blueprints.values()}) == 1


def test_rediscovering_the_same_input_reuses_the_checkpoint_and_the_blueprint(sources, results) -> None:
    store, out = results
    for kind, request in sources.items():
        again = discover(request, store)
        assert again.reused and again.checkpoint.checkpoint_id == out[kind].checkpoint.checkpoint_id, kind
        assert again.blueprint_id == out[kind].blueprint_id, kind


def test_a_tampered_checkpoint_no_longer_verifies_for_any_kind(results) -> None:
    store, out = results
    for kind, result in out.items():
        directory = checkpoint_dir(store, result.checkpoint.checkpoint_id)
        release(directory)
        (directory / "source" / "README.md").write_text("tampered\n", encoding="utf-8")
        report = verify_checkpoint(directory)
        assert not report.ok and "README.md" in report.modified, kind
