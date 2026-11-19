"""Layer 3 acceptance criterion 11: a large corpus completes within a documented time and memory budget, and the
store is queryable without loading the whole JSON document.

Size is ``KG_BENCH_FILES`` (default 1000 so the default run stays quick; set ``KG_BENCH_FILES=10000`` for the full
criterion).  Budgets are *per file* so they scale with the chosen size.  Measured numbers are printed (``pytest -s``).

Documented budgets (the contract this file enforces, CPython 3.11):

* graph pipeline (scan -> resolve -> applications -> serialise -> store save): <= ``GRAPH_SECONDS_PER_FILE`` s/file
* peak process memory growth over the pipeline:                                  <= ``GRAPH_MEMORY_BYTES_PER_FILE`` B/file
* any store row query (p95 for the repeated impact hops) on the saved snapshot: <= ``QUERY_SECONDS``
* full ``discover()`` (ingest + checkpoint + compilers + publish): must take no more than
  ``MAX_DOUBLING_RATIO`` x as long when the input doubles (i.e. not quadratic).
"""

from __future__ import annotations

import ctypes
import json
import os
import sys
import time
from pathlib import Path

import pytest

from enterprise.discovery.applications import build_applications, link_applications
from enterprise.discovery.classify import classify
from enterprise.discovery.compilers import ToolchainConfig
from enterprise.discovery.discover import DiscoveryRequest, discover, scan_file
from enterprise.discovery.graph import stamp_graph_id
from enterprise.discovery.inventory import FileRecord
from enterprise.discovery.kg_query import impact
from enterprise.discovery.kg_store import KGStore
from enterprise.discovery.resolve import build_graph
from tests.discovery._kg_synth import synth_files, write_synth

BENCH_FILES = int(os.environ.get("KG_BENCH_FILES", "1000"))
GRAPH_SECONDS_PER_FILE = 0.05
GRAPH_MEMORY_BYTES_PER_FILE = 512 * 1024
QUERY_SECONDS = 5.0
MAX_DOUBLING_RATIO = 3.0
IMPACT_DEPTH = 2
E2E_SMALL, E2E_LARGE = 100, 200
E2E_REPEATS = 3


def _peak_memory_bytes() -> int:
    """Peak resident/working set of this process (monotonic), without third-party packages."""
    if sys.platform == "win32":
        class Counters(ctypes.Structure):
            _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
        counters = Counters()
        counters.cb = ctypes.sizeof(Counters)
        kernel32, psapi = ctypes.windll.kernel32, ctypes.windll.psapi
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
        psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb)
        return int(counters.PeakWorkingSetSize)
    import resource

    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(peak if sys.platform == "darwin" else peak * 1024)


def _records(files: dict[str, str]) -> list[FileRecord]:
    out = []
    for path, text in files.items():
        cls = classify(path, text).cls
        out.append(FileRecord(path, "0" * 64, len(text), cls, scan=scan_file(path, cls, text)))
    return out


def _graph_document(files: dict[str, str]) -> dict:
    records = _records(files)
    graph = build_graph(records).graph
    link_applications(graph, build_applications(records, graph))
    document = graph.to_dict()
    stamp_graph_id(document)
    return document


@pytest.fixture(scope="module")
def pipeline(tmp_path_factory):
    """Run the graph pipeline once at the configured size and keep the measurements and the saved store."""
    files = synth_files(BENCH_FILES)
    base_memory = _peak_memory_bytes()
    started = time.perf_counter()
    document = _graph_document(files)
    built = time.perf_counter()
    db_path = tmp_path_factory.mktemp("kg-bench") / "kg.sqlite3"
    with KGStore(db_path) as store:
        graph_id = store.save(document, application="bench")
    finished = time.perf_counter()
    metrics = {
        "files": len(files), "nodes": len(document["nodes"]), "edges": len(document["edges"]),
        "unresolved": len(document["unresolved"]), "build_seconds": round(built - started, 2),
        "save_seconds": round(finished - built, 2), "total_seconds": finished - started,
        "peak_memory_growth_bytes": _peak_memory_bytes() - base_memory,
        "document_bytes": len(json.dumps(document)),
    }
    print(f"\nKG_BENCH graph pipeline: {json.dumps(metrics, sort_keys=True)}")
    return {"document": document, "db_path": db_path, "graph_id": graph_id, "metrics": metrics}


def test_graph_pipeline_stays_within_the_time_budget(pipeline) -> None:
    metrics = pipeline["metrics"]
    assert metrics["edges"] > metrics["files"]
    assert metrics["total_seconds"] <= GRAPH_SECONDS_PER_FILE * metrics["files"], metrics


def test_graph_pipeline_stays_within_the_memory_budget(pipeline) -> None:
    metrics = pipeline["metrics"]
    assert metrics["peak_memory_growth_bytes"] <= GRAPH_MEMORY_BYTES_PER_FILE * metrics["files"], metrics


def test_store_rows_equal_the_json_after_a_large_import(pipeline) -> None:
    document = pipeline["document"]
    with KGStore(pipeline["db_path"]) as store:
        counts = store.counts(pipeline["graph_id"])
    assert counts["nodes"] == len(document["nodes"]) and counts["edges"] == len(document["edges"])
    assert counts["unresolved"] >= len(document["unresolved"])


