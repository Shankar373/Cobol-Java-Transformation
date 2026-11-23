"""Behavioural single-reader lint (Layer 4 contract: ONE reader of COBOL source text).

``docs/architecture/LAYER_MODEL.md`` says no module may re-detect dialect or reference format.
``test_engine_graph_lint.py`` only checks *imports* of ``cobol_text`` and regexes over structure keywords; this
module checks the *behaviour*: an ``engine/`` or ``api/`` module that re-derives comment / indicator / column /
conditional-compilation logic from raw source text is re-reading COBOL.  Static (AST), deterministic.

Rules R1-R7 (each is proven by a mutation test below: an offending synthetic module is flagged, a clean one is not):

``R1 reader-literal``
    A string literal (docstrings excluded) that is, or contains, a reference-format / directive marker:
    ``"*>"`` (floating comment), ``">>"`` followed by a word (``">>IF"``, ``">>SOURCE"``), ``"$SET"``,
    ``"SOURCEFORMAT"``.  Only the reader knows how those are scoped (quotes, columns, tabs, dead branches).
``R2 column-slice``
    A subscript on a line-like name (``line``, ``raw``, ``cleaned``, ``stripped``, ``lines[i]``, a loop variable
    over ``X.splitlines()``, ...) with a constant index or slice bound of 6, 7 or 72 (``line[6]``, ``line[6:7]``,
    ``line[:72]``, ``line[7:72]``, ``raw[6:]``): the sequence area, the indicator column, the program-text area or
    the identification area.
``R3 star-comment``
    ``startswith("*")`` (or a tuple containing ``"*"``) on a line-like name, optionally behind
    ``strip/lstrip/rstrip/upper/lower``: a hand-rolled full-line comment test.
``R4 splitlines-slicing``
    A loop (or comprehension) over ``<source-like>.splitlines()`` / ``.split("\\n")`` - directly, through a name
    assigned from one, or through ``enumerate`` - whose loop variable is column-sliced (R2 bounds) or tested with
    ``startswith("*")``, whatever the variable is called.
``R5 dialect-redetection``
    A ``"-std=..."`` literal (``-std=`` is the dialect -> GnuCOBOL standard selection), or any reference to
    ``DIALECT_SIGNALS`` / ``std_for_dialect`` (the dialect signal table and the one dialect->standard mapping).
    The dialect decision belongs to ``enterprise.discovery`` (scan_cobol / compilers / dialect_profile) only.
``R7 sequence-area-regex``
    A string literal that is a regular expression over the fixed-format sequence-number area (columns 1-6):
    backslash-d repeated six times, a ``[digit space]{6}`` class, or ``.{6}`` followed by an indicator class.  Re-slicing the six-column prefix by
    regex is exactly the column logic the reader owns.
``R6 one-profile-builder``
    ``build_profiles`` may be referenced (called or imported) only from ``enterprise/discovery/report.py`` and
    ``enterprise/discovery/dialect_profile.py`` itself; tests are excluded.

Scope: ``engine/`` and ``api/`` for R1-R5 (the sanctioned reader modules ``engine/transformation/source_format.py``
and ``source_positions.py`` are excluded); the whole non-test tree for R6.  JCL is not COBOL: ``startswith("*")`` is
only a line-like test on the names in ``_LINE_NAMES`` so JCL ``content``/``operands`` handling is not flagged.

``INVENTORY`` is the honest list of what still re-derives source text.  Shrink-only: a new offender fails, a stale
entry (module no longer offends) fails, and every entry needs a justification of at least four words.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

SANCTIONED_READERS = frozenset({"engine/transformation/source_format.py", "engine/transformation/source_positions.py"})
PROFILE_BUILDER_HOMES = frozenset({"enterprise/discovery/report.py", "enterprise/discovery/dialect_profile.py"})

_LINE_NAMES = frozenset({
    "line", "raw", "raw_line", "cleaned", "cleaned_line", "stripped", "upper", "nxt", "body", "ln",
    "src_line", "source_line", "cobol_line", "physical", "l", "u", "row", "card"})
_SOURCE_NAMES = re.compile(r"^(source|src|text|cobol|cobol_text|source_text|code|raw_text|content|program|lines?)$")
_COLUMN_BOUNDS = frozenset({6, 7, 72})
_PASSTHROUGH = frozenset({"strip", "lstrip", "rstrip", "upper", "lower"})
_DIRECTIVE_WORDS = r"(?:IF|ELSE|END-IF|EVALUATE|SOURCE|DEFINE|SET|PAGE|TURN|CALL-CONVENTION|LISTING|D)\b"
_MARKER_LITERAL = re.compile(
    r"\\\*>|(?<![\w\])])\*>|(?:^|[\s\"'(])>>\s*" + _DIRECTIVE_WORDS + r"|\$SET\b|\bSOURCEFORMAT\b", re.IGNORECASE)
_SEQUENCE_AREA = re.compile(r"\\d\{6\}|\[\\d ?\]\{6\}|\.\{6\}\[")
_LINE_LISTS = frozenset({"lines", "rows", "cards"})
_DIALECT_NAMES = frozenset({"DIALECT_SIGNALS", "std_for_dialect"})


def _docstring_nodes(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                ids.add(id(first.value))
    return ids


def _base_name(node: ast.AST) -> str:
    """The name a (possibly method-chained / indexed) expression ultimately reads from."""
    while True:
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in _PASSTHROUGH:
            node = node.func.value
        elif isinstance(node, ast.Subscript) and not isinstance(node.slice, ast.Slice) \
                and not isinstance(node.slice, ast.Constant):
            node = node.value          # lines[i] -> lines
        elif isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return node.attr
        else:
            return ""


def _bound_hit(sl: ast.AST) -> bool:
    if isinstance(sl, ast.Constant):
        return isinstance(sl.value, int) and not isinstance(sl.value, bool) and sl.value in _COLUMN_BOUNDS
    if isinstance(sl, ast.Slice):
        bounds = [b for b in (sl.lower, sl.upper) if b is not None]
        return any(isinstance(b, ast.Constant) and isinstance(b.value, int) and b.value in _COLUMN_BOUNDS for b in bounds) \
            and all(isinstance(b, ast.Constant) for b in bounds)
    return False


def _is_split_lines(node: ast.AST) -> bool:
    """``X.splitlines()`` / ``X.split("\\n")`` over a source-like name."""
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
        return False
    attr = node.func.attr
    if attr == "splitlines" or (attr == "split" and node.args and isinstance(node.args[0], ast.Constant)
                                and node.args[0].value == "\n"):
        return bool(_SOURCE_NAMES.match(_base_name(node.func.value)))
    return False


def _iter_names(node: ast.AST) -> str:
    """Name of the collection a ``for`` iterates (through ``enumerate``), or ``""``."""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "enumerate" and node.args:
        node = node.args[0]
    return node.id if isinstance(node, ast.Name) else ""


def _target_names(target: ast.AST) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, ast.Tuple):
        return [n for elt in target.elts for n in _target_names(elt)]
    return []


def _star_test(node: ast.Call) -> bool:
    if not (isinstance(node.func, ast.Attribute) and node.func.attr == "startswith" and node.args):
        return False
    arg = node.args[0]
    values = [arg] if isinstance(arg, ast.Constant) else list(arg.elts) if isinstance(arg, ast.Tuple) else []
    return any(isinstance(v, ast.Constant) and v.value == "*" for v in values)


def _split_line_names(tree: ast.AST) -> set[str]:
    """Names assigned from a source ``splitlines()``/``split("\\n")`` anywhere in the module."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and _is_split_lines(node.value):
            names.update(n for t in node.targets for n in _target_names(t))
    return names


