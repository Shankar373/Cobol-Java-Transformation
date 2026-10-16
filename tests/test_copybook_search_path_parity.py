"""BL-035 focused gate: discovery and generation share one copybook search authority.

A copybook found by discovery must be found by generation for the same
tree, in every layout either lane accepts — one deterministic
search-directory builder (``copybook_resolver.copybook_search_dirs``)
feeds both lanes.  Ambiguity stays an explicit error in both lanes, never
a first-match pick; resolver precedence rules are untouched.

Acceptance (docs/BACKLOG.md BL-035):
1. a copybook found by discovery is found by generation for the same tree;
2. ambiguity/missing semantics unchanged (explicit errors);
3. focused tests cover flat, nested and duplicate-name layouts in the gate;
4. no existing resolution test weakened.
"""

from __future__ import annotations

from pathlib import Path

from engine.modernization.capability_analyzer import (
    CapabilityAnalyzer,
    CapabilityLevel,
)
from engine.modernization.modernization_planner import (
    ModernizationPlanner,
    ModernizationStatus,
)
from engine.modernization.pipeline import (
    ModernizationConfig,
    UniversalModernizationPipeline,
)
from engine.transformation.application_discovery import ApplicationDiscovery
from engine.transformation.copybook_model import prepare_application_copybooks
from engine.transformation.copybook_resolver import (
    AmbiguousCopybookError,
    copybook_search_dirs,
    resolve_copybook,
)

MAIN = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. NESTMAIN.\n"
    "       DATA DIVISION.\n"
    "       WORKING-STORAGE SECTION.\n"
    "           COPY OUTER.\n"
    "       PROCEDURE DIVISION.\n"
    '           DISPLAY "NEST[" WS-OUTER "]".\n'
    "           STOP RUN.\n"
)
OUTER = '       01  WS-OUTER PIC X(4) VALUE "NEST".\n'


def _write(tmp_path: Path, files: dict[str, str]) -> Path:
    src = tmp_path / "cobol"
    src.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        target = src / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return src


def _discover(tmp_path: Path, files: dict[str, str]):
    src = _write(tmp_path, files)
    return src, ApplicationDiscovery().discover(src, application_id="bl035")


def _generation(tmp_path: Path, files: dict[str, str]):
    src = _write(tmp_path, files)
    app = ApplicationDiscovery().discover(src, application_id="bl035")
    prep = prepare_application_copybooks(app, source_root=src)
    from engine.transformation.application_generator import ApplicationGenerator
    return ApplicationGenerator().generate(
        prep.application, entrypoint="NESTMAIN", source_root=src,
    )


# ---------------------------------------------------------------------------
# Single authority
# ---------------------------------------------------------------------------


class TestSingleSearchAuthority:
    def test_discovery_delegates_to_the_shared_builder(self, tmp_path):
        src = _write(tmp_path, {
            "NESTMAIN.cob": MAIN, "cb/OUTER.cpy": OUTER,
            "deep/nested/more.cpy": "       01  WS-MORE PIC X(2).\n",
        })
        discovery_dirs = ApplicationDiscovery()._copybook_search_dirs(src)
        assert discovery_dirs == copybook_search_dirs(src)
        # The shared set is the root plus every directory holding a file.
        assert discovery_dirs[0] == src
        assert (src / "cb") in discovery_dirs
        assert (src / "deep" / "nested") in discovery_dirs

    def test_generation_resolver_finds_every_discovered_ref(self, tmp_path):
        """Parity at the resolution layer: discovery RESOLVED == resolver hit."""
        from engine.transformation.copybook_resolver import (
            resolve_application_copybooks,
        )
        _, app = _discover(tmp_path, {
            "NESTMAIN.cob": MAIN,
            "cb/OUTER.cpy": OUTER,
            "a/b/DEEPREC.cpy": "       01  WS-D PIC X(2).\n",
        })
        refs = [
            (u.program_id, cb.copybook_name)
            for u in app.programs for cb in u.copybooks
        ]
        assert refs, "fixture must produce COPY references"
        resolved, missing = resolve_application_copybooks(
            tuple(refs), copybook_search_dirs(tmp_path / "cobol"),
        )
        assert missing == (), missing
        assert len(resolved) == len(refs)


# ---------------------------------------------------------------------------
# Layouts: subdir (the filed defect), nested-subdir, flat
# ---------------------------------------------------------------------------


