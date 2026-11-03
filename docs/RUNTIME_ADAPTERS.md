# Runtime adapters — how a Java target is added

One semantic transform, many runtimes: COBOL is parsed and mapped to Java IR
once (`ApplicationGenerator`, `engine/transformation/cobol_to_java_mapping.py`);
a **runtime adapter** only assembles that IR into a buildable project for one
target. Adapters never parse COBOL or change semantics.

## The runtime registry

`engine/transformation/runtime_registry.py` is the single table of targets: key, label, plan output type, candidate
lane (Spring Boot or generic Maven) and a `certified` flag. The assembly adapters, the candidate-lane factory, the
API and the frontend all read it. `GET /runtimes` lists it; `POST /applications` accepts only certified targets
(`jakarta_ee` is registered and the engine can still generate it, but the API answers 400 "not certified"); the
frontend selector offers the certified rows. `tests/test_runtime_registry.py` pins the certified set to the
corpus-certification matrix in `.github/workflows/certification.yml`.

## Proven targets

| `target_runtime` | Adapter (`engine/transformation/runtime_adapters.py`) | Project | Proof |
|---|---|---|---|
| `spring_boot` (default) | `SpringBootRuntimeAdapter` | Spring Boot app, runner calls `RUN_UNIT$ENTRY` | corpus certification, 44/54 VERIFIED |
| `plain_java` | `PlainJavaRuntimeAdapter` | dependency-free jar, class `main` | same |
| `quarkus` | `QuarkusRuntimeAdapter` | `@QuarkusMain` command-mode uber-jar | same |
| `micronaut` | `MicronautRuntimeAdapter` | `ApplicationContext` command-mode shaded jar | same |
| `jakarta_ee` | `JakartaEeRuntimeAdapter` | plain jar under a Jakarta-marked pom (**no server**) | builds and runs as `plain_java` |

Application servers (a Jakarta EE server, WildFly, Open Liberty, Payara,
TomEE) are not targets: the name is refused as an unknown `target_runtime`.

## The port

```python
class RuntimeAdapter(ABC):
    target_runtime: ClassVar[str]
    def assemble(self, java_application, *, entry_program="", copybook_models=(),
                 output_prefix="generated-", runtime=None, output_root=None) -> AssemblyOutcome
```

`AssemblyOutcome(project_dir, entrypoint)`: the project directory (created
under `output_root`, the run's durable output directory) and the class the
build lane runs. Command-mode framework targets extend `PlainJavaRuntimeAdapter`
through `_FrameworkCommandAdapter`: the program classes are the `plain_java`
ones byte for byte, plus `_framework_files(program_class)` (the entry class
and resources) and `_render_pom(...)`.

## Adding a target — checklist

1. **Adapter**: subclass (usually `_FrameworkCommandAdapter`), set
   `target_runtime` and the entry class, implement `_framework_files` and
   `_render_pom`. Exactly **one runnable jar** must end up in `target/`
   (the Maven lane runs the jar it finds there).
2. **Registry**: add the name to `SUPPORTED_TARGET_RUNTIMES`,
   `PLAN_OUTPUT_TYPE_BY_TARGET` and `_ADAPTER_FACTORIES`; route it in
   `engine/candidate/factory.py` (the generic Maven lane builds any
   single-jar Maven project offline).
3. **Offline build**: the build image has no network. Generate the
   precache project (`scripts/generate_framework_precache.py`, extend it for
   the new adapter) so `Dockerfile.maven-offline` resolves every plugin and
   dependency at image build time; `tests/test_framework_runtimes.py` fails
   when the precache drifts from the adapter.
4. **Scope disclosure**: add the target's limitations to the modernization
   report (`engine/modernization/pipeline.py`) — e.g. "command mode, no HTTP
   endpoints".
5. **Proof**: unit tests for the project shape and shared sources
   (`tests/test_framework_runtimes.py` is the template), a Docker-lane test
   against GnuCOBOL, the target in `.github/workflows/certification.yml`'s
   matrix and a committed accepted evidence file
   (`docs/reports/evidence/phase3/runtime_corpus_<target>.jsonl`) that
   `scripts/e2e/certify_corpus.py` compares against.
6. **Docs**: this table, `docs/CAPABILITY_MATRIX.md`, `docs/KNOWN_ISSUES.md`.

A target is "supported" only after the whole corpus certifies on it with
every VERIFIED result independently re-checked — never on generation alone.
