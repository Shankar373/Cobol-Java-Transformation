"""COPYBOOK semantic materialization — M7 (Lane C).

Upgrades COPYBOOK handling from dependency-only metadata to semantic
content, reusing existing IR structures:

  COMMON.cpy
    -> resolve (copybook_resolver)
    -> CopybookModel (records as IR ``DataItem`` trees)
    -> merge into program IR (``working_storage``, provenance preserved)
    -> shared Java model class IR (``JavaClass`` in ``model`` package)
    -> rendered model source (``model/<Name>Record.java``)

A COPYBOOK is a dependency/data definition, NOT an executable program:
no model class ever carries business-logic methods or a ``main`` method,
and ``.cpy`` files are never fed to program discovery (established
behaviour, locked in by tests).

Conflict note: this module only ADDS isolated pieces. It imports from —
but never modifies — the FRNC-owned files (parser, IR, mappings, Spring
IR/generator). Pipeline wiring is specified in ``INTEGRATION`` below for
the owning lane.

REQUIRED INTERFACE (for the owning lane — signatures to add there):

  1. ``CobolParser.parse_data_description_lines(lines: list[str])
       -> list[DataItem]``
     Public promotion of the existing private ``_parse_working_storage``
     logic. ``parse_copybook`` below calls the private method today;
     switching to the public method is a one-line change with no
     semantic difference.

  2. ``ApplicationGenerator.generate`` (or ``Service._generate_application``)
     pre-step::

         materialized = materialize_application_copybooks(application, workspace)

     ``materialize_application_copybooks`` is specified here (pure,
     ``dataclasses.replace``-based) but intentionally NOT implemented
     here: constructing a new ``CobolApplication`` touches discovery-owned
     assembly semantics. The per-program primitive it needs,
     ``materialize_copybooks_into_program``, IS implemented here.

  3. ``map_copybook_model_to_java_class(model, package) -> JavaClass``:
     specified here as ``build_copybook_model_class`` (implemented, reuses
     ``map_cobol_data_items_to_fields``). The owning lane calls it once
     per ``plan_shared_models`` entry and appends the class to the
     ``JavaApplication`` model set — never to the executable program set,
     and entrypoint resolution must exclude ``*Record`` model classes.

  4. Spring Boot: carry each model ``JavaClass`` into
     ``SpringBootApplication`` (new ``models`` field, Spring-IR lane) and
     emit under ``model/`` via the Spring generator (Spring-generator
     lane). ``rendered_model_path`` below fixes the canonical path so all
     lanes agree without further coordination.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable, Mapping

from engine.transformation.copybook_resolver import ResolvedCopybook
from engine.transformation.ir import CobolProgram, DataItem

INTEGRATION = __doc__


# ---------------------------------------------------------------------------
# Semantic model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CopybookDiagnostic:
    """Controlled diagnostic from copybook materialization."""
    level: str  # "INFO", "WARNING", "ERROR"
    code: str  # e.g. "COPYBOOK_FIELD_COLLISION"
    message: str


@dataclass(frozen=True)
class CopybookModel:
    """Semantic model of one copybook file.

    ``records`` are the level-01 roots parsed from the ``.cpy`` source,
    using the IR ``DataItem`` structure (level numbers, PIC, VALUE,
    OCCURS, nested groups via ``children``) — the same structure the
    parser produces for program WORKING-STORAGE, so downstream mapping
    treats copybook fields identically to program fields.
    """
    name: str  # copybook name as referenced by COPY (upper-cased stem)
    source_path: str  # resolved .cpy file (provenance)
    records: tuple[DataItem, ...] = ()


def parse_copybook(path: str | Path) -> CopybookModel:
    """Parse a ``.cpy`` file into a ``CopybookModel``.

    Reuses the existing WORKING-STORAGE parsing logic (same PIC / VALUE /
    OCCURS / group-hierarchy semantics as program parsing) without
    duplicating or modifying it. Copybook sources contain only data
    description entries, so no division scanning is required.
    """
    from engine.transformation.cobol_parser import CobolParser

    src = Path(path)
    text = src.read_text(encoding="utf-8")
    items = CobolParser().parse_data_description_lines(text.splitlines())
    return CopybookModel(
        name=src.stem.upper(), source_path=str(src), records=tuple(items)
    )


# ---------------------------------------------------------------------------
# Program merge semantics (pure, no source rewriting, no concatenation)
# ---------------------------------------------------------------------------

def materialize_copybooks_into_program(
    program: CobolProgram,
    models: Mapping[str, CopybookModel],
) -> tuple[CobolProgram, tuple[CopybookDiagnostic, ...]]:
    """Give a program's semantic model access to its copybook-defined fields.

    For every name in ``program.copybooks`` (case-insensitive lookup into
    ``models``), the copybook's level-01 records are appended to the
    program's ``working_storage``. The COBOL source is never rewritten and
    files are never concatenated; the ``copybooks`` tuple (provenance:
    program -> copybook dependency) is preserved unchanged.

    Name collisions (a program field with the same upper-cased name as a
    copybook field, at any nesting level) keep the program's own definition
    and are reported as diagnostics — never silently overwritten, never
    duplicated. Collision filtering is recursive: a colliding child is
    dropped from its group while surviving siblings are still merged.

    Field expansion: besides each merged group record, its flattened
    elementary leaves are appended as top-level items. The existing
    COBOL->Java mapping only creates fields from top-level items, so
    without expansion group children would be unreferenceable in generated
    code. Expansion is scoped to copybook-materialized fields only;
    program-authored WORKING-STORAGE is never rewritten.
    """
    diagnostics: list[CopybookDiagnostic] = []
    existing: set[str] = set()

    def collect_names(item: DataItem) -> None:
        existing.add(item.name.upper())
        for child in item.children:
            collect_names(child)

    for top in program.working_storage:
        collect_names(top)
    # Names owned by the program itself (pre-merge). Expansion below must
    # skip these (collision already diagnosed) but must NOT skip names the
    # merge itself just registered. Cross-record duplicates are tracked
    # separately in `expanded`.
    owned = set(existing)
    expanded: set[str] = set()
    merged = list(program.working_storage)

    def collision(message_name: str) -> None:
        diagnostics.append(
            CopybookDiagnostic(
                level="WARNING",
                code="COPYBOOK_FIELD_COLLISION",
                message=message_name,
            )
        )

    def merge_item(item: DataItem, model_name: str) -> DataItem | None:
        if item.name.upper() in existing:
            collision(
                f"Program {program.program_id} keeps its own {item.name}; "
                f"copybook {model_name} definition skipped"
            )
            return None
        kept_children: list[DataItem] = []
        for child in item.children:
            merged_child = merge_item(child, model_name)
            if merged_child is not None:
                kept_children.append(merged_child)
        if item.children and not kept_children and item.pic_length == 0:
            # Structural group emptied by collision filtering: drop it
            # rather than merging a hollow shell.
            return None
        existing.add(item.name.upper())
        if len(kept_children) == len(item.children):
            return item
        return replace(item, children=tuple(kept_children))

    for ref_name in program.copybooks:
        model = models.get(ref_name.upper())
        if model is None:
            diagnostics.append(
                CopybookDiagnostic(
                    level="ERROR",
                    code="COPYBOOK_MODEL_MISSING",
                    message=(
                        f"Program {program.program_id} references COPY "
                        f"{ref_name} with no materialized model"
                    ),
                )
            )
            continue
        for record in model.records:
            merged_record = merge_item(record, model.name)
            if merged_record is None:
                continue
            merged.append(merged_record)
            # Field expansion for code generation (see docstring).
            for leaf in flatten_records((merged_record,)):
                if leaf.name.upper() == merged_record.name.upper():
                    continue  # elementary 01 record already appended itself
                if leaf.name.upper() in owned:
                    continue  # program-owned: collision already diagnosed
                if leaf.name.upper() in expanded:
                    continue  # duplicate across records: keep first only
                expanded.add(leaf.name.upper())
                existing.add(leaf.name.upper())
                merged.append(leaf)

    return replace(program, working_storage=tuple(merged), linkage_section=program.linkage_section, using_parameters=program.using_parameters), tuple(diagnostics)


# ---------------------------------------------------------------------------
# Application-level preparation (single entry point for the generator lane)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CopybookPreparation:
    """Result of preparing an application's copybooks for transformation."""
    application: object  # CobolApplication with materialized programs
    diagnostics: tuple[CopybookDiagnostic, ...] = ()
    plans: tuple[CopybookModelPlan, ...] = ()
    model_classes: tuple[object, ...] = ()  # JavaClass per plan

    @property
    def has_errors(self) -> bool:
        return any(d.level == "ERROR" for d in self.diagnostics)

    def error_messages(self) -> tuple[str, ...]:
        return tuple(d.message for d in self.diagnostics if d.level == "ERROR")