class TestLayoutParity:
    def test_subdir_layout_resolved_by_both_lanes(self, tmp_path):
        src, app = _discover(tmp_path, {
            "NESTMAIN.cob": MAIN, "cb/OUTER.cpy": OUTER,
        })
        refs = app.programs[0].copybooks
        assert [(r.copybook_name, r.resolution) for r in refs] == [
            ("OUTER", "RESOLVED")
        ]
        report = CapabilityAnalyzer(docker_available=True).analyze(app)
        comp = next(
            c for c in report.components if c.component_type == "COPYBOOK")
        assert comp.level is CapabilityLevel.SUPPORTED
        gen = _generation(tmp_path, {
            "NESTMAIN.cob": MAIN, "cb/OUTER.cpy": OUTER,
        })
        assert gen.success is True, gen.errors

    def test_deep_subdir_layout_resolved_by_both_lanes(self, tmp_path):
        _, app = _discover(tmp_path, {
            "NESTMAIN.cob": MAIN, "a/b/c/OUTER.cpy": OUTER,
        })
        refs = app.programs[0].copybooks
        assert [(r.copybook_name, r.resolution) for r in refs] == [
            ("OUTER", "RESOLVED")
        ]
        gen = _generation(tmp_path, {
            "NESTMAIN.cob": MAIN, "a/b/c/OUTER.cpy": OUTER,
        })
        assert gen.success is True, gen.errors

    def test_flat_layout_unchanged(self, tmp_path):
        src, app = _discover(tmp_path, {"NESTMAIN.cob": MAIN, "OUTER.cpy": OUTER})
        refs = app.programs[0].copybooks
        assert [(r.copybook_name, r.resolution) for r in refs] == [
            ("OUTER", "RESOLVED")
        ]
        gen = _generation(tmp_path, {"NESTMAIN.cob": MAIN, "OUTER.cpy": OUTER})
        assert gen.success is True, gen.errors
        plan = ModernizationPlanner(docker_available=True).plan(
            src, application_id="bl035", entrypoint="NESTMAIN")
        assert plan.overall_status is ModernizationStatus.READY

    def test_subdir_layout_pipeline_succeeds_end_to_end(self, tmp_path):
        src = _write(tmp_path, {"NESTMAIN.cob": MAIN, "cb/OUTER.cpy": OUTER})
        report = UniversalModernizationPipeline(
            ModernizationConfig(
                source_dir=str(src),
                output_dir=str(tmp_path / "out"),
                application_id="bl035",
                entrypoint="NESTMAIN",
                docker_available=True,
            )
        ).execute()
        assert report.generation_success is True, report.generation_errors


# ---------------------------------------------------------------------------
# Ambiguity and precedence semantics unchanged (acceptance 2)
# ---------------------------------------------------------------------------


class TestAmbiguityAndPrecedence:
    def test_duplicate_name_across_dirs_is_ambiguous_in_discovery(self, tmp_path):
        _, app = _discover(tmp_path, {
            "NESTMAIN.cob": MAIN,
            "cb/OUTER.cpy": OUTER,
            "cb2/OUTER.cpy": OUTER,
        })
        refs = app.programs[0].copybooks
        assert [(r.copybook_name, r.resolution) for r in refs] == [
            ("OUTER", "AMBIGUOUS")
        ]

    def test_duplicate_name_fails_generation_explicitly_never_first_match(
        self, tmp_path,
    ):
        gen = _generation(tmp_path, {
            "NESTMAIN.cob": MAIN,
            "cb/OUTER.cpy": OUTER,
            "cb2/OUTER.cpy": OUTER,
        })
        assert gen.success is False
        assert any("OUTER" in e for e in gen.errors), gen.errors

    def test_duplicate_name_blocks_the_plan(self, tmp_path):
        src = _write(tmp_path, {
            "NESTMAIN.cob": MAIN,
            "cb/OUTER.cpy": OUTER,
            "cb2/OUTER.cpy": OUTER,
        })
        plan = ModernizationPlanner(docker_available=True).plan(
            src, application_id="bl035", entrypoint="NESTMAIN")
        assert plan.overall_status is not ModernizationStatus.READY

    def test_resolver_ambiguity_is_an_explicit_error_with_candidates(self, tmp_path):
        root = tmp_path / "tree"
        (root / "cb").mkdir(parents=True)
        (root / "cb2").mkdir(parents=True)
        (root / "cb" / "OUTER.cpy").write_text(OUTER, encoding="utf-8")
        (root / "cb2" / "OUTER.cpy").write_text(OUTER, encoding="utf-8")
        dirs = copybook_search_dirs(root)
        try:
            resolve_copybook("OUTER", dirs, program_id="P")
        except AmbiguousCopybookError as exc:
            assert len(exc.candidates) == 2
        else:  # pragma: no cover - fail loud if ambiguity ever silent-picks
            raise AssertionError("ambiguity must never silently pick a winner")

    def test_extension_precedence_unchanged_in_shared_dirs(self, tmp_path):
        root = tmp_path / "tree"
        root.mkdir()
        (root / "OUTER.cpy").write_text(OUTER, encoding="utf-8")
        (root / "OUTER.cbl").write_text(
            "       01  WS-OUTER PIC X(4).\n", encoding="utf-8")
        resolved = resolve_copybook(
            "OUTER", copybook_search_dirs(root), program_id="P")
        assert resolved.path.suffix.lower() == ".cpy"
