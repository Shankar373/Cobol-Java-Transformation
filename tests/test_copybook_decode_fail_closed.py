"""BL-056 focused gate: decode failures fail closed as COPYBOOK_UNREADABLE.

The copybook lanes guarded ``read_text(encoding="utf-8")`` with
``except OSError`` only, but ``UnicodeDecodeError`` is a ``ValueError`` —
a non-UTF-8 copybook therefore escaped the documented fail-closed
contract and crashed both lanes with a raw exception, while the
capability analyzer's lenient ``errors="replace"`` reader could read the
very same bytes without complaint (lane disagreement on one file).

Acceptance (docs/BACKLOG.md BL-056):
1. generation/materializer lane: binary copybook ⇒ ``COPYBOOK_UNREADABLE``
   ERROR diagnostic for the top level *and* a nested target; generation
   fails closed with the message surfaced verbatim (never a crash);
2. capability lane: the same bytes ⇒ COPYBOOK component UNSUPPORTED —
   never SUPPORTED, never a crash — with the decode failure named, and a
   decode failure takes the analyzer's *read-failure* path (same
   treatment as an OSError on the same file);
3. the shared BL-039 reader ``collect_copybook_texts`` returns the
   ``COPYBOOK_UNREADABLE`` diagnostic instead of raising, and the
   unreadable text is never scanned;
4. lane parity: the analyzer's reason quotes generation's exact
   unreadable message for the same bytes;
5. no existing copybook test weakened.
"""

from __future__ import annotations

from pathlib import Path

from engine.modernization.capability_analyzer import (
    CapabilityAnalyzer,
    CapabilityLevel,
)
from engine.transformation.application_discovery import ApplicationDiscovery
from engine.transformation.application_generator import ApplicationGenerator
from engine.transformation.copybook_model import (
    collect_copybook_texts,
    prepare_application_copybooks,
)

MAIN = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. NM.\n"
    "       DATA DIVISION.\n"
    "       WORKING-STORAGE SECTION.\n"
    "           COPY OUTER.\n"
    "       PROCEDURE DIVISION.\n"
    "           STOP RUN.\n"
)
OUTER_NESTS_INNER = "       COPY INNER.\n"
# 0xff is never a valid UTF-8 byte; 0xc3 0x28 breaks a continuation.
BINARY_COPYBOOK = b"\xff\xfe\x00binary\xc3\x28"


def _write(tmp_path: Path, text_files: dict[str, str],
           binary_files: dict[str, bytes] | None = None) -> Path:
    src = tmp_path / "cobol"
    src.mkdir(parents=True, exist_ok=True)
    for name, text in text_files.items():
        (src / name).write_text(text, encoding="utf-8")
    for name, data in (binary_files or {}).items():
        (src / name).write_bytes(data)
    return src


def _discovered(tmp_path: Path, text_files: dict[str, str],
                binary_files: dict[str, bytes] | None = None):
    src = _write(tmp_path, text_files, binary_files)
    app = ApplicationDiscovery().discover(src, application_id="bl056")
    return src, app


def _copybook_component(report):
    return next(c for c in report.components if c.component_type == "COPYBOOK")


# ---------------------------------------------------------------------------
# Generation / materializer lane
# ---------------------------------------------------------------------------


class TestMaterializerLane:
    def test_binary_top_level_copybook_yields_copybook_unreadable(self, tmp_path):
        src, app = _discovered(
            tmp_path, {"NM.cob": MAIN}, {"OUTER.cpy": BINARY_COPYBOOK}
        )
        prep = prepare_application_copybooks(app, source_root=src)
        unreadable = [
            d for d in prep.diagnostics if d.code == "COPYBOOK_UNREADABLE"
        ]
        assert prep.has_errors, prep.diagnostics
        assert unreadable, prep.diagnostics
        assert "OUTER" in unreadable[0].message
        assert "codec can't decode" in unreadable[0].message

    def test_generation_fails_closed_with_unreadable_message_verbatim(self, tmp_path):
        src, app = _discovered(
            tmp_path, {"NM.cob": MAIN}, {"OUTER.cpy": BINARY_COPYBOOK}
        )
        result = ApplicationGenerator().generate(
            app, entrypoint="NM", source_root=src
        )
        assert result.success is False
        assert any(
            "OUTER" in err and "codec can't decode" in err
            for err in result.errors
        ), result.errors

    def test_binary_nested_target_yields_copybook_unreadable_naming_target(self, tmp_path):
        src, app = _discovered(
            tmp_path,
            {"NM.cob": MAIN, "OUTER.cpy": OUTER_NESTS_INNER},
            {"INNER.cpy": BINARY_COPYBOOK},
        )
        prep = prepare_application_copybooks(app, source_root=src)
        unreadable = [
            d for d in prep.diagnostics if d.code == "COPYBOOK_UNREADABLE"
        ]
        assert prep.has_errors, prep.diagnostics
        assert unreadable, prep.diagnostics
        assert any("INNER" in d.message for d in unreadable), unreadable
        assert any("codec can't decode" in d.message for d in unreadable), unreadable


