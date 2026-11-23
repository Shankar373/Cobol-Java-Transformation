# D6: emitting nested control- and data-flow edges into the graph (investigation, no change made)

Status: **investigation only.** The closed graph vocabulary, `RESOLVER_RULES` and `graph_id` are unchanged. Measured at
`338c896` with `engine.semantic_facts.graph_bridge.proposed_edges` over the 55 fixture applications that have a `cobol/` tree.

## Findings

| Measure | Value |
|---|---|
| edges the graph builder emits today (these 55 trees) | 1,029 |
| edges Layer 5 can state with an exact file/line/column (`performs`, `goes-to`, `reads-item`, `writes-item`) | 1,218 |
| of those, already present in the graph (same from, to, relation) | **0** |
| facts Layer 5 could not place exactly (counted, never emitted) | 395 |
| relations needed that are *not* in `EDGE_RELATIONS` | none (all four exist) |
| rules needed that are *not* in `RESOLVER_RULES` | none required: generic `definition-<relation>` rules exist (e.g. `definition-reads-item`, `definition-performs`) |

* **No vocabulary change is needed**, which weakens the earlier assumption that D6 requires new rules. What D6 actually
  decides is *granularity and volume*: the graph's existing `performs` edges are program-to-paragraph, the proposal is
  paragraph-to-paragraph (more precise, so zero overlap), and emitting would roughly double the edge count of these trees and
  change `graph_id` of every estate that has COBOL control flow.
* Because `graph_id` is the content address bound into evidence (`graph_traceability`, `semantic_facts.graph_id`), emitting
  invalidates every stored graph lineage; that is a coordinated, certified schema decision (LM contract 4), not a Layer 6 step.

## What a decision would have to cover (not done)

1. the source node for a nested statement (paragraph vs program) and how it relates to the existing program-level `performs`;
2. whether `reads-item`/`writes-item` target the collapsed name-level `data-item` node (qualified duplicates collapse) or
   require a qualified node id;
3. the 10k-scale benchmark threshold (`3.0`) with roughly double the edges;
4. `test_kg_acceptance` criterion 1 (`graph_id` stability), the lint inventories, and a migration of stored `graph_id`s.

Until then the proposal stays a read-only report: the Layer 6 IR carries these relationships as `reads-item`, `writes-item`,
`performs`, `goes-to` edges derived from Layer 5 facts, so consumers have them without touching the graph.