def prepare_application_copybooks(
    application, source_root=None
) -> CopybookPreparation:
    """Resolve + parse + merge copybooks for a discovered application.

    Search directories: ``source_root`` (the ingested source tree) when
    given — preferred, because unit ``source_path`` values are stored
    relative to the discovery root. Otherwise each unit's source path is
    resolved against the current working directory. COBOL sources are
    only read, never written.

    Returns materialized application + diagnostics + shared-model plans +
    built model classes. Callers must treat ``has_errors`` as a
    deterministic generation failure with ``error_messages()`` surfaced
    verbatim — never a silent fallback to unmaterialized programs.
    """
    from engine.transformation.copybook_resolver import (
        resolve_application_copybooks,
    )
    from engine.transformation.ir import CobolApplication

    refs: list[tuple[str, str]] = []
    search_dirs: list[Path] = []
    if source_root is not None:
        root = Path(source_root)
        if root.is_dir():
            search_dirs.append(root)
    for unit in application.programs:
        if unit.program is None:
            continue  # unparseable unit: generator's empty check owns this
        for cb in unit.copybooks:
            refs.append((unit.program_id, cb.copybook_name))
        candidate = Path(unit.source_path)
        if not candidate.is_absolute():
            candidate = Path.cwd() / candidate
        parent = candidate.parent
        if parent.is_dir() and parent not in search_dirs:
            search_dirs.append(parent)
    resolved, missing = resolve_application_copybooks(
        tuple(refs), tuple(search_dirs)
    )
    diagnostics: list[CopybookDiagnostic] = [
        CopybookDiagnostic(
            level="ERROR",
            code="COPYBOOK_UNRESOLVED",
            message=m.message,
        )
        for m in missing
    ]

    models: dict[str, CopybookModel] = {}
    for ref in resolved:
        key = ref.copybook_name.upper()
        if key not in models:
            try:
                models[key] = parse_copybook(ref.path)
            except OSError as exc:
                diagnostics.append(
                    CopybookDiagnostic(
                        level="ERROR",
                        code="COPYBOOK_UNREADABLE",
                        message=f"COPY {ref.copybook_name} at {ref.path}: {exc}",
                    )
                )

    merged_units = []
    for unit in application.programs:
        if unit.program is None:
            merged_units.append(unit)
            continue
        merged_program, merge_diags = materialize_copybooks_into_program(
            unit.program, models
        )
        diagnostics.extend(merge_diags)
        merged_units.append(replace(unit, program=merged_program))

    plans = plan_shared_models(
        tuple(
            r
            for r in resolved
            if r.copybook_name.upper() in models
        ),
        models,
    )
    model_classes = tuple(build_copybook_model_class(p) for p in plans)

    return CopybookPreparation(
        application=CobolApplication(
            application_id=application.application_id,
            programs=tuple(merged_units),
            copybooks=application.copybooks,
            edges=application.edges,
        ),
        diagnostics=tuple(diagnostics),
        plans=plans,
        model_classes=model_classes,
    )