# ---------------------------------------------------------------------------
# Capability-analysis lane
# ---------------------------------------------------------------------------


class TestCapabilityLane:
    def test_binary_top_level_copybook_is_unsupported_read_failure_path(self, tmp_path):
        src, app = _discovered(
            tmp_path, {"NM.cob": MAIN}, {"OUTER.cpy": BINARY_COPYBOOK}
        )
        report = CapabilityAnalyzer(docker_available=True).analyze(
            app, source_root=src
        )
        comp = _copybook_component(report)
        # Same treatment as an OSError read failure on the same file.
        assert comp.level is CapabilityLevel.UNSUPPORTED, comp.reason
        assert "could not be read" in comp.reason, comp.reason
        assert "OUTER" in comp.reason
        assert "codec can't decode" in comp.reason

    def test_binary_nested_target_fails_component_closed_naming_target(self, tmp_path):
        src, app = _discovered(
            tmp_path,
            {"NM.cob": MAIN, "OUTER.cpy": OUTER_NESTS_INNER},
            {"INNER.cpy": BINARY_COPYBOOK},
        )
        report = CapabilityAnalyzer(docker_available=True).analyze(
            app, source_root=src
        )
        comp = _copybook_component(report)
        assert comp.level is CapabilityLevel.UNSUPPORTED, comp.reason
        assert "INNER" in comp.reason, comp.reason
        assert "codec can't decode" in comp.reason

    def test_analyzer_quotes_generation_unreadable_message_for_same_bytes(self, tmp_path):
        """Lane parity: one file, one message — the analyzer quotes generation."""
        src, app = _discovered(
            tmp_path,
            {"NM.cob": MAIN, "OUTER.cpy": OUTER_NESTS_INNER},
            {"INNER.cpy": BINARY_COPYBOOK},
        )
        prep = prepare_application_copybooks(app, source_root=src)
        gen_msg = next(m for m in prep.error_messages() if "INNER" in m)
        report = CapabilityAnalyzer(docker_available=True).analyze(
            app, source_root=src
        )
        comp = _copybook_component(report)
        assert comp.level is CapabilityLevel.UNSUPPORTED, comp.reason
        assert gen_msg in comp.reason, (gen_msg, comp.reason)


# ---------------------------------------------------------------------------
# Shared BL-039 reader
# ---------------------------------------------------------------------------


def test_collect_copybook_texts_top_level_decode_failure_returns_diagnostic(tmp_path):
    src = _write(tmp_path, {}, {"OUTER.cpy": BINARY_COPYBOOK})
    files, diagnostics = collect_copybook_texts(src / "OUTER.cpy", (src,))
    unreadable = [
        d for d in diagnostics if d.code == "COPYBOOK_UNREADABLE"
    ]
    assert unreadable, diagnostics
    assert "codec can't decode" in unreadable[0].message
    assert not files  # unreadable text is never scanned, not even as ""


def test_collect_copybook_texts_nested_decode_failure_returns_diagnostic(tmp_path):
    src = _write(
        tmp_path,
        {"OUTER.cpy": OUTER_NESTS_INNER},
        {"INNER.cpy": BINARY_COPYBOOK},
    )
    files, diagnostics = collect_copybook_texts(src / "OUTER.cpy", (src,))
    unreadable = [
        d for d in diagnostics if d.code == "COPYBOOK_UNREADABLE"
    ]
    assert unreadable, diagnostics
    assert "INNER" in unreadable[0].message
    stems = [p.stem.upper() for p, _ in files]
    assert "OUTER" in stems
    assert "INNER" not in stems  # unreadable file's text is absent
