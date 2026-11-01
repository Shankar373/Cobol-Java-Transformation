"""Regenerate docs/audits/DEPENDENCY_MAP.md from the tracked Python sources.

Usage::

    python tools/dependency_map.py            # rewrite the map
    python tools/dependency_map.py --check    # exit 1 if the map is stale

Deterministic (sorted, no timestamps), standard library only.  Covers the
production packages (engine/, api/, scripts/, tools/):

* module import graph (static and lazy imports, resolved to tracked modules);
* fan-in (how many modules import each module);
* package-level layering and module import cycles;
* top-level functions/classes no other production module references and
  their own module uses at most once (candidates for removal - each still
  needs a manual check, e.g. for dynamic dispatch or public API use).
"""
from __future__ import annotations

import ast
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "docs" / "audits" / "DEPENDENCY_MAP.md"
PROD_ROOTS = ("engine", "api", "scripts", "tools")


def _tracked_py() -> list[str]:
    out = subprocess.run(["git", "ls-files", "*.py"], cwd=REPO, capture_output=True,
                         text=True, check=True).stdout
    return sorted(f for f in out.split() if f)


def _module(path: str) -> str:
    mod = path[:-3].replace("/", ".")
    return mod[: -len(".__init__")] if mod.endswith(".__init__") else mod


def _imports(tree: ast.AST, me: str, is_pkg: bool, known: set[str]) -> set[str]:
    pkg = me if is_pkg else me.rpartition(".")[0]
    found: set[str] = set()
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parts = pkg.split(".")
                if node.level > 1:
                    parts = parts[: len(parts) - (node.level - 1)]
                base = ".".join(parts + ([base] if base else []))
            names = [base] + [f"{base}.{a.name}" for a in node.names]
        for name in names:
            while name and name not in known:
                name = name.rpartition(".")[0]
            if name and name != me:
                found.add(name)
    return found


def _cycles(edges: dict[str, set[str]]) -> list[tuple[str, ...]]:
    # Tarjan SCC: every strongly connected component of size > 1 is a cycle.
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on: set[str] = set()
    out: list[tuple[str, ...]] = []
    counter = [0]

    def visit(v: str) -> None:
        index[v] = low[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        on.add(v)
        for w in sorted(edges.get(v, ())):
            if w not in index:
                visit(w)
                low[v] = min(low[v], low[w])
            elif w in on:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            comp = []
            while True:
                w = stack.pop()
                on.discard(w)
                comp.append(w)
                if w == v:
                    break
            if len(comp) > 1:
                out.append(tuple(sorted(comp)))

    sys.setrecursionlimit(10000)
    for v in sorted(edges):
        if v not in index:
            visit(v)
    return sorted(out)


def build() -> str:
    files = _tracked_py()
    prod = [f for f in files if f.split("/")[0] in PROD_ROOTS]
    known = {_module(f) for f in files}
    text = {f: (REPO / f).read_text(encoding="utf-8", errors="replace") for f in files}

    edges: dict[str, set[str]] = {}
    defs: dict[str, list[str]] = {}
    for f in prod:
        tree = ast.parse(text[f])
        edges[_module(f)] = _imports(tree, _module(f), f.endswith("__init__.py"), known)
        defs[f] = [
            n.name for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and not n.decorator_list  # decorated = registered (routes, fixtures)
            and not n.name.startswith("__")
        ]

    fan_in: dict[str, int] = defaultdict(int)
    pkg_edges: dict[tuple[str, str], int] = defaultdict(int)
    for src, dsts in edges.items():
        for dst in dsts:
            fan_in[dst] += 1
            a, b = ".".join(src.split(".")[:2]), ".".join(dst.split(".")[:2])
            if a != b:
                pkg_edges[(a, b)] += 1

    unused: list[tuple[str, str, int]] = []
    for f, names in sorted(defs.items()):
        for name in names:
            pat = re.compile(r"\b" + re.escape(name) + r"\b")
            if any(pat.search(text[g]) for g in prod if g != f):
                continue
            if len(pat.findall(text[f])) > 1:
                continue
            tests = sum(1 for g in files if g.startswith("tests/") and pat.search(text[g]))
            unused.append((f, name, tests))

    lines = [
        "# Dependency map",
        "",
        "Generated by `python tools/dependency_map.py`; do not edit by hand.",
        "CI-independent: rerun after any change to imports and commit the result",
        "(`--check` reports a stale map).",
        "",
        f"Production modules: {len(prod)}; import edges: "
        f"{sum(len(v) for v in edges.values())}.",
        "",
        "## Module import cycles",
        "",
    ]
    cycles = _cycles(edges)
    lines += [f"- {' <-> '.join(c)}" for c in cycles] or ["- none"]
    lines += ["", "## Package layering (cross-package import edges)", "",
              "| From | To | Edges |", "|---|---|---:|"]
    lines += [f"| {a} | {b} | {n} |" for (a, b), n in sorted(pkg_edges.items())]
    lines += ["", "## Most-imported modules (fan-in)", "", "| Module | Importers |", "|---|---:|"]
    top = sorted(fan_in.items(), key=lambda kv: (-kv[1], kv[0]))[:25]
    lines += [f"| {m} | {n} |" for m, n in top]
    lines += ["", "## Unreferenced top-level symbols (removal candidates)", "",
              "No other production module references the name and its own module uses",
              "it at most once.  `tests` = test files that mention it.", "",
              "| Symbol | Tests |", "|---|---:|"]
    lines += [f"| `{f}::{name}` | {t} |" for f, name, t in unused]
    lines += ["", "## Module imports", ""]
    for src in sorted(edges):
        deps = ", ".join(sorted(edges[src])) or "-"
        lines.append(f"- **{src}** -> {deps}")
    return "\n".join(lines) + "\n"


def main() -> int:
    content = build()
    if "--check" in sys.argv:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current.replace("\r\n", "\n") != content:
            print(f"{OUT.relative_to(REPO)} is stale; run python tools/dependency_map.py")
            return 1
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(content, encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