# ---------------------------------------------------------------------------
# Shared-model planning (dedup across programs)
# ---------------------------------------------------------------------------

MODEL_PACKAGE = "com.generated.app.model"


def to_model_class_name(copybook_stem: str) -> str:
    """Derive the shared model class name: ``COMMON`` -> ``CommonRecord``."""
    parts = [p for p in copybook_stem.replace("_", "-").split("-") if p]
    base = "".join(p[:1].upper() + p[1:].lower() for p in parts) or "Copybook"
    return f"{base}Record"


@dataclass(frozen=True)
class CopybookModelPlan:
    """One shared model class for one copybook, used by N programs."""
    class_name: str
    package: str
    copybook_name: str  # upper-cased stem
    source_path: str
    using_programs: tuple[str, ...]  # sorted PROGRAM-IDs
    fields: tuple[DataItem, ...] = ()  # flattened elementary items


def flatten_records(records: Iterable[DataItem]) -> tuple[DataItem, ...]:
    """Flatten record trees to elementary items for field generation.

    Group nodes without their own PIC are structural only: their children
    are carried, the group itself is dropped. Elementary items (PIC length
    or OCCURS) are kept with OCCURS preserved. Original COBOL field names
    are kept verbatim (downstream mapping applies dash-to-underscore).
    """
    flat: list[DataItem] = []

    def visit(item: DataItem) -> None:
        if item.children and item.pic_length == 0 and item.occurs is None:
            for child in item.children:
                visit(child)
            return
        flat.append(item)
        # An OCCURS group still exposes its elementary children as well,
        # so element-level references resolve; the group row itself keeps
        # the OCCURS table shape.
        for child in item.children:
            visit(child)

    for record in records:
        visit(record)

    seen: set[str] = set()
    deduped: list[DataItem] = []
    for item in flat:
        key = item.name.upper()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return tuple(deduped)


