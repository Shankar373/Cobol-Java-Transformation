"""Import-lint (Layer 3 acceptance criterion 3): the engine must not re-parse COBOL structure that discovery parses,
and the estate view must derive only from the discovery graph.

Two checks, both static (AST), so they hold whatever the fixtures are:

* **estate view is graph-only** - nothing under ``engine/estate`` imports a source parser or a second dependency
  scanner, and ``build_estate_from_graph`` reaches discovery only through ``enterprise.discovery.graph_view``;
  ``graph_view.estate_from_graph`` itself opens no file.
* **no undeclared structure parsing in the engine** - a module that compiles a regular expression over COBOL
  structure keywords (``CALL``, ``COPY``, ``PERFORM``, ``PROGRAM-ID``, ``REPLACING``, ``EXEC SQL|CICS|DLI``, ``GO TO``)
  must be listed in :data:`ALLOWED_STRUCTURE_PARSERS` with a justification.  The list is the honest inventory of what
  is still parsed twice; it fails when an entry goes stale (the module no longer parses) so it can only shrink.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "engine"

_STRUCTURE = re.compile(r"\b(CALL|COPY|PERFORM|PROGRAM-ID|REPLACING|GO\s*TO|EXEC\s+(?:SQL|CICS|DLI))\b", re.IGNORECASE)
_RE_FUNCTIONS = frozenset({"compile", "search", "match", "fullmatch", "finditer", "findall", "sub", "subn", "split"})
_PATTERN_NAME = re.compile(r"(?:RE|REGEX|PATTERN|PAT)(?:_|$)|_RE\b|_PATTERN|_REGEX", re.IGNORECASE)

#: module (path relative to ``engine/``) -> why it still parses COBOL structure itself.  Every entry is a debt or a
#: deliberate exception; an empty string is rejected.
ALLOWED_STRUCTURE_PARSERS: dict[str, str] = {
    "transformation/application_discovery.py": (
        "CALL/COPY occurrence scan builds the ProgramCall/CopybookReference IR consumed by generation.  Not yet "
        "delegated to enterprise.discovery.scan_cobol because (1) classify_call diverts CICS/MQ/IMS/LE entry points "
        "out of 'calls' while the capability analyzer still needs them there, (2) the discovery tokenizer does not "
        "treat a fixed-format floating '*>' comment as a comment and so reports a phantom COPY/CALL, (3) the IR keeps "
        "the source spelling and the USING arguments.  The estate and decomposition no longer read this module."),
    "transformation/cobol_parser.py": (
        "The full COBOL parser builds the CobolProgram IR (data layouts, paragraphs, statements) that code generation "
        "needs; discovery records only a dependency graph and has no IR.  COPY/CALL/PERFORM are read here to be "
        "lowered or expanded, not to discover dependencies."),
    "transformation/copybook_model.py": (
        "Applies COPY ... REPLACING to copybook text (text substitution for expansion).  Discovery records the "
        "REPLACING pairs (cobol_structure.parse_replacing) but deliberately does not expand them."),
    "transformation/producer.py": (
        "The single-source producer refuses a COPY it cannot expand (it has no copybook path); a guard on the text it "
        "was handed, not a dependency scan."),
    "transformation/semantic_capability.py": (
        "Classifies the capability of a PERFORM form from source for the capability analyzer; a verdict, no edge."),
    "transformation/next_sentence.py": "Statement-boundary scan for NEXT SENTENCE lowering; consumes statements, no edge.",
    "transformation/exec_sql.py": "Parses WHENEVER ... GO TO inside EXEC SQL for lowering; discovery records table access only.",
    "transformation/sql_parser.py": "Parses EXEC SQL statement bodies (including CALL of a stored procedure) into SQL IR for lowering.",
    "transformation/subsystem_calls.py": "Recognises CALL forms to IMS/MQ/DB2 stubs to lower them (statement shapes), not to find edges.",
    "transformation/cics_java_mapping.py": (
        "The CICS lane extracts EXEC CICS blocks and the PROGRAM-ID of the source it was handed to lower them; "
        "discovery records the CICS resources, not the command bodies."),
    "modernization/capability_analyzer.py": (
        "Source-scan capability classification (UNSUPPORTED/PARTIAL) of features the IR cannot carry (COPY/REPLACE "
        "forms); a verdict, not a dependency edge."),
    "modernization/external_dependency_edges.py": (
        "DB2/MQ/IMS/CICS ledger: proof-state classification of embedded-subsystem statements.  The estate takes "
        "which program touches which resource from the graph and uses this ledger only for the state and the reason."),
    "jcl/job_lane.py": (
        "PROGRAM-ID lookup to map a JCL EXEC PGM= to a source file when running a job against generated code; "
        "the graph's program nodes carry the path but this lane runs without a discovery graph.  Debt: switch to graph_view."),
    "oracle/docker_adapter.py": "Oracle harness reads the PROGRAM-ID of the program under test to name the build; not a dependency scan.",
}


def _engine_modules() -> list[Path]:
    return sorted(p for p in ENGINE.rglob("*.py") if "__pycache__" not in p.parts)


def _string_parts(node: ast.AST) -> list[str]:
    return [n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def structure_patterns(path: Path) -> list[tuple[int, str]]:
    """``(line, pattern)`` for every regex in ``path`` that is written over COBOL structure keywords."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "re" \
                and node.func.attr in _RE_FUNCTIONS and node.args:
            found.extend((node.lineno, text) for text in _string_parts(node.args[0]) if _STRUCTURE.search(text))
        elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str) and _STRUCTURE.search(node.value.value) \
                and any(isinstance(t, ast.Name) and _PATTERN_NAME.search(t.id) for t in node.targets):
            found.append((node.lineno, node.value.value))
    return found


