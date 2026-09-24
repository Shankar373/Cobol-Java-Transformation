# JCL Modernization — Integration Contract

> Status: proposed (contract only; no shared-file edits applied)
> Scope: defines *how* `pipeline.py` / `api/` / code generators would consume
> the JCL modernization lane **without modifying** the shared files listed in
> project rules (`pipeline.py`, `api/`, `application_generator.py`,
> `spring_boot_generator.py`, `ir.py`, etc.).

## Purpose

The JCL lane produces a self-contained result: `JclModernizationProfile`.
This contract fixes the boundary so integration work is a pure *consumer* of
the lane. The lane does **not** require changes to any Core COBOL/Spring
artifact.

## Lane entry point (stable API)

```python
# engine/transformation/jcl_to_spring_batch.py
def modernize_jcl(
    app: JclApplication,             # from JclParser.parse_application / JclDiscovery
    raw_sources: dict[str, str] | None,
    application_id: str = "jcl-modernization",
    base_package: str = "com.generated.batch",
) -> JclModernizationProfile: ...
```

### Sourcing the JCL application

Preferred: reuse discovery so JCL joins the pipeline like COBOL does.

```python
from engine.transformation.jcl_discovery import JclDiscovery
from engine.transformation.jcl_to_spring_batch import modernize_jcl

sources = {path.name: path.read_text() for path in sorted(fx.glob("*.jcl"))}
app = JclDiscovery().discover(fx)
profile = modernize_jcl(app, sources, application_id=app_id, base_package=pkg)
```

`raw_sources` may be omitted when discovery already populated it; it is used
only for unsupported-construct scanning (raw JCL text), never for IR building.

## The profile object (output contract)

| Attribute | Type | Meaning |
| --- | --- | --- |
| `application` | `SpringBatchApplication` | generated representation (see below) |
| `status` | `"FULL" \| "PARTIAL" \| "EMPTY"` | by-error-driven status |
| `has_errors` / `has_warnings` | `bool` | derived from diagnostics |
| `supported_constructs` | `tuple[str, ...]` | explicit supported-subset contract |
| `unsupported_constructs` | `tuple[str, ...]` | explicit unsupported-subset contract |
| `diagnostics` | `tuple[JclDiagnostic, ...]` | full trail (errors/warnings/info) |

### `SpringBatchApplication`

| Member | Type | Meaning |
| --- | --- | --- |
| `application_id`, `base_package`, `PROFILE_VERSION` (`"1.0"`) | `str` | metadata |
| `jobs` | `tuple[SpringBatchJob, ...]` | per-JCL-job batch jobs |
| `resources` | `tuple[SpringBatchResource, ...]` | deduplicated dataset inventory |
| `dataset_edges` | `tuple[SpringBatchDatasetEdge, ...]` | producer/consumer edges |
| `validate()` | `list[str]` | structural consistency; empty = consistent |

### `SpringBatchJob` / `SpringBatchStep`

- Job: `name`, `job_bean`, `start_step`, `steps`, `flows`, `parameters`,
  `source_path`.
- Step: `name` (camel), `source_step` (original JCL name), `program`,
  `tasklet_bean`, `resources`, `activation`, `raw_condition`.
- Flow edge: `source`, `target`, `on_status` (`SUCCESS`, `FAILED`, `*`, or
  `CONDITIONAL` for declared return-code gates).

## Integration rules (mandatory)

1. **Consumers only.** Integration code (in `pipeline.py`, `api/`, or a code
   generator) may *call* `modernize_jcl`/`JclDiscovery` and consume the
   returned objects. It must not depend on internals of `engine/jcl/*` or
   `jcl_to_spring_batch.py`.
2. **No shared-file edits.** This contract is satisfied without touching
   `cobol_parser.py`, `ir.py`, `cobol_to_java_mapping.py`,
   `java_to_spring_mapping.py`, `spring_boot_ir.py`, `spring_boot_generator.py`,
   `application_generator.py`, `pipeline.py`, `api/`, `frontend/`, or
   `oracle/`. If actual wiring turns out to require such an edit, **stop and
   reopen this contract** — do not modify shared files.
3. **Never propagate guesses.** A `PARTIAL`/`EMPTY` profile must be surfaced
   to the caller with its diagnostics intact; do not flatten or downgrade
   unsupported-construct errors.
4. **Determinism.** Both the semantic model and the generated representation
   are deterministic; integration must not reorder or re-key them.
5. **No JES claims.** The representation is a static modernization intent.
   Nothing downstream may label `CONDITIONAL`/`UNKNOWN` edges as equivalent to
   z/OS run-time behavior.

## Status semantics for the pipeline

- `EMPTY`: no JCL jobs found — pass-through to existing behavior; emit INFO.
- `FULL`: safe to generate from `application`; diagnostics are notes/warnings.
- `PARTIAL`: generate the representation **and** carry `unsupported_constructs`
  + error diagnostics to the caller/report; do not block the rest of the
  pipeline for the jobs that were fully parseable.

## Dataset edge contract

`SpringBatchDatasetEdge`: `job`, `dataset`, `producer` (camel step, `""` =
external/not produced), `consumer` (camel step, `""` = produced but not
consumed). Producers/consumers are derived from each DD's dataset name and
disposition within the owning job (declare-before-use).

## Consuming generator sketch (illustrative, not applied)

```python
# Illustrative only — shows the boundary. Would live in the integration
# layer, NOT in engine/transformation.
profile = modernize_jcl(app, sources)
assert profile.application.validate() == []
if profile.status == JclProfileStatus.PARTIAL:
    collect = list(profile.unsupported_constructs)   # surface, do not hide
for job in profile.application.jobs:
    emit_job_class(job)                                 # consumer-side code
```

No such generator exists in this change; if one is requested it must be
created under the integration layer and must not modify shared files.

## Not in scope

- Executing JCL, resolving `&SYMBOL`s, expanding `PROC` steps.
- Emulating z/OS return codes or `COND=(rc,op)` evaluation.
- Generating Spring Boot application source (that is Core-lane territory;
   this lane emits the *representation*, not Java files).

## Status

Contract written. No `pipeline.py`/`api/` wiring applied, because applying it
would require editing shared files listed as DO-NOT-MODIFY — per project
rules, integration requiring shared-file edits must stop at the contract.