def plan_shared_models(
    resolved: Iterable[ResolvedCopybook],
    models: Mapping[str, CopybookModel],
) -> tuple[CopybookModelPlan, ...]:
    """Plan one shared model class per copybook (dedup by stem).

    The same copybook used by many programs yields exactly one plan whose
    ``using_programs`` lists every consumer — conflicting duplicate model
    classes are impossible by construction.
    """
    by_copybook: dict[str, set[str]] = {}
    for ref in resolved:
        by_copybook.setdefault(ref.copybook_name.upper(), set()).add(
            ref.program_id
        )
    plans: list[CopybookModelPlan] = []
    for copybook_upper in sorted(by_copybook):
        model = models.get(copybook_upper)
        if model is None:
            continue
        fields: tuple[DataItem, ...] = ()
        for record in model.records:
            fields += flatten_records((record,))
        # Dedupe across multiple 01 records of one copybook.
        seen: set[str] = set()
        unique: list[DataItem] = []
        for field in fields:
            if field.name.upper() in seen:
                continue
            seen.add(field.name.upper())
            unique.append(field)
        plans.append(
            CopybookModelPlan(
                class_name=to_model_class_name(copybook_upper),
                package=MODEL_PACKAGE,
                copybook_name=copybook_upper,
                source_path=model.source_path,
                using_programs=tuple(sorted(by_copybook[copybook_upper])),
                fields=tuple(unique),
            )
        )
    return tuple(plans)


# ---------------------------------------------------------------------------
# Java representation (shared model class IR + source)
# ---------------------------------------------------------------------------