def _relative(path: Path) -> str:
    return path.relative_to(ENGINE).as_posix()


def test_every_justification_is_a_real_sentence():
    for module, reason in ALLOWED_STRUCTURE_PARSERS.items():
        assert len(reason.split()) >= 4, f"{module}: justify why it still parses COBOL structure"
        assert (ENGINE / module).is_file(), f"{module} no longer exists; remove it from the allowlist"


def test_no_engine_module_parses_cobol_structure_without_a_declared_reason():
    offenders = {_relative(p): structure_patterns(p) for p in _engine_modules()}
    undeclared = {m: hits[:2] for m, hits in offenders.items() if hits and m not in ALLOWED_STRUCTURE_PARSERS}
    assert not undeclared, (
        "these engine modules compile a regex over COBOL structure (CALL/COPY/PERFORM/PROGRAM-ID/REPLACING/EXEC) "
        "without an entry in ALLOWED_STRUCTURE_PARSERS; read the graph instead, or declare why they must parse:\n"
        + "\n".join(f"  {m}: {hits}" for m, hits in sorted(undeclared.items())))


def test_the_allowlist_has_no_stale_entries():
    stale = [m for m in ALLOWED_STRUCTURE_PARSERS if not structure_patterns(ENGINE / m)]
    assert not stale, f"these modules no longer parse COBOL structure; delete their allowlist entries: {stale}"


# --- format/dialect re-detection is forbidden ----------------------------------------------
# The engine must consume the single reader through ``engine.transformation.source_format``
# (the engine face).  Importing format detection from ``enterprise.discovery.cobol_text``
# directly is re-detection and is forbidden outside the allowlist below.

#: Engine modules that may import the discovery reader directly, with justification.
ALLOWED_FORMAT_READERS: dict[str, str] = {
    "transformation/source_format.py": (
        "The engine face of the single reader: wraps enterprise.discovery.cobol_text.read_source "
        "and exposes compiler_visible_text/detect_source_format to the rest of the engine."),
    "transformation/cobol_parser.py": (
        "Criterion 6 pre-parse refusal: reads the reader's conditional-compilation verdict "
        "(read_source().conditional) to refuse an unevaluated >>IF by name.  Consumes the "
        "verdict, never re-derives format state."),
}


def _format_reader_imports(path: Path) -> list[tuple[int, str]]:
    """``(line, module)`` for every import of the discovery reader's format detection."""
    out: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module == "enterprise.discovery.cobol_text":
            out.append((node.lineno, node.module))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "enterprise.discovery.cobol_text":
                    out.append((node.lineno, alias.name))
    return out


def test_no_engine_module_imports_the_discovery_reader_without_a_declared_reason():
    offenders = {}
    for p in _engine_modules():
        rel = _relative(p)
        hits = _format_reader_imports(p)
        if hits and rel not in ALLOWED_FORMAT_READERS:
            offenders[rel] = hits
    assert not offenders, (
        "these engine modules import enterprise.discovery.cobol_text (format re-detection) "
        "without an entry in ALLOWED_FORMAT_READERS:\n"
        + "\n".join(f"  {m}: {h}" for m, h in sorted(offenders.items())))


def test_the_format_reader_allowlist_has_no_stale_entries():
    stale = [m for m in ALLOWED_FORMAT_READERS if not _format_reader_imports(ENGINE / m)]
    assert not stale, f"these modules no longer import the discovery reader; delete their entries: {stale}"


# --- the estate view is graph-only ---------------------------------------------------------------------------------

#: What ``engine/estate`` may never import: a source parser or a second dependency scanner.
_FORBIDDEN_FOR_ESTATE = ("engine.transformation", "engine.modernization.external_dependency_edges",
                         "engine.vsam", "api.ingestion")


def _imports(path: Path) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module:
            out.append((node.lineno, node.module))
        elif isinstance(node, ast.Import):
            out.extend((node.lineno, alias.name) for alias in node.names)
    return out


def test_engine_estate_imports_no_parser_and_reaches_discovery_only_through_graph_view():
    for path in sorted((ENGINE / "estate").glob("*.py")):
        assert not structure_patterns(path), f"{path.name} must not parse COBOL structure"
        for line, module in _imports(path):
            assert not module.startswith(_FORBIDDEN_FOR_ESTATE), f"{path.name}:{line} imports {module}"
            if module.startswith("enterprise.discovery"):
                assert module == "enterprise.discovery.graph_view", f"{path.name}:{line} imports {module}"


def test_estate_from_graph_reads_no_file_and_no_source():
    path = ROOT / "enterprise" / "discovery" / "graph_view.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    pure = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "estate_from_graph")
    called = {n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "")
              for n in ast.walk(pure) if isinstance(n, ast.Call)}
    assert not called & {"open", "read_text", "read_bytes", "rglob", "scan_cobol", "scan_file", "build_graph"}, called
    # And no module-level helper it uses touches the filesystem either (the file readers are separate functions).
    helpers = {n.name for n in tree.body if isinstance(n, ast.FunctionDef) and n.name.startswith(("_executes", "_job_", "_copybook", "_datasets", "_binding", "_subsystems", "_program_target", "_classify_target"))}
    for name in helpers:
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
        names = {n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "")
                 for n in ast.walk(fn) if isinstance(n, ast.Call)}
        assert not names & {"open", "read_text", "read_bytes", "rglob", "scan_cobol", "scan_file"}, (name, names)


def test_the_api_estate_path_builds_from_the_graph():
    source = (ROOT / "api" / "estate.py").read_text(encoding="utf-8")
    compute = source[source.index("def compute_estate"):]
    assert "build_estate_from_graph" in compute and "graph_from_directory" in compute
    assert "ApplicationDiscovery" not in compute and "discover_application" not in compute
