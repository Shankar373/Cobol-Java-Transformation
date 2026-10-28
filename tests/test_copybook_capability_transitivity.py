"""BL-039 focused gate: capability scan is transitive into nested copybooks.

The verdict must cover everything materialization merges (§14/§20): a
construct inside a nested copybook lowers the COPYBOOK component's level
with a reason naming the nested file, and a nested target generation
cannot materialize fails the component closed with the same message
generation surfaces — the expanded-scan result can never contradict
generation.

Acceptance (docs/BACKLOG.md BL-039):
1. a nested copybook containing a registry non-SUPPORTED construct lowers
   the COPYBOOK verdict with a reason naming the nested file;
2. expanded-scan results never contradict generation;
3. focused tests join the gate;
4. no existing resolution/copybook test weakened.
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
CLEAN_OUTER = '       01  WS-OUTER PIC X(4) VALUE "NEST".\n'
REDEFINES_INNER = (
    "       01  WS-GRP.\n"
    "         02  WS-A PIC X(4).\n"
    "         02  WS-B REDEFINES WS-A PIC 9(4).\n"
)


def _write(tmp_path: Path, files: dict[str, str]) -> Path:
    src = tmp_path / "cobol"
    src.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        target = src / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return src


def _copybook_component(tmp_path: Path, files: dict[str, str]):
    src = _write(tmp_path, files)
    app = ApplicationDiscovery().discover(src, application_id="bl039")
    report = CapabilityAnalyzer(docker_available=True).analyze(
        app, source_root=src
    )
    comp = next(
        c for c in report.components if c.component_type == "COPYBOOK"
    )
    return src, app, comp


def _generation(tmp_path: Path, files: dict[str, str]):
    src = _write(tmp_path, files)
    app = ApplicationDiscovery().discover(src, application_id="bl039")
    prep = prepare_application_copybooks(app, source_root=src)
    return ApplicationGenerator().generate(
        prep.application, entrypoint="NM", source_root=src
    )


# ---------------------------------------------------------------------------
# Acceptance 1: nested constructs lower the verdict, naming the nested file
# ---------------------------------------------------------------------------


class TestNestedConstructsAreClassified:
    def test_nested_redefines_lowers_verdict_and_names_nested_file(self, tmp_path):
        _, _, comp = _copybook_component(tmp_path, {
            "NM.cob": MAIN,
            "OUTER.cpy": "       COPY INNER.\n",
            "INNER.cpy": REDEFINES_INNER,
        })
        # REDEFINES registry level is PARTIAL since the certified overlay
        # subset landed (semantic_capability.CONSTRUCT_REGISTRY; lowering
        # proven by test_redefines_lowering.py + structural oracle proof).
        # PARTIAL is still non-SUPPORTED, so BL-039's lowering contract holds.
        assert comp.level is CapabilityLevel.PARTIAL
        assert "REDEFINES" in comp.reason
        assert "INNER" in comp.reason, comp.reason

    def test_nested_scan_follows_shared_search_dirs_in_subdir_layout(self, tmp_path):
        _, _, comp = _copybook_component(tmp_path, {
            "NM.cob": MAIN,
            "cb/OUTER.cpy": "       COPY INNER.\n",
            "cb/INNER.cpy": REDEFINES_INNER,
        })
        # REDEFINES registry level = PARTIAL (certified overlay subset).
        assert comp.level is CapabilityLevel.PARTIAL
        assert "INNER" in comp.reason, comp.reason

    def test_top_level_construct_attributed_to_top_file_only(self, tmp_path):
        _, _, comp = _copybook_component(tmp_path, {
            "NM.cob": MAIN,
            "OUTER.cpy": REDEFINES_INNER,
        })
        # REDEFINES registry level = PARTIAL (certified overlay subset).
        assert comp.level is CapabilityLevel.PARTIAL
        assert "REDEFINES" in comp.reason
        assert "nested" not in comp.reason, comp.reason

    def test_clean_nested_copybook_stays_supported_with_nested_note(self, tmp_path):
        _, _, comp = _copybook_component(tmp_path, {
            "NM.cob": MAIN,
            "OUTER.cpy": "       COPY INNER.\n",
            "INNER.cpy": CLEAN_OUTER,
        })
        assert comp.level is CapabilityLevel.SUPPORTED, comp.reason
        assert "nested" in comp.reason, comp.reason

    def test_flat_copybook_reason_unchanged(self, tmp_path):
        _, _, comp = _copybook_component(tmp_path, {
            "NM.cob": MAIN,
            "OUTER.cpy": CLEAN_OUTER,
        })
        assert comp.level is CapabilityLevel.SUPPORTED
        assert comp.reason == (
            "Copybook resolved and contains no unsupported constructs"
        )


# ---------------------------------------------------------------------------
# Acceptance 2: capability never contradicts generation
# ---------------------------------------------------------------------------


class TestCapabilityGenerationAgreement:
    def test_materializable_nested_copybook_generates(self, tmp_path):
        gen = _generation(tmp_path, {
            "NM.cob": MAIN,
            "OUTER.cpy": "       COPY INNER.\n",
            "INNER.cpy": CLEAN_OUTER,
        })
        assert gen.success is True, gen.errors

    def test_missing_nested_target_fails_component_and_generation_identically(
        self, tmp_path,
    ):
        files = {
            "NM.cob": MAIN,
            "OUTER.cpy": "       COPY NO-SUCH-NESTED.\n",
        }
        _, _, comp = _copybook_component(tmp_path, files)
        assert comp.level is CapabilityLevel.UNSUPPORTED
        assert "NO-SUCH-NESTED" in comp.reason, comp.reason
        gen = _generation(tmp_path, files)
        assert gen.success is False
        assert any("NO-SUCH-NESTED" in e for e in gen.errors), gen.errors
        # The component reason carries the same message generation surfaces.
        assert "Missing COPY target: NO-SUCH-NESTED" in comp.reason

    def test_cyclic_nested_target_fails_component_closed(self, tmp_path):
        _, _, comp = _copybook_component(tmp_path, {
            "NM.cob": MAIN,
            "OUTER.cpy": "       COPY OUTER.\n",
        })
        assert comp.level is CapabilityLevel.UNSUPPORTED
        assert "Cyclic" in comp.reason or "OUTER" in comp.reason, comp.reason


# ---------------------------------------------------------------------------
# The per-file collector itself (BL-039 support surface)
# ---------------------------------------------------------------------------


class TestCollector:
    def test_collector_returns_top_then_nested_in_depth_first_order(self, tmp_path):
        src = _write(tmp_path, {
            "NM.cob": MAIN,
            "OUTER.cpy": "       COPY INNER.\n",
            "INNER.cpy": CLEAN_OUTER,
        })
        files, diagnostics = collect_copybook_texts(
            src / "OUTER.cpy", (src,)
        )
        assert [f.stem.upper() for f, _ in files] == ["OUTER", "INNER"]
        assert [d for d in diagnostics if d.level == "ERROR"] == []

    def test_collector_never_repeats_a_file_on_a_cycle(self, tmp_path):
        src = _write(tmp_path, {
            "NM.cob": MAIN,
            "OUTER.cpy": "       COPY OUTER.\n",
        })
        files, diagnostics = collect_copybook_texts(
            src / "OUTER.cpy", (src,)
        )
        assert [f.stem.upper() for f, _ in files] == ["OUTER"]
        assert any(d.code == "COPYBOOK_CYCLE" for d in diagnostics)