def build_copybook_model_class(plan: CopybookModelPlan):
    """Build the shared model ``JavaClass`` for a plan (REQUIRED-INTERFACE 3).

    Reuses ``map_cobol_data_items_to_fields`` so copybook fields get the
    identical Java types/defaults as program WORKING-STORAGE fields, then
    converts them to private instance state with public accessors. The
    class carries data only: no business-logic methods, no ``main``.
    """
    from dataclasses import replace as dc_replace

    from engine.transformation.cobol_to_java_mapping import (
        map_cobol_data_items_to_fields,
    )
    from engine.transformation.java_ir import (
        JavaAssignment,
        JavaClass,
        JavaConstructor,
        JavaMethod,
        JavaParameter,
        JavaReturn,
        JavaType,
        JavaBasicType,
        JavaVariableRef,
    )

    static_fields = map_cobol_data_items_to_fields(plan.fields)
    fields = tuple(
        dc_replace(f, is_static=False, modifiers=("private",))
        for f in static_fields
    )

    methods: list[JavaMethod] = []
    for field in fields:
        cap = field.name[:1].upper() + field.name[1:]
        methods.append(
            JavaMethod(
                name=f"get{cap}",
                return_type=field.java_type,
                parameters=(),
                body_statements=(
                    JavaReturn(
                        expression=JavaVariableRef(name=f"this.{field.name}")
                    ),
                ),
                modifiers=("public",),
                is_static=False,
            )
        )
        param_type = field.java_type
        methods.append(
            JavaMethod(
                name=f"set{cap}",
                return_type=JavaType(basic_type=JavaBasicType.VOID),
                parameters=(JavaParameter(java_type=param_type, name="value"),),
                body_statements=(
                    JavaAssignment(
                        target=f"this.{field.name}",
                        expression=JavaVariableRef(name="value"),
                    ),
                ),
                modifiers=("public",),
                is_static=False,
            )
        )

    return JavaClass(
        name=plan.class_name,
        package=plan.package,
        fields=fields,
        methods=tuple(methods),
        constructors=(
            JavaConstructor(class_name=plan.class_name, parameters=()),
        ),
        modifiers=("public",),
    )


def rendered_model_path(plan: CopybookModelPlan) -> str:
    """Canonical Spring Boot project path: ``model/CommonRecord.java``."""
    return f"src/main/java/{plan.package.replace('.', '/')}/{plan.class_name}.java"


def _render_expression(expr) -> str:
    from engine.transformation.java_ir import JavaLiteral, JavaVariableRef

    if isinstance(expr, JavaLiteral):
        return expr.value
    if isinstance(expr, JavaVariableRef):
        return expr.name
    return str(expr)


def render_model_class(cls) -> str:
    """Render a model ``JavaClass`` (as built above) to Java source.

    Minimal renderer scoped to the model-class shape (fields, constructor,
    accessors). Full program rendering stays in the Java-generator lane.
    """
    from engine.transformation.java_ir import (
        JavaAssignment,
        JavaReturn,
    )

    lines = [
        f"package {cls.package};",
        "",
        "/**",
        f" * Shared data model materialized from COPYBOOK.",
        " * Auto-generated: data definition only, no business logic.",
        " */",
        f"public class {cls.name} {{",
    ]
    for field in cls.fields:
        init = (
            f" = {_render_expression(field.initializer)}"
            if field.initializer is not None
            else ""
        )
        lines.append(f"    private {field.java_type.to_source()} {field.name}{init};")
    lines.append("")
    lines.append(f"    public {cls.name}() {{}}")
    for method in cls.methods:
        params = ", ".join(
            f"{p.java_type.to_source()} {p.name}" for p in method.parameters
        )
        lines.append("")
        lines.append(
            f"    public {method.return_type.to_source()} {method.name}({params}) {{"
        )
        for stmt in method.body_statements:
            if isinstance(stmt, JavaReturn):
                lines.append(f"        return {_render_expression(stmt.expression)};")
            elif isinstance(stmt, JavaAssignment):
                lines.append(
                    f"        {stmt.target} = {_render_expression(stmt.expression)};"
                )
        lines.append("    }")
    lines.append("}")
    return "\n".join(lines) + "\n"


def generate_copybook_model_sources(
    plans: Iterable[CopybookModelPlan],
) -> tuple[tuple[str, str], ...]:
    """Render ``(project_path, source)`` pairs for shared model classes."""
    return tuple(
        (rendered_model_path(plan), render_model_class(build_copybook_model_class(plan)))
        for plan in plans
    )
