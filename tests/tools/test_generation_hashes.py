"""Tests for tools/generation_hashes.py (the byte-identical generation-hash tool)."""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[2]
GENERATED_APP = "workload-minimal"   # generates on both runtimes
REFUSED_APP = "workload-cics"        # refused by the plan (EXEC CICS)
APPS = f"{GENERATED_APP},{REFUSED_APP}"


def _load_tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("generation_hashes", REPO / "tools" / "generation_hashes.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclasses resolves annotations via sys.modules
    spec.loader.exec_module(mod)
    return mod


tool = _load_tool()


@pytest.fixture(autouse=True)
def _restore_cwd(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(REPO)  # the tool chdirs into the repo root


def _write(path: Path) -> int:
    return tool.main(["--write", str(path), "--apps", APPS])


def _diff_lines(out: str) -> list[str]:
    return [ln for ln in out.splitlines() if ln.startswith("  ")]


def test_two_runs_are_byte_identical(tmp_path: Path) -> None:
    assert _write(tmp_path / "a.json") == 0
    assert _write(tmp_path / "b.json") == 0
    assert (tmp_path / "a.json").read_bytes() == (tmp_path / "b.json").read_bytes()


def test_snapshot_shape_and_refusal_recorded_by_name(tmp_path: Path) -> None:
    _write(tmp_path / "s.json")
    snap = json.loads((tmp_path / "s.json").read_text(encoding="utf-8"))
    assert snap["schema"] == tool.SCHEMA and snap["tool"] == tool.TOOL
    assert set(snap["apps"]) == set(APPS.split(","))
    for runtime in ("spring_boot", "plain_java"):
        ok = snap["apps"][GENERATED_APP][runtime]
        assert ok["status"] == "generated" and ok["files"] and len(ok["tree_sha256"]) == 64
        assert list(ok["files"]) == sorted(ok["files"]) and all("\\" not in p for p in ok["files"])
        refused = snap["apps"][REFUSED_APP][runtime]
        assert refused["status"] == "refused"
        assert refused["refusal_code"] == "PLAN_SKIPPED_PROGRAMS"
        assert refused["errors"] and "UNSUPPORTED_CONSTRUCT" in refused["unsupported_markers"]


def test_check_passes_on_unchanged_tree(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write(tmp_path / "s.json")
    assert tool.main(["--check", str(tmp_path / "s.json"), "--apps", APPS]) == 0
    assert "identical" in capsys.readouterr().out


def test_one_changed_file_hash_is_reported_exactly(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    snap_path = tmp_path / "s.json"
    _write(snap_path)
    snap = json.loads(snap_path.read_text(encoding="utf-8"))
    files = snap["apps"][GENERATED_APP]["plain_java"]["files"]
    victim = sorted(files)[0]
    files[victim] = ("0" if files[victim][0] != "0" else "1") + files[victim][1:]
    snap_path.write_text(json.dumps(snap), encoding="utf-8")
    capsys.readouterr()
    assert tool.main(["--check", str(snap_path), "--apps", APPS]) == 1
    lines = _diff_lines(capsys.readouterr().out)
    assert len(lines) == 1
    assert f"{GENERATED_APP}/plain_java: file changed: {victim}" in lines[0]


def test_mutated_fixture_changes_only_its_generated_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    snap_path = tmp_path / "s.json"
    _write(snap_path)
    fixtures = tmp_path / "fixtures"
    for name in (GENERATED_APP, REFUSED_APP):
        shutil.copytree(REPO / "fixtures" / name, fixtures / name)
    cob = next((fixtures / GENERATED_APP / "cobol").glob("*.cob"))
    original = cob.read_bytes()
    cob.write_bytes(original.replace(b"VALUE 150", b"VALUE 151", 1))
    assert cob.read_bytes() != original
    capsys.readouterr()
    assert tool.main(["--check", str(snap_path), "--apps", APPS, "--fixtures-dir", str(fixtures)]) == 1
    lines = _diff_lines(capsys.readouterr().out)
    assert lines and all(ln.startswith(f"  {GENERATED_APP}/") for ln in lines)
    assert all("file changed:" in ln for ln in lines)


def test_newline_change_is_a_difference(tmp_path: Path) -> None:
    # Raw bytes are hashed: LF -> CRLF in a generated file must be reported.
    (tmp_path / "x.txt").write_bytes(b"one\ntwo\n")
    before = tool.hash_tree(tmp_path)
    (tmp_path / "x.txt").write_bytes(b"one\r\ntwo\r\n")
    assert tool.hash_tree(tmp_path)["tree_sha256"] != before["tree_sha256"]


def test_refusal_change_is_a_difference(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    snap_path = tmp_path / "s.json"
    _write(snap_path)
    snap = json.loads(snap_path.read_text(encoding="utf-8"))
    snap["apps"][REFUSED_APP]["spring_boot"]["refusal_code"] = "SOMETHING_ELSE"
    snap_path.write_text(json.dumps(snap), encoding="utf-8")
    capsys.readouterr()
    assert tool.main(["--check", str(snap_path), "--apps", APPS]) == 1
    assert f"{REFUSED_APP}/spring_boot: refused record changed" in capsys.readouterr().out


def test_tool_errors_exit_2(tmp_path: Path) -> None:
    assert tool.main(["--check", str(tmp_path / "missing.json")]) == 2
    bad = tmp_path / "bad.json"
    bad.write_text('{"schema": "other"}', encoding="utf-8")
    assert tool.main(["--check", str(bad)]) == 2
    assert tool.main(["--write", str(tmp_path / "o.json"), "--apps", "no-such-fixture"]) == 2
    with pytest.raises(SystemExit) as exc:  # argparse usage error is also exit 2
        tool.main([])
    assert exc.value.code == 2
