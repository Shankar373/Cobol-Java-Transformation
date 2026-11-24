"""Layer 8: the application's CALL graph as the plan consumes it - dependency order, transitive blocking, oracle parameters.

* ``dependency_order``: callees before callers, ties and cycles broken by discovery order (never by name or hash), so the order
  is a pure function of the application.  A cycle is not ordered away: Layer 7 already marks it non-SUPPORTED, and the members
  keep their discovery order here.
* ``blocked_by_dependency``: a program that has a RESOLVED CALL to a program the plan does not transform cannot be transformed
  either - its Java would call a class that is never generated.  Unresolved and dynamic CALLs are the Layer 7 CALL
  components' business and are not propagated here.
* ``oracle_parameters``: the reference-format flag and link set of the GnuCOBOL oracle, derived from the same sources the oracle
  adapter reads (``engine.transformation.source_format.detect_source_format``; every top-level module except the entry).

Pure and deterministic: no clock, no randomness, no LLM.
"""

from __future__ import annotations

from collections.abc import Iterable

from engine.transformation.entrypoint import normalise
from engine.transformation.ir import CobolApplication
from engine.transformation.source_format import detect_source_format


def _callee_indexes(application: CobolApplication) -> list[set[int]]:
    """For each program (discovery order), the indexes of the programs it has a RESOLVED CALL to (self-calls excluded)."""
    index_of: dict[str, int] = {}
    for position, unit in enumerate(application.programs):
        index_of.setdefault(normalise(unit.program_id), position)
    callees: list[set[int]] = [set() for _ in application.programs]
    for edge in application.edges:
        if edge.edge_type != "CALL" or edge.resolution != "RESOLVED":
            continue
        source, target = index_of.get(normalise(edge.source)), index_of.get(normalise(edge.target))
        if source is not None and target is not None and source != target:
            callees[source].add(target)
    return callees


def dependency_ranks(application: CobolApplication) -> tuple[int, ...]:
    """The 1-based build rank of each program, by discovery position (programs sharing an id keep distinct ranks)."""
    callees = _callee_indexes(application)
    emitted: list[int] = []
    done: set[int] = set()
    remaining = list(range(len(callees)))
    while remaining:
        ready = [i for i in remaining if callees[i] <= done]
        pick = ready[0] if ready else remaining[0]       # a cycle: the earliest-discovered member goes first
        emitted.append(pick)
        done.add(pick)
        remaining.remove(pick)
    ranks = [0] * len(callees)
    for rank, position in enumerate(emitted, 1):
        ranks[position] = rank
    return tuple(ranks)


def dependency_order(application: CobolApplication) -> tuple[str, ...]:
    """Program ids, every callee before its callers; ties and cycle members in discovery order."""
    ranks = dependency_ranks(application)
    by_rank = sorted(range(len(ranks)), key=ranks.__getitem__)
    return tuple(application.programs[i].program_id for i in by_rank)


def blocked_by_dependency(application: CobolApplication, transformable: Iterable[str],
                          blocked_copybooks: Iterable[str] = ()) -> dict[str, str]:
    """``{program_id: dependency}`` for each transformable program that cannot be, because of what it depends on.

    The dependency is ``"calls CALLEE"`` for a RESOLVED CALL to a program that is not transformable and
    ``"uses copybook NAME"`` for a COPY of a blocked copybook.  Computed to a fixed point: a caller of a newly blocked
    caller is blocked too.  A copybook is named before a callee, and the first callee (discovery order) is named.
    """
    callees = _callee_indexes(application)
    names = [u.program_id for u in application.programs]
    allowed, bad_copybooks = set(transformable), set(blocked_copybooks)
    live = {i for i, name in enumerate(names) if name in allowed}
    blocked: dict[str, str] = {}
    changed = True
    while changed:
        changed = False
        for i in sorted(live):
            unit = application.programs[i]
            bad = sorted({c.copybook_name for c in unit.copybooks if c.copybook_name in bad_copybooks})
            dead = sorted(j for j in callees[i] if j not in live)
            reason = f"uses copybook {bad[0]}" if bad else f"calls {names[dead[0]]}" if dead else ""
            if reason:
                blocked[names[i]] = reason
                live.discard(i)
                changed = True
    return blocked


def oracle_parameters(application: CobolApplication, entry_program: str) -> tuple[str, tuple[str, ...]]:
    """``(source_format, link_modules)`` of the oracle run for ``entry_program``.

    ``source_format`` is ``"free"`` or ``"fixed"`` when every program has that start format, ``"mixed"`` when they differ and
    ``""`` when there is no program text to read.  ``link_modules`` are the source file names the oracle links beside the
    entry's own file (sorted case-insensitively, as the oracle adapter sorts its modules); ``()`` without an entry.
    """
    formats = {detect_source_format(u.source_text) for u in application.programs if u.source_text}
    source_format = "" if not formats else next(iter(formats)) if len(formats) == 1 else "mixed"
    entry = next((u for u in application.programs if u.program_id == entry_program), None)
    if entry is None:
        return source_format, ()
    entry_file = entry.source_path.replace("\\", "/").rsplit("/", 1)[-1]
    files = {u.source_path.replace("\\", "/").rsplit("/", 1)[-1] for u in application.programs}
    files.discard(entry_file)
    return source_format, tuple(sorted(files, key=str.lower))
