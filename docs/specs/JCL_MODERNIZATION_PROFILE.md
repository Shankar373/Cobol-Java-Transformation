# JCL Modernization Profile — Java/Spring Batch

> Status: implemented + structurally verified
> Scope: `engine/jcl/`, `engine/transformation/jcl_*.py` (mapper + IR + adapter), `fixtures/workload-jcl/`, `tests/test_jcl_*.py`

## Purpose

Upgrades JCL handling from discovery-only (`JclDiscovery`) to a defined
modernization profile that converts each JCL job into a **semantic JCL model**
and then into a **Java/Spring Batch representation**, with explicit
diagnostics for constructs outside the supported subset.

The lane is deliberately **static and declarative**. It captures the JCL
*program*: step order, step activation, resource declarations, and
dataset producer/consumer relationships. It does **not** execute JCL and
claims **no JES/z/OS runtime equivalence**.

## Pipeline

```
JCL source
   │ (engine/transformation/jcl_parser.py — discovery parser, already existing)
   ▼
JclApplication IR           (engine/transformation/ir.py — DO NOT MODIFY)
   │ (engine/jcl/builder.py — JclSemanticBuilder)
   ▼
JclSemanticModel            (engine/jcl/model.py)
   │ (engine/transformation/jcl_to_spring_batch.py — JclSpringBatchMapper)
   ▼
SpringBatchApplication      (engine/transformation/jcl_spring_batch_ir.py)
   +                                                  │
JclModernizationProfile                    (engine/transformation/jcl_spring_boot_adapter.py)
   (representation + diagnostics + status)            ▼
                                        SpringBootApplication (shared IR)
                                                      │
                                        (engine/transformation/spring_boot_generator.py)
                                                      ▼
                                        Generated Spring Boot project (list[GeneratedFile])
```

Single entry point:

```python
from engine.transformation.jcl_parser import JclParser
from engine.transformation.jcl_to_spring_batch import modernize_jcl

app = JclParser().parse_application({"batch.jcl": source})
profile = modernize_jcl(app, {"batch.jcl": source})

profile.application           # SpringBatchApplication
profile.status                # "FULL" | "PARTIAL" | "EMPTY"
profile.diagnostics           # full diagnostic trail
profile.supported_constructs  # explicit contract
profile.unsupported_constructs  # explicit contract
```

## Supported subset

| Construct | JCL form | Semantic model | Spring Batch mapping |
| --- | --- | --- | --- |
| Job card | `//NAME JOB ...` | `JclSemanticJob` | `SpringBatchJob` (bean naming deterministic) |
| Step | `//STEP EXEC PGM=...` | `JclSemanticStep` | `SpringBatchStep` + `*Tasklet` bean |
| DD — dataset | `//DD DD DSN=...` | `JclResource` (DATASET) | `SpringBatchResource` INPUT/OUTPUT by DISP |
| DD — temp dataset | `//DD DD DSN=&&T,X` | `JclResource` (TEMPORARY) | `SpringBatchResourceType.TEMP`, I/O by DISP |
| DD — SYSOUT | `//SYSPRINT DD SYSOUT=*` | `JclResource` (SYSOUT) | `SYSOUT_LOG` |
| DD — inline | `//SYSIN DD *` | `JclResource` (SYSIN_INLINE) | `INLINE_PARAMS` |
| Step order | sequential steps | `order_index`, `dataset_flows` | `SpringBatchFlowEdge`, `start_step` |
| Synthetic activation | `COND=EVEN` | `JclControlKind.EVEN` | `on_status == '*'` (ANY) |
| Exec-only-on-failure | `COND=ONLY` | `JclControlKind.ONLY` | `on_status == 'FAILED'` |
| Return-code condition | `COND=(rc,op)` | `JclControlKind.RETURN_CODE` | `on_status == 'CONDITIONAL'` + WARNING |

Step activation mapping (declared gates, verified at implementation time):

| COND value | `JclControlKind` | `exit_status` | WARNING |
| --- | --- | --- | --- |
| (absent) | `SEQUENTIAL` | `SUCCESS` | — |
| `EVEN` | `EVEN` | `ANY` (`*`) | — |
| `ONLY` | `ONLY` | `FAILED` | — |
| `(rc,op)` | `RETURN_CODE` | `CONDITIONAL` | `PARTIAL_COND_SEMANTICS` |
| anything else / malformed | `UNSUPPORTED` | `UNKNOWN` | warning |

## Unsupported constructs (explicit diagnostics)

Detected at the raw-source line level (no silent dropping — the parser still
captures every statement; support is evaluated at modernization time).