def _loop_vars(tree: ast.AST, collections: set[str]) -> set[str]:
    """Loop/comprehension variables iterating a source line sequence (R4)."""
    out: set[str] = set()
    for node in ast.walk(tree):
        loops = [(node.target, node.iter)] if isinstance(node, (ast.For, ast.comprehension)) else []
        for target, it in loops:
            probe = it.args[0] if isinstance(it, ast.Call) and isinstance(it.func, ast.Name) \
                and it.func.id == "enumerate" and it.args else it
            if _is_split_lines(probe) or _iter_names(it) in collections:
                out.update(_target_names(target))
    return out


def reader_violations(source: str) -> list[tuple[int, str, str]]:
    """``(line, rule, detail)`` for every single-reader rule R1-R5 that ``source`` breaks."""
    tree = ast.parse(source)
    docstrings = _docstring_nodes(tree)
    loop_vars = _loop_vars(tree, _split_line_names(tree))
    found: list[tuple[int, str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            if _MARKER_LITERAL.search(node.value):
                found.append((node.lineno, "R1 reader-literal", repr(node.value[:40])))
            if _SEQUENCE_AREA.search(node.value):
                found.append((node.lineno, "R7 sequence-area-regex", repr(node.value[:40])))
            if node.value.startswith("-std="):
                found.append((node.lineno, "R5 dialect-redetection", repr(node.value[:40])))
        elif isinstance(node, ast.JoinedStr) and node.values and isinstance(node.values[0], ast.Constant) \
                and str(node.values[0].value).startswith("-std="):
            found.append((node.lineno, "R5 dialect-redetection", "f'-std=...'"))
        elif isinstance(node, ast.Subscript) and _bound_hit(node.slice):
            base = _base_name(node.value)
            if base in _LINE_NAMES or base in loop_vars or (isinstance(node.value, ast.Subscript) and base in _LINE_LISTS):
                found.append((node.lineno, "R4 splitlines-slicing" if base in loop_vars and base not in _LINE_NAMES
                              else "R2 column-slice", f"{base}[...]"))
        elif isinstance(node, ast.Call) and _star_test(node):
            base = _base_name(node.func.value)
            if base in _LINE_NAMES or base in loop_vars or base in _LINE_LISTS:
                found.append((node.lineno, "R4 splitlines-slicing" if base in loop_vars and base not in _LINE_NAMES
                              else "R3 star-comment", f"{base}.startswith('*')"))
        elif isinstance(node, (ast.Name, ast.Attribute)):
            name = node.id if isinstance(node, ast.Name) else node.attr
            if name in _DIALECT_NAMES:
                found.append((node.lineno, "R5 dialect-redetection", name))
        elif isinstance(node, (ast.ImportFrom, ast.Import)):
            for alias in node.names:
                if alias.name in _DIALECT_NAMES:
                    found.append((node.lineno, "R5 dialect-redetection", alias.name))
    return sorted(set(found))


def profile_builder_references(source: str) -> list[int]:
    """Lines that reference ``build_profiles`` (call, attribute, import)."""
    hits: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Name) and node.id == "build_profiles":
            hits.append(node.lineno)
        elif isinstance(node, ast.Attribute) and node.attr == "build_profiles":
            hits.append(node.lineno)
        elif isinstance(node, (ast.ImportFrom, ast.Import)) and any(a.name == "build_profiles" for a in node.names):
            hits.append(node.lineno)
    return sorted(set(hits))


def _scoped_modules(*roots: str) -> list[Path]:
    paths: list[Path] = []
    for root in roots:
        paths.extend(p for p in (ROOT / root).rglob("*.py") if "__pycache__" not in p.parts)
    return sorted(paths)


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def current_offenders() -> dict[str, list[tuple[int, str, str]]]:
    out: dict[str, list[tuple[int, str, str]]] = {}
    for path in _scoped_modules("engine", "api"):
        rel = _rel(path)
        if rel in SANCTIONED_READERS:
            continue
        hits = reader_violations(path.read_text(encoding="utf-8"))
        if hits:
            out[rel] = hits
    return out


#: module -> why it still re-derives COBOL source text (derived by running the rules; shrink-only).
INVENTORY: dict[str, str] = {
    "engine/modernization/external_dependency_edges.py": (
        "_mask_comments blanks any line whose first non-blank is a star (and cuts *> tails) on raw text; the "
        "module's own test fixture puts the star in column 6, which the reader correctly reads as program text, "
        "so migrating needs that fixture corrected (an existing test must not be weakened) - migrate with it."),
    "engine/transformation/cobol_parser.py": (
        "The full parser still slices fixed-format columns itself (sequence area, indicator, star-prefix comment "
        "tests in its statement/paragraph scanners) over lines it normalises before building the CobolProgram IR; "
        "its offsets feed IR source locations and 4000+ lines of parsing, so it cannot move to positioned_lines "
        "without a parser rewrite.  The R1 hit is only the CONDITIONAL_COMPILATION_UNEVALUATED message text."),
    "engine/transformation/copybook_model.py": (
        "_strip_sequence_numbers re-slices the six-digit sequence field of already compiler-visible copybook lines "
        "and left-strips them; copy-origin offsets and every COPY/REPLACING expansion test depend on that exact "
        "whitespace, so a byte-identical move to positioned_lines needs the copybook materialiser reworked."),
    "engine/transformation/fd_copybooks.py": (
        "FD record locators anchor FILE SECTION / storage-section regexes on an optional six-digit sequence prefix "
        "(_SEQ) over copybook-expanded text; replacing them needs the same copybook-materialiser rework as "
        "copybook_model."),
    "engine/transformation/producer.py": (
        "The single-source COPY refusal guard matches the column-7 indicator by regex over the text it was handed "
        "(no copybook path, no reader pass); it only refuses, never discovers, and should move to "
        "positioned_lines with the producer's pre-parse checks."),
}


# --- the repository obeys the rules --------------------------------------------------------------------------------

def test_every_inventory_justification_is_a_real_sentence():
    for module, reason in INVENTORY.items():
        assert len(reason.split()) >= 4, f"{module}: justify why it still re-reads COBOL source text"
        assert (ROOT / module).is_file(), f"{module} no longer exists; remove it from INVENTORY"


def test_no_module_rederives_cobol_source_text_without_a_declared_reason():
    undeclared = {m: h[:3] for m, h in current_offenders().items() if m not in INVENTORY}
    assert not undeclared, (
        "these modules re-derive comment/indicator/column/directive/dialect logic from raw COBOL text; consume "
        "engine.transformation.source_format (positioned_lines / compiler_visible_text) instead, or declare why in "
        "INVENTORY:\n" + "\n".join(f"  {m}: {h}" for m, h in sorted(undeclared.items())))


def test_the_inventory_has_no_stale_entries():
    offenders = current_offenders()
    stale = [m for m in INVENTORY if m not in offenders]
    assert not stale, f"these modules no longer re-derive source text; delete their INVENTORY entries: {stale}"


def test_exactly_one_profile_builder_caller():
    offenders = {}
    for path in _scoped_modules("engine", "api", "enterprise", "tools"):
        rel = _rel(path)
        if rel in PROFILE_BUILDER_HOMES:
            continue
        hits = profile_builder_references(path.read_text(encoding="utf-8"))
        if hits:
            offenders[rel] = hits
    assert not offenders, f"build_profiles may only be referenced from {sorted(PROFILE_BUILDER_HOMES)}: {offenders}"


def test_the_one_profile_builder_is_actually_used_by_report():
    source = (ROOT / "enterprise/discovery/report.py").read_text(encoding="utf-8")
    assert profile_builder_references(source), "report.py must be the (one) caller of build_profiles"


# --- mutation tests: every rule flags an offender and passes a clean module -----------------------------------------

def _rules(source: str) -> set[str]:
    return {rule.split()[0] for _, rule, _ in reader_violations(source)}


def test_R1_flags_reader_literals_and_ignores_docstrings():
    assert "R1" in _rules('def f(x):\n    return x.find("*>")\n')
    assert "R1" in _rules('def f(x):\n    return x.startswith(">>IF")\n')
    assert "R1" in _rules('MARK = "$SET SOURCEFORMAT"\n')
    assert "R1" in _rules('def f():\n    return "SOURCEFORMAT"\n')
    assert not _rules('def f():\n    """Strips *> and >>IF and $SET text."""\n    return 1\n')
    assert not _rules('SHIFT = "x >> 2"\nPUT = "a *b"\n')


def test_R2_flags_column_slices_on_line_like_names():
    for expr in ("line[6]", "line[6:7]", "line[:72]", "line[7:72]", "raw[6:]", "lines[i][6]", "cleaned[:6]"):
        assert "R2" in _rules(f"def f(line, raw, lines, i, cleaned):\n    return {expr}\n"), expr
    assert not _rules("def f(parts, header):\n    return parts[6], header[7:], parts[1:3]\n")
    assert not _rules("def f(line):\n    return line[0], line[1:5], line[i]\n".replace("line[i]", "line[-1]"))


def test_R3_flags_star_comment_tests():
    assert "R3" in _rules('def f(line):\n    return line.startswith("*")\n')
    assert "R3" in _rules('def f(stripped):\n    return stripped.lstrip().startswith(("*", "/"))\n')
    assert not _rules('def f(operands):\n    return operands.startswith("*")\n')
    assert not _rules('def f(line):\n    return line.startswith("//")\n')


def test_R4_flags_splitlines_loops_that_slice_columns():
    sliced = "def f(source):\n    for entry in source.splitlines():\n        if entry[6] == '*':\n            pass\n"
    assert "R4" in _rules(sliced)
    via_name = ("def f(text):\n    rows = text.splitlines()\n    for n, entry in enumerate(rows):\n"
                "        if entry.startswith('*'):\n            pass\n")
    assert "R4" in _rules(via_name)
    comp = "def f(cobol):\n    return [e[:72] for e in cobol.splitlines()]\n"
    assert "R4" in _rules(comp)
    clean = "def f(source):\n    for entry in source.splitlines():\n        print(entry.strip())\n"
    assert not _rules(clean)
    other = "def f(blob):\n    for entry in blob.splitlines():\n        print(entry[6])\n"
    assert not _rules(other)


def test_R7_flags_sequence_area_regexes():
    bad = (r"^(\d{6})(.)(.*)$", r"^[\d ]{6}", r"^(?:.{6}[ \-]|\s*)COPY")
    for pattern in bad:
        assert "R7" in _rules(f"import re\nSEQ = re.compile({pattern!r})\n"), pattern
    assert not _rules("import re\nSHA = re.compile(r'^[0-9a-f]{64}$')\nYEAR = re.compile(r'\\d{4}')\n")


def test_R5_flags_dialect_redetection():
    assert "R5" in _rules('def f():\n    return ["-std=ibm", "-free"]\n')
    assert "R5" in _rules('def f(s):\n    return [f"-std={s}"]\n')
    assert "R5" in _rules("from enterprise.discovery.scan_cobol import DIALECT_SIGNALS\n")
    assert "R5" in _rules("def f(x):\n    return compilers.std_for_dialect(x)\n")
    assert not _rules('def f():\n    return ["-free", "-x"]\n')


def test_R6_profile_builder_references_are_found():
    assert profile_builder_references("from enterprise.discovery.dialect_profile import build_profiles\n")
    assert profile_builder_references("def f(r):\n    return dialect_profile.build_profiles(r)\n")
    assert profile_builder_references("def f(r):\n    return build_profiles(r)\n")
    assert not profile_builder_references("def f(r):\n    return build_profile_names(r)\n")


def test_a_synthetic_offending_module_would_fail_the_repo_gate(tmp_path):
    """The gate's decision function, applied to a synthetic module, flags it; a clean module passes."""
    bad = tmp_path / "bad.py"
    bad.write_text("def f(line):\n    return line[6] in '*/' or '*>' in line\n", encoding="utf-8")
    good = tmp_path / "good.py"
    good.write_text("def f(lines):\n    return [pl.code for pl in lines if pl.kind == 'code']\n", encoding="utf-8")
    assert reader_violations(bad.read_text(encoding="utf-8"))
    assert not reader_violations(good.read_text(encoding="utf-8"))