def test_store_is_queryable_without_loading_the_json_document(pipeline, monkeypatch: pytest.MonkeyPatch) -> None:
    document, graph_id = pipeline["document"], pipeline["graph_id"]
    with KGStore(pipeline["db_path"]) as store:
        statements: list[str] = []
        original = store._db.execute

        def spy(sql, *args, **kwargs):
            statements.append(str(sql))
            return original(sql, *args, **kwargs)

        monkeypatch.setattr(store._db, "execute", spy)
        monkeypatch.setattr(store, "load", lambda *_: pytest.fail("the whole JSON document was loaded"))

        copybook = max((n["id"] for n in document["nodes"] if n["kind"] == "copybook"),
                       key=lambda node: len([e for e in document["edges"] if e["to"] == node]))
        program = next(n["id"] for n in document["nodes"] if n["kind"] == "program")
        timings: dict[str, float] = {}

        def timed(label, fn):
            started = time.perf_counter()
            result = fn()
            timings[label] = time.perf_counter() - started
            return result

        assert timed("nodes_by_kind", lambda: store.nodes(graph_id, kind="program", limit=50))
        assert timed("edges_from_program", lambda: store.edges(graph_id, src=program, limit=None))
        assert timed("unresolved", lambda: store.unresolved(graph_id, limit=100)) is not None

        lookups: list[float] = []

        def store_impact() -> set[str]:  # reverse closure (IMPACT_DEPTH hops) through row queries only
            seen, frontier = {copybook}, [copybook]
            for _ in range(IMPACT_DEPTH):
                following = []
                for node in frontier:
                    started = time.perf_counter()
                    rows = store.edges(graph_id, dst=node, limit=None)
                    lookups.append(time.perf_counter() - started)
                    for row in rows:
                        if row["src"] not in seen:
                            seen.add(row["src"])
                            following.append(row["src"])
                frontier = following
            return seen - {copybook}

        from_store = timed("impact_by_rows", store_impact)
        assert from_store, "the benchmark copybook must have dependants"
        assert from_store == impact(document, copybook, "in", depth=IMPACT_DEPTH)
        timings["impact_lookups"] = len(lookups)
        timings["impact_p95_lookup"] = sorted(lookups)[int(len(lookups) * 0.95)]
        print(f"KG_BENCH store queries (seconds): {json.dumps(timings, sort_keys=True)}")
        for label in ("nodes_by_kind", "edges_from_program", "unresolved", "impact_p95_lookup"):
            assert timings[label] <= QUERY_SECONDS, timings
        assert statements and not any("document" in s.lower() for s in statements), statements


def test_full_discovery_scales_sub_quadratically(tmp_path: Path) -> None:
    """``discover()`` takes at most ``MAX_DOUBLING_RATIO`` x as long when the input doubles.

    The measurement is best-of-``E2E_REPEATS`` with the two sizes **interleaved**: a shared CI runner
    stalls for seconds at a time (the Windows run of ``f083b1a`` measured ``{100: 0.537, 200: 1.625}``
    = 3.03x and failed, while the same code on a quiet machine measures about 1.9x), and running every
    ``E2E_SMALL`` pass before the first ``E2E_LARGE`` pass lets one stall land on a single size and
    invent a ratio.  Interleaving exposes both sizes to the same machine state, best-of-N keeps the
    fastest (least-disturbed) observation of each, and the threshold itself is unchanged: it still
    fails any superlinear ``discover()`` (quadratic would measure about 4x).  The sizes are written
    once, before any timing, so file creation never lands inside a measured pass.
    """
    for size in (E2E_SMALL, E2E_LARGE):
        write_synth(tmp_path / f"estate-{size}", size)
    runs: dict[int, list[float]] = {E2E_SMALL: [], E2E_LARGE: []}
    order = (E2E_SMALL, E2E_LARGE)
    for attempt in range(E2E_REPEATS):
        for size in order if attempt % 2 == 0 else tuple(reversed(order)):  # alternate: no size runs first always
            started = time.perf_counter()
            discover(DiscoveryRequest("directory", str(tmp_path / f"estate-{size}")),
                     tmp_path / f"store-{size}-{attempt}", toolchain=ToolchainConfig(backend="none"))
            runs[size].append(time.perf_counter() - started)
    seconds = {size: min(samples) for size, samples in runs.items()}
    print(f"KG_BENCH full discover (seconds): {json.dumps(seconds, sort_keys=True)}"
          f" samples={json.dumps({str(k): [round(v, 3) for v in vs] for k, vs in runs.items()}, sort_keys=True)}")
    assert seconds[E2E_LARGE] <= MAX_DOUBLING_RATIO * seconds[E2E_SMALL], seconds


def test_destination_lookup_uses_an_index_instead_of_scanning_the_snapshot(pipeline) -> None:
    """A ``dst`` point lookup must search ``kg_edge_graph_dst``; scanning every edge of the graph makes each
    neighbour/impact hop O(edges), so an impact walk over a hot copybook is O(edges x dependants)."""
    with KGStore(pipeline["db_path"]) as store:
        plan = store._db.execute(
            'EXPLAIN QUERY PLAN SELECT edge_id FROM kg_edge WHERE graph_id = ? AND dst = ?'
            ' ORDER BY src, dst, relation, file, line, "column", edge_id', (pipeline["graph_id"], "copybook:CPY00000"),
        ).fetchall()
    details = " | ".join(str(row["detail"]) for row in plan)
    assert "kg_edge_graph_dst" in details and "dst=?" in details, details