| Construct | Diagnostic code (ERROR) |
| --- | --- |
| `PROC`/`PEND` definitions and `EXEC PROC=` steps | `UNSUPPORTED_PROCEDURE` |
| `IF (...) THEN` / `ELSE` / `ENDIF` blocks | `UNSUPPORTED_CONTROL_BLOCK` |
| `JCLLIB`, `INCLUDE`, `OUTPUT`, `XMIT`, `TWRS`, `CMPSC`, `PROCESS`, `NETVIEW` | `UNSUPPORTED_STATEMENT` |
| DD continuations (`// ,...`) | `UNSUPPORTED_CONTINUATION` |
| steps without an EXEC program | `STEP_NO_EXEC` |
| unnamed jobs | `JOB_UNNAMED` |

Non-blocking diagnostics:

| Condition | Code (WARNING/INFO) |
| --- | --- |
| return-code COND declared | `PARTIAL_COND_SEMANTICS` (WARNING) |
| symbolic reference `&X` (static profile) | `UNRESOLVED_SYMBOL` (WARNING) |
| DD with no dataset/SYSOUT/inline | `DUMMY_RESOURCE` (WARNING) |
| `SET` statements preserved verbatim | `SYMBOL_SET_PRESERVED` (INFO) |
| profile generated (no JES equivalence) | `PROFILE_NOTED` (INFO) |

## Profile status

- `EMPTY` — the application contains no jobs.
- `FULL` — modernization produced no ERROR diagnostics.
- `PARTIAL` — at least one unsupported construct was diagnosed (representation
  is still generated and complete for everything that was parseable).

## Deterministic naming

- `_camel_bean("PAY-MAIN")` → `PayMain` (split on non-alphanumerics, title-case).
- Job bean: `camel(job) + "Job"`.
- Step bean: `camel(step)`; tasklet bean: `camel(step) + "Tasklet"`.
- Resource bean: `camel(DD name)`.
- Spring Batch flow/dataset edges use the camel step names; the semantic model
  keeps original JCL names, so the two layers remain traceable
  (`SpringBatchStep.source_step`).

## Dataset relationships

For each job, `dataset_flows` pairs a dataset name with one producer (the step
that creates/updates it, `""` if external) and zero-or-more consumers (steps
that read it). The rule is *declare-before-use within a job*: disposition
`NEW` → OUTPUT, `OLD`/`SHR` → INPUT, `MOD` → OUTPUT. A temporary dataset `&&T`
declared in STEP01 and referenced in STEP02 therefore yields
producer `STEP01`, consumer `STEP02`.

## Limitations (documented, not claimed)

- No JES/z/OS execution semantics; `PROC` expansion, symbol resolution
  (`&X`), and return-code conditions (`COND=(rc,op)`) are **declared**, not
  evaluated.
- Ordering captured is the static JCL sequence plus step activation gates.
- Library/procedure catalogs (`JCLLIB`, `INCLUDE`) are out of scope.
- COBOL program bodies themselves are outside this lane (see the Core
  COBOL→Java pipeline).

## Files

| Path | Contents |
| --- | --- |
| `engine/jcl/__init__.py` | lane exports |
| `engine/jcl/diagnostics.py` | `JclDiagnostic*` types |
| `engine/jcl/model.py` | semantic model (`JclSemanticModel`, jobs, steps, resources, controls, dataset flows) |
| `engine/jcl/builder.py` | `JclSemanticBuilder` (`app + raw sources → model`) |
| `engine/transformation/jcl_spring_batch_ir.py` | Spring Batch representation IR |
| `engine/transformation/jcl_to_spring_batch.py` | mapper, profile, `modernize_jcl` facade |
| `engine/transformation/jcl_spring_boot_adapter.py` | JCL → Spring Boot IR adapter (structural generation) |
| `engine/transformation/jcl_consumer.py` | consumer integration module |
| `engine/transformation/jcl_parser.py` | discovery parser (edited: `PGM=`/`PROC=` capture stops at `,`) |
| `fixtures/workload-jcl/*.jcl` | fixture workload (`simple_batch`, `order_flow`, `conditional`, `unsupported`) |
| `tests/test_jcl_semantic_model.py` | semantic model regression/structure tests |
| `tests/test_jcl_spring_batch.py` | generated representation tests |
| `tests/test_jcl_fixtures.py` | end-to-end fixture/profile tests |
| `tests/test_jcl_consumer_integration.py` | consumer integration tests |
| `tests/test_jcl_generation.py` | generation pipeline tests |

## Verification

- `python -m pytest tests/transformation/test_jcl_parser.py tests/test_jcl_*.py tests/transformation/test_cics_semantics.py -q` → 320 passed.
- `python -m ruff check` clean on all new JCL-lane files.
- Consumer smoke: workload fixtures → `status: PARTIAL`, 4 jobs, 14 steps, 4 unsupported constructs.
- Generation smoke: JCL → adapter → `SpringBootApplication` → `SpringBootGenerator` → 7 files (pom.xml, application.properties, entry point, 4 service classes).
- Generated code compiles structurally (correct Java syntax, Spring annotations, `System.out.println` statements).
- **NOT runtime verified**: Maven compilation and Docker execution not yet proven.
- **NO JES/z/OS equivalence claimed**.