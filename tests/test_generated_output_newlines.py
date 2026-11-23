"""Generated projects are byte-identical on every platform: output writers say ``newline="\\n"``.

``Path.write_text(text, encoding="utf-8")`` translates ``\\n`` to ``\\r\\n`` on Windows, so the same COBOL produced
different bytes on a developer's Windows machine and on the Linux CI that certifies it (found when the Linux
generation-hash check failed against a Windows-built baseline: nearly every file differed).  Every ``write_text`` in
``engine/`` that emits generated or evidence output must therefore pass ``newline=``; the few that do not are listed
here with the reason.  A new writer fails this test until it chooses.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

#: modules whose ``write_text`` may keep the platform default, with the reason (module path -> reason)
PLATFORM_DEFAULT_OK = {
    "engine/candidate/image_provenance.py": "a provenance record read back by the same host, not a generated project",
    "engine/transformation/producers/opensource4j.py": "copies the user's own COBOL source for a third-party tool",
}


def _write_text_calls(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "write_text":
            yield node


def _offenders() -> list[str]:
    found = []
    for path in sorted((REPO / "engine").rglob("*.py")):
        rel = path.relative_to(REPO).as_posix()
        if rel in PLATFORM_DEFAULT_OK:
            continue
        for call in _write_text_calls(path):
            keywords = {k.arg: k.value for k in call.keywords}
            newline = keywords.get("newline")
            if not (isinstance(newline, ast.Constant) and newline.value == "\n"):
                found.append(f"{rel}:{call.lineno}")
    return found


def test_every_engine_writer_emits_lf_regardless_of_platform():
    assert _offenders() == [], "write_text without newline='\\n' in engine/ (generated output must not depend on the OS)"


def test_the_checker_flags_a_platform_dependent_writer(tmp_path):
    bad = tmp_path / "m.py"
    bad.write_text("from pathlib import Path\nPath('x').write_text('a', encoding='utf-8')\n", encoding="utf-8")
    good = tmp_path / "g.py"
    good.write_text("from pathlib import Path\nPath('x').write_text('a', encoding='utf-8', newline='\\n')\n",
                    encoding="utf-8")
    assert len(list(_write_text_calls(bad))) == 1
    call = next(iter(_write_text_calls(bad)))
    assert "newline" not in {k.arg for k in call.keywords}
    assert "newline" in {k.arg for k in next(iter(_write_text_calls(good))).keywords}


def test_the_allowlist_has_no_stale_entries():
    for rel in PLATFORM_DEFAULT_OK:
        path = REPO / rel
        assert path.exists(), rel
        assert list(_write_text_calls(path)), f"{rel} no longer calls write_text: drop it from the allowlist"
