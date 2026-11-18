"""E1 — secure Git ingestion (tasks B2, E1; plan §4.4, §7).

The invariants under test, in order of importance:

* **Nothing from the repository executes.**  A hook planted in the source
  repository must not run; ``.git`` must be gone from the staged tree.
* **Nothing escapes.**  A symlink (``120000``) or gitlink (``160000``) in the
  pinned tree is refused *before* the working tree is trusted.
* **Nothing is reachable that the operator did not authorise.**  Network
  remotes are refused; the environment is stripped of credential hooks.
* **Re-ingestion is byte-identical.**  The same pin yields the same hashes,
  which is what makes a commit-pinned run reproducible.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from enterprise.discovery.discover import DiscoveryRequest, discover
from tests.discovery.helpers import REPO_ROOT, codes_of, expect_refusal, make_zip, read_json, write_enterprise_app, write_tree  # noqa: F401

from enterprise.discovery.errors import IngestionError
from enterprise.discovery.gitingest import _hardened_env, ingest_git, resolve_git_source

GIT = shutil.which("git")

pytestmark = pytest.mark.skipif(
    GIT is None, reason="git executable is required for the ingestion suite"
)

COMMITTER = (
    "-c", "user.email=discovery@example.invalid",
    "-c", "user.name=P1",
    "-c", "commit.gpgsign=false",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(
        [str(GIT), *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
        timeout=120,
    )
    if check and proc.returncode != 0:
        raise AssertionError(
            f"git {' '.join(args)} failed ({proc.returncode}): "
            f"{(proc.stderr or proc.stdout).strip()}"
        )
    return (proc.stdout or "").strip()


def _commit(repo: Path, message: str) -> str:
    _git(repo, *COMMITTER, "add", "-A")
    return _commit_staged(repo, message)


def _commit_staged(repo: Path, message: str) -> str:
    """Commit exactly what is already in the index.

    ``git add -A`` would *reconcile* the index with the working tree, which
    deletes the synthetic symlink/gitlink entries the hostile-repo fixtures
    plant there (they have no on-disk counterpart by design).
    """

    _git(repo, *COMMITTER, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _new_repo(path: Path, files: dict[str, str]) -> tuple[Path, str]:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q")
    _git(path, "config", "core.autocrlf", "false")
    write_tree(path, files)
    return path, _commit(path, "initial")


def _fresh_staging(tmp_path: Path, name: str) -> Path:
    staging = tmp_path / name
    staging.mkdir()
    return staging


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    """A small pinned repository containing a console application."""

    repo, _ = _new_repo(
        tmp_path / "origin",
        {
            "src/App.dpr": "program App;\n{$MODE OBJFPC}\nbegin\nend.\n",
            "src/uThing.pas": (
                "unit uThing;\ninterface\nimplementation\nend.\n"
            ),
            "README.md": "# pinned fixture\n",
        },
    )
    return repo


def _pin(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD")


def _records(result) -> list[tuple[str, str, int]]:
    return sorted((f.path, f.sha256, f.size) for f in result.files)


# ---------------------------------------------------------------------------
# Source classification (plan §4.4)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source",
    [
        "https://example.invalid/owner/repo.git",
        "http://example.invalid/owner/repo.git",
        "ssh://git@example.invalid/owner/repo.git",
        "git://example.invalid/owner/repo.git",
        "sftp://example.invalid/owner/repo.git",
        "ftps://example.invalid/owner/repo.git",
        "git@example.invalid:owner/repo.git",
        "someone@example.invalid:owner/repo.git",
    ],
)
def test_network_sources_are_refused(source: str) -> None:
    assert expect_refusal(resolve_git_source, source) == (
        "REMOTE_INPUT_UNSUPPORTED"
    )


@pytest.mark.parametrize(
    "source",
    ["", "   "],
)
def test_empty_git_source_is_refused(source: str) -> None:
    assert expect_refusal(resolve_git_source, source) == "INPUT_NOT_FOUND"


def test_local_path_is_accepted(git_repo: Path) -> None:
    kind, location = resolve_git_source(str(git_repo))
    assert kind == "local"
    assert Path(location) == git_repo


def test_file_url_is_accepted(git_repo: Path) -> None:
    url = git_repo.as_uri()  # file:///C:/... on Windows
    kind, location = resolve_git_source(url)
    assert kind == "local"
    assert Path(location) == git_repo


def test_local_ingest_refuses_a_remote_url_before_creating_staging(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    with pytest.raises(IngestionError) as excinfo:
        ingest_git("https://example.invalid/x.git", staging)
    assert excinfo.value.code == "REMOTE_INPUT_UNSUPPORTED"
    assert not staging.exists()


# ---------------------------------------------------------------------------
# Ingestion behaviour
# ---------------------------------------------------------------------------


def test_local_repository_is_ingested(tmp_path: Path, git_repo: Path) -> None:
    staging = _fresh_staging(tmp_path, "stage")
    result = ingest_git(str(git_repo), staging, commit=_pin(git_repo))

    assert result.kind == "git"
    assert result.commit == _pin(git_repo)
    assert result.commit_timestamp, "commit time must be source-derived"
    paths = {f.path for f in result.files}
    assert {"src/App.dpr", "src/uThing.pas", "README.md"} <= paths
    # Version-control metadata is removed from the staged tree, so it is never
    # inventoried and never hashed.
    assert not (staging / "repo" / ".git").exists()
    assert ".git" not in paths and ".git/HEAD" not in paths


def test_file_url_repository_is_ingested(
    tmp_path: Path, git_repo: Path
) -> None:
    staging = _fresh_staging(tmp_path, "stage")
    result = ingest_git(git_repo.as_uri(), staging, commit=_pin(git_repo))
    assert [f.path for f in result.files] == [f.path for f in result.files]
    assert len(result.files) == 3


def test_reingestion_is_byte_identical(tmp_path: Path, git_repo: Path) -> None:
    pin = _pin(git_repo)
    first = ingest_git(
        str(git_repo), _fresh_staging(tmp_path, "s1"), commit=pin
    )
    second = ingest_git(
        str(git_repo), _fresh_staging(tmp_path, "s2"), commit=pin
    )
    assert _records(first) == _records(second)
    assert first.commit == second.commit == pin
    assert first.total_bytes == second.total_bytes


def test_repository_without_a_pin_is_still_reproducible(
    tmp_path: Path, git_repo: Path
) -> None:
    first = ingest_git(str(git_repo), _fresh_staging(tmp_path, "s1"))
    second = ingest_git(str(git_repo), _fresh_staging(tmp_path, "s2"))
    assert _records(first) == _records(second)
    assert first.commit == second.commit == _pin(git_repo)


def test_missing_repository_path(tmp_path: Path) -> None:
    staging = _fresh_staging(tmp_path, "stage")
    assert (
        expect_refusal(
            ingest_git, str(tmp_path / "absent"), staging
        )
        == "INPUT_NOT_FOUND"
    )


def test_git_source_that_is_not_a_repository(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    write_tree(plain, {"a.txt": "hello"})
    staging = _fresh_staging(tmp_path, "stage")
    assert expect_refusal(ingest_git, str(plain), staging) == (
        "NOT_A_GIT_REPOSITORY"
    )


@pytest.mark.parametrize("pin", ["HEAD", "main", "v1.0", "zzzzzzz", "abc"])
def test_branch_and_tag_pins_are_refused(
    tmp_path: Path, git_repo: Path, pin: str
) -> None:
    """P1 pins an object name, never a moving target."""

    staging = _fresh_staging(tmp_path, "stage")
    assert (
        expect_refusal(ingest_git, str(git_repo), staging, commit=pin)
        == "INVALID_COMMIT_PIN"
    )


def test_commit_that_is_not_present(tmp_path: Path, git_repo: Path) -> None:
    staging = _fresh_staging(tmp_path, "stage")
    assert (
        expect_refusal(
            ingest_git, str(git_repo), staging,
            commit="0123456789abcdef0123456789abcdef01234567",
        )
        == "COMMIT_NOT_FOUND"
    )


def test_empty_repository(tmp_path: Path) -> None:
    repo = tmp_path / "empty"
    repo.mkdir()
    _git(repo, "init", "-q")
    staging = _fresh_staging(tmp_path, "stage")
    assert expect_refusal(ingest_git, str(repo), staging) == "EMPTY_REPOSITORY"


# ---------------------------------------------------------------------------
# Hostile repository content
# ---------------------------------------------------------------------------


def _add_blob_entry(repo: Path, mode: str, name: str, content: bytes) -> None:
    """Record *content* as a blob and index *name* at *mode*.

    Building the entry through the index is how a symlink or a gitlink is
    authored without needing privileged filesystem support on the host.
    """

    proc = subprocess.run(
        [str(GIT), "hash-object", "-w", "--stdin"],
        cwd=str(repo),
        input=content,
        capture_output=True,
        shell=False,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    blob = proc.stdout.decode("ascii").strip()
    _git(repo, "update-index", "--add", "--cacheinfo", f"{mode},{blob},{name}")


def test_symlink_entry_is_refused(tmp_path: Path) -> None:
    repo, _ = _new_repo(
        tmp_path / "symlink-origin", {"keep.txt": "kept\n"}
    )
    _add_blob_entry(repo, "120000", "escape.pas", b"../../outside")
    _commit_staged(repo, "add symlink")
    staging = _fresh_staging(tmp_path, "stage")
    assert expect_refusal(
        ingest_git, str(repo), staging, commit=_pin(repo)
    ) == "SYMLINK_ENTRY"
    # `core.symlinks=false` materialises the link as an ordinary file *inside*
    # staging, so nothing escapes; the refusal happens on the authoritative
    # `ls-tree` record rather than on whatever the worktree looks like.
    assert (staging / "repo" / "escape.pas").is_file()
    assert not (tmp_path / "outside").exists()


def test_submodule_entry_is_refused(tmp_path: Path) -> None:
    repo, _ = _new_repo(tmp_path / "sub-origin", {"keep.txt": "kept\n"})
    _git(repo, "update-index", "--add", "--cacheinfo",
         f"160000,{_pin(repo)},vendor/lib")
    _commit_staged(repo, "add gitlink")
    staging = _fresh_staging(tmp_path, "stage")
    assert expect_refusal(
        ingest_git, str(repo), staging, commit=_pin(repo)
    ) == "SUBMODULE_ENTRY"


def test_hooks_are_never_executed(tmp_path: Path, git_repo: Path) -> None:
    """A post-checkout hook in the source repository must not fire."""

    marker = tmp_path / "HOOK_RAN"
    hooks = git_repo / ".githooks"
    hooks.mkdir(exist_ok=True)
    script = hooks / "post-checkout"
    # Written for the POSIX shell; on Windows git for Windows runs it through
    # its own shell.  Either way, if it ran the marker would exist.
    script.write_text(
        f'#!/bin/sh\nprintf ran > "{marker.as_posix()}"\nexit 0\n',
        encoding="utf-8",
    )
    os.chmod(script, 0o755)
    _git(git_repo, "config", "core.hooksPath", ".githooks")
    _commit(git_repo, "install hook")
    pin = _pin(git_repo)

    result = ingest_git(
        str(git_repo), _fresh_staging(tmp_path, "stage"), commit=pin
    )
    assert result.commit == pin
    assert not marker.exists(), "a repository hook was executed during ingest"


def test_environment_is_hardened(tmp_path: Path, monkeypatch) -> None:
    """Credential-bearing variables must not reach the git subprocess."""

    monkeypatch.setenv("GIT_CONFIG", "/somewhere/attacker-controlled")
    monkeypatch.setenv("GIT_ASKPASS", "/somewhere/askpass.sh")
    monkeypatch.setenv("GIT_SSH_COMMAND", "ssh -o ProxyCommand=evil")
    monkeypatch.setenv("HOME", "/somewhere/attacker-home")

    staging = tmp_path / "stage"
    staging.mkdir()
    env = _hardened_env(staging)

    assert "GIT_CONFIG" not in env
    assert env["GIT_CONFIG_NOSYSTEM"] == "1"
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["GIT_ASKPASS"] == "true"
    assert env["GIT_SSH_COMMAND"] == "true"
    assert env["HOME"] == str(staging / ".discovery-home")
    assert str(env["GIT_CONFIG_GLOBAL"]).endswith("no-such-gitconfig")
    # GIT_* is dropped wholesale apart from the one harmless locator and the
    # two values this function deliberately sets itself.
    allowed = (
        "GIT_EXEC_PATH", "GIT_CONFIG_NOSYSTEM", "GIT_CONFIG_GLOBAL",
        "GIT_TERMINAL_PROMPT", "GIT_ASKPASS", "GIT_SSH_COMMAND",
        "GIT_EDITOR", "GIT_PAGER",
    )
    for key in env:
        if key.startswith("GIT_"):
            assert key in allowed, key


# ---------------------------------------------------------------------------
# End-to-end through the pipeline
# ---------------------------------------------------------------------------


def test_discovery_ingests_a_pinned_repository(tmp_path: Path, git_repo: Path) -> None:
    pin = _pin(git_repo)
    result = discover(DiscoveryRequest("git", str(git_repo), ref=pin, label="pinned-app"), tmp_path / "store")
    provenance = result.report["provenance"]

    assert provenance["kind"] == "git"
    assert provenance["commit"] == pin
    assert provenance["origin"] == "pinned-app"
    assert result.checkpoint.commit == pin
    text = (result.outdir / "discovery-report.json").read_text(encoding="utf-8")
    assert str(tmp_path).replace("\\", "/") not in text, "a staging path leaked into the report"
    assert result.report["summary"]["files_by_class"]


def test_repository_input_has_no_staging_paths_in_any_artefact(tmp_path: Path, git_repo: Path) -> None:
    result = discover(DiscoveryRequest("git", str(git_repo)), tmp_path / "store")
    for name in result.outputs.values():
        text = (result.outdir / name).read_text(encoding="utf-8")
        assert "discovery-stage-" not in text, name
        assert str(tmp_path) not in text, name


def test_gitattributes_conversions_never_change_the_committed_bytes(tmp_path: Path) -> None:
    """``.gitattributes`` (eol=crlf, ident, text=auto) must not alter staged bytes: the digest is host-independent."""
    repo = tmp_path / "attr-repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    committed = {"A.cbl": b"       PROGRAM-ID. A.\n       STOP RUN.\n", "B.cpy": b"01 X PIC X. $Id$\n", "C.txt": b"one\ntwo\n"}
    for name, data in committed.items():
        (repo / name).write_bytes(data)
    (repo / ".gitattributes").write_bytes(b"*.cbl text eol=crlf\n*.cpy ident\n* text=auto\n")
    _git(repo, "add", "-A")
    _git(repo, *COMMITTER, "commit", "-q", "-m", "attrs")
    staging = _fresh_staging(tmp_path, "stage")
    result = ingest_git(str(repo), staging, commit=_pin(repo))
    root = staging / "repo" if (staging / "repo").is_dir() else staging
    for name, data in committed.items():
        assert (root / name).read_bytes() == data, name
    assert {f.path for f in result.files} >= set(committed)
