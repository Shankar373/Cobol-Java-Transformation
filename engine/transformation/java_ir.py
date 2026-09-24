"""Java application IR — generic target model for COBOL → Java transformation.

Defines the intermediate representation for a Java application that is
the target of COBOL semantic transformation. This model is workload-agnostic:
it represents Java application structure independently of any particular
COBOL source domain.

Architecture:

    JavaApplication
    ├── JavaProgram (one per COBOL program)
    │   ├── JavaClass
    │   │   ├── JavaField
    │   │   ├── JavaMethod
    │   │   │   ├── JavaStatement
    │   │   │   │   ├── JavaAssignment
    │   │   │   │   ├── JavaMethodCall
    │   │   │   │   ├── JavaIf
    │   │   │   │   ├── JavaWhile
    │   │   │   │   ├── JavaTryCatch
    │   │   │   │   ├── JavaReturn
    │   │   │   │   ├── JavaThrow
    │   │   │   │   ├── JavaBlock
    │   │   │   │   └── JavaComment
    │   │   │   └── JavaParameter
    │   │   └── JavaConstructor
    │   ├── JavaFileResource
    │   ├── JavaDatabaseResource
    │   └── JavaTransactionBoundary
    └── JavaDependency

Status domains remain distinct:
    - application_status (COBOL application logic)
    - file_status (FILE STATUS IS)
    - sqlcode (SQLCODE)
    - sqlstate (SQLSTATE)
    - cics_resp (CICS RESP)
    - cics_resp2 (CICS RESP2)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


# ---------------------------------------------------------------------------
# Java type system
# ---------------------------------------------------------------------------

class JavaBasicType(Enum):
    """Basic Java types mapped from COBOL PIC."""
    INT = "int"
    LONG = "long"
    DOUBLE = "double"
    STRING = "String"
    BOOLEAN = "boolean"
    CHAR = "char"
    VOID = "void"
    OBJECT = "Object"


@dataclass(frozen=True)
class JavaType:
    """A Java type reference.

    Can be a basic type, array type, or named type (class/interface).
    """
    basic_type: JavaBasicType | None = None
    class_name: str = ""  # for named types (e.g. "List", "Map")
    is_array: bool = False
    array_element_type: JavaType | None = None
    is_nullable: bool = False
    generic_type_params: tuple[JavaType, ...] = ()  # e.g. List<String>

    @property
    def is_basic(self) -> bool:
        return self.basic_type is not None

    @property
    def is_void(self) -> bool:
        return self.basic_type == JavaBasicType.VOID

    def to_source(self) -> str:
        """Render type as Java source string."""
        if self.basic_type:
            return self.basic_type.value
        if self.class_name:
            if self.generic_type_params:
                params = ", ".join(p.to_source() for p in self.generic_type_params)
                return f"{self.class_name}<{params}>"
            return self.class_name
        return "Object"


# ---------------------------------------------------------------------------
# Java expressions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class JavaExpression:
    """Base class for Java expressions."""
    pass


@dataclass(frozen=True)
class JavaLiteral(JavaExpression):
    """A literal value."""
    value: str  # the literal text
    java_type: JavaType | None = None


@dataclass(frozen=True)
class JavaVariableRef(JavaExpression):
    """A reference to a Java variable/field."""
    name: str


@dataclass(frozen=True)
class JavaBinaryOp(JavaExpression):
    """A binary operation."""
    left: JavaExpression
    operator: str  # +, -, *, /, ==, !=, <, >, <=, >=, &&, ||
    right: JavaExpression


@dataclass(frozen=True)
class JavaUnaryOp(JavaExpression):
    """A unary operation."""
    operator: str  # -, !, ~
    operand: JavaExpression


@dataclass(frozen=True)
class JavaMethodCall(JavaExpression):
    """A method call expression."""
    object_ref: JavaExpression | None = None  # null for static calls
    method_name: str = ""
    arguments: tuple[JavaExpression, ...] = ()
    is_static: bool = False
    class_name: str = ""  # for static calls


@dataclass(frozen=True)
class JavaNewObject(JavaExpression):
    """A new object expression."""
    class_name: str = ""
    arguments: tuple[JavaExpression, ...] = ()


@dataclass(frozen=True)
class JavaTernary(JavaExpression):
    """A ternary expression."""
    condition: JavaExpression
    true_expr: JavaExpression
    false_expr: JavaExpression


@dataclass(frozen=True)
class JavaStringConcat(JavaExpression):
    """String concatenation."""
    parts: tuple[JavaExpression, ...] = ()


@dataclass(frozen=True)
class JavaCast(JavaExpression):
    """Type cast."""
    target_type: JavaType
    expression: JavaExpression


# ---------------------------------------------------------------------------
# Java statements
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class JavaStatement:
    """Base class for Java statements."""
    pass


@dataclass(frozen=True)
class JavaAssignment(JavaStatement):
    """Variable assignment."""
    target: str  # variable name
    expression: JavaExpression
    java_type: JavaType | None = None  # for declarations


@dataclass(frozen=True)
class JavaLocalVarDecl(JavaStatement):
    """Local variable declaration."""
    java_type: JavaType
    name: str
    initializer: JavaExpression | None = None


@dataclass(frozen=True)
class JavaMethodCallStatement(JavaStatement):
    """Method call as statement (discard return value)."""
    call: JavaMethodCall


@dataclass(frozen=True)
class JavaIf(JavaStatement):
    """If/else statement."""
    condition: JavaExpression
    then_body: tuple[JavaStatement, ...] = ()
    else_body: tuple[JavaStatement, ...] = ()


@dataclass(frozen=True)
class JavaWhile(JavaStatement):
    """While loop."""
    condition: JavaExpression
    body: tuple[JavaStatement, ...] = ()


@dataclass(frozen=True)
class JavaDoWhile(JavaStatement):
    """Do-while loop (PERFORM UNTIL WITH TEST AFTER)."""
    condition: JavaExpression
    body: tuple[JavaStatement, ...] = ()


@dataclass(frozen=True)
class JavaFor(JavaStatement):
    """For loop."""
    init: JavaStatement | None = None
    condition: JavaExpression | None = None
    update: JavaStatement | None = None
    body: tuple[JavaStatement, ...] = ()


@dataclass(frozen=True)
class JavaTryCatch(JavaStatement):
    """Try-catch block."""
    try_body: tuple[JavaStatement, ...] = ()
    catch_type: str = "Exception"  # exception class name
    catch_var: str = "e"
    catch_body: tuple[JavaStatement, ...] = ()
    finally_body: tuple[JavaStatement, ...] = ()


@dataclass(frozen=True)
class JavaReturn(JavaStatement):
    """Return statement."""
    expression: JavaExpression | None = None


@dataclass(frozen=True)
class JavaThrow(JavaStatement):
    """Throw statement."""
    exception_class: str = "RuntimeException"
    message: str = ""


@dataclass(frozen=True)
class JavaBlock(JavaStatement):
    """A block of statements."""
    statements: tuple[JavaStatement, ...] = ()


@dataclass(frozen=True)
class JavaComment(JavaStatement):
    """A comment line."""
    text: str = ""


@dataclass(frozen=True)
class JavaSwitch(JavaStatement):
    """Switch statement."""
    expression: JavaExpression
    cases: tuple[tuple[JavaExpression, tuple[JavaStatement, ...]], ...] = ()
    default_body: tuple[JavaStatement, ...] = ()


# ---------------------------------------------------------------------------
# Java class members
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class JavaParameter:
    """A method parameter."""
    java_type: JavaType
    name: str


@dataclass(frozen=True)
class JavaField:
    """A class field (static or instance)."""
    java_type: JavaType
    name: str
    initializer: JavaExpression | None = None
    is_static: bool = True
    is_final: bool = False
    modifiers: tuple[str, ...] = ()  # additional modifiers
    format_width: int = 0  # PIC display width for numeric formatting (0 = no formatting)


@dataclass(frozen=True)
class JavaMethod:
    """A Java method."""
    name: str
    return_type: JavaType = JavaType(basic_type=JavaBasicType.VOID)
    parameters: tuple[JavaParameter, ...] = ()
    body_statements: tuple[JavaStatement, ...] = ()
    modifiers: tuple[str, ...] = ("public",)
    is_static: bool = True
    exceptions: tuple[str, ...] = ()  # checked exceptions


@dataclass(frozen=True)
class JavaConstructor:
    """A Java constructor."""
    class_name: str
    parameters: tuple[JavaParameter, ...] = ()
    body_statements: tuple[JavaStatement, ...] = ()
    modifiers: tuple[str, ...] = ("public",)


@dataclass(frozen=True)
class JavaClass:
    """A Java class."""
    name: str
    package: str = ""
    fields: tuple[JavaField, ...] = ()
    methods: tuple[JavaMethod, ...] = ()
    constructors: tuple[JavaConstructor, ...] = ()
    inner_classes: tuple[JavaClass, ...] = ()
    modifiers: tuple[str, ...] = ("public",)
    extends: str = ""  # superclass name
    implements: tuple[str, ...] = ()  # interface names
    imports: tuple[str, ...] = ()  # import statements
    source_copybook: str = ""  # originating COPYBOOK stem (models only)


# ---------------------------------------------------------------------------
# Resource abstractions
# ---------------------------------------------------------------------------

class JavaFileAccessMode(Enum):
    """File access mode."""
    READ = "READ"
    WRITE = "WRITE"
    READ_WRITE = "READ_WRITE"
    APPEND = "APPEND"


class JavaFileOrganization(Enum):
    """File organization type — derived from COBOL SELECT clause."""
    SEQUENTIAL = "SEQUENTIAL"
    INDEXED = "INDEXED"
    RELATIVE = "RELATIVE"


@dataclass(frozen=True)
class JavaFileKey:
    """A file key definition — derived from COBOL RECORD KEY / ALTERNATE RECORD KEY."""
    field_name: str
    key_type: str = "PRIMARY"  # PRIMARY, ALTERNATE, RELATIVE
    is_duplicated: bool = False


@dataclass(frozen=True)
class JavaFileResource:
    """A file resource in the Java application.

    Maps from COBOL file definitions. Represents the target persistence
    abstraction without prescribing implementation details.
    """
    name: str  # logical resource name
    path: str = ""  # file path or container path
    access_mode: JavaFileAccessMode = JavaFileAccessMode.READ
    record_delimiter: str | None = None  # field delimiter — derived from source, not invented
    is_text: bool = True
    # Status domain: kept distinct from other status types
    status_field: str = ""  # COBOL FILE STATUS field name
    status_java_type: JavaType = JavaType(basic_type=JavaBasicType.STRING)
    # File organization — derived from COBOL SELECT clause
    organization: JavaFileOrganization = JavaFileOrganization.SEQUENTIAL
    record_key: JavaFileKey | None = None  # RECORD KEY IS
    alternate_keys: tuple[JavaFileKey, ...] = ()  # ALTERNATE RECORD KEY IS
    relative_key: str = ""  # RELATIVE KEY IS
    record_contains: int | None = None  # RECORD CONTAINS n CHARACTERS


class JavaSqlOperationType(Enum):
    """SQL operation type."""
    SELECT = "SELECT"
    INSERT = "INSERT"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    SELECT_INTO = "SELECT_INTO"
    CURSOR_OPEN = "CURSOR_OPEN"
    CURSOR_FETCH = "CURSOR_FETCH"
    CURSOR_CLOSE = "CURSOR_CLOSE"
    COMMIT = "COMMIT"
    ROLLBACK = "ROLLBACK"


@dataclass(frozen=True)
class JavaDatabaseResource:
    """A database resource in the Java application.

    Maps from COBOL embedded SQL. Represents the target persistence
    abstraction without prescribing JPA/JDBC implementation.
    """
    name: str  # logical resource name (table name)
    operation: JavaSqlOperationType = JavaSqlOperationType.SELECT
    columns: tuple[str, ...] = ()
    schema: str = ""
    # Status domain: kept distinct
    sqlcode_field: str = ""  # COBOL SQLCODE variable
    sqlstate_field: str = ""  # COBOL SQLSTATE variable


class JavaTransactionType(Enum):
    """Transaction boundary type."""
    CICS_TRANSACTION = "CICS_TRANSACTION"
    DB2_TRANSACTION = "DB2_TRANSACTION"
    BATCH_STEP = "BATCH_STEP"
    METHOD_BOUNDARY = "METHOD_BOUNDARY"


@dataclass(frozen=True)
class JavaTransactionBoundary:
    """A transaction boundary in the Java application.

    Maps from CICS transaction or DB2 transaction. Represents the target
    transaction abstraction without prescribing implementation.
    """
    name: str  # transaction identifier
    transaction_type: JavaTransactionType = JavaTransactionType.METHOD_BOUNDARY
    # Status domain: kept distinct
    resp_field: str = ""  # CICS RESP field
    resp2_field: str = ""  # CICS RESP2 field
    sqlcode_field: str = ""  # SQLCODE field


# ---------------------------------------------------------------------------
# Application composition
# ---------------------------------------------------------------------------

class JavaDependencyType(Enum):
    """Type of dependency between Java programs."""
    METHOD_CALL = "METHOD_CALL"  # direct method call
    INTERFACE_CALL = "INTERFACE_CALL"  # interface-based call
    SERVICE_CALL = "SERVICE_CALL"  # service invocation
    DATABASE = "DATABASE"  # database access
    FILE = "FILE"  # file access
    TRANSACTION = "TRANSACTION"  # transaction boundary


@dataclass(frozen=True)
class JavaDependency:
    """A dependency edge in the Java application graph."""
    source: str  # source program/class name
    target: str  # target program/class/resource name
    dependency_type: JavaDependencyType
    metadata: str = ""


# ---------------------------------------------------------------------------
# Decision-mode metadata
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class JavaStatusCodeMapping:
    """A status code value and its label, mapped to Java semantics.

    Generator produces: if (statusVar.equals("R")) { result = "REJECTED"; counter++; }
    All values are source-derived — not invented.
    """
    code: str  # e.g. "R", "P", "A"
    label: str  # e.g. "REJECTED", "PENDING"
    counter_name: str  # Java variable name for the counter (e.g. "rejected")


@dataclass(frozen=True)
class JavaThresholdRule:
    """A numeric threshold constant for decision logic.

    Generator produces: static final int THRESHOLD = {value};
    Value is source-derived — not invented.
    """
    field_name: str  # the Java field this threshold applies to
    operator: str  # ">", "<", ">=", "<="
    value: int
    constant_name: str = "THRESHOLD"  # Java constant name


@dataclass(frozen=True)
class JavaSummaryField:
    """A summary field for aggregate output.

    Generator produces: System.out.println("FIELD=" + String.format("%06d", fieldVar));
    Width is source-derived from PIC metadata.
    """
    field_name: str  # original field name (for display label)
    java_var_name: str  # Java variable name
    format_width: int = 0  # from PIC metadata — 0 means no formatting
    is_numeric: bool = True


@dataclass(frozen=True)
class JavaReportConfig:
    """Report output configuration for decision-mode generation.

    Generator produces: rpt.println("HEADER"); rpt.printf(...)
    All values are source-derived.
    """
    header: str = ""  # report header text
    report_file_name: str = ""  # logical name of report output file
    output_file_name: str = ""  # logical name of secondary output file
    report_fields: tuple[JavaSummaryField, ...] = ()  # fields in report record
    output_fields: tuple[JavaSummaryField, ...] = ()  # fields in output record
    # Record format: field names and literal delimiters for printf
    report_format_fields: tuple[str, ...] = ()  # alternates: field names and literals
    output_format_fields: tuple[str, ...] = ()  # alternates: field names and literals


@dataclass(frozen=True)
class JavaMatchOutcome:
    """Match outcome labels for lookup-based decision logic.

    Generator produces: paid/partial/unpaid counter logic.
    Labels are source-derived from COBOL MOVE statements.
    """
    paid_label: str = ""
    partial_label: str = ""
    unpaid_label: str = ""


@dataclass(frozen=True)
class JavaProgram:
    """A single Java program unit within an application.

    Maps from a COBOL program. Contains the class, resources,
    and dependency information.
    """
    program_id: str  # original COBOL PROGRAM-ID
    java_class: JavaClass | None = None
    source_file: str = ""  # path to original COBOL source
    # Resources
    file_resources: tuple[JavaFileResource, ...] = ()
    database_resources: tuple[JavaDatabaseResource, ...] = ()
    transaction_boundaries: tuple[JavaTransactionBoundary, ...] = ()
    # Dependencies
    calls: tuple[str, ...] = ()  # programs this one calls
    called_by: tuple[str, ...] = ()  # programs that call this one
    copybooks: tuple[str, ...] = ()  # copybook references
    # COBOL metadata (preserved for traceability)
    cobol_program_id: str = ""  # original PROGRAM-ID
    entry_points: tuple[str, ...] = ()
    # Status domains — all kept distinct
    has_file_status: bool = False
    has_sqlcode: bool = False
    has_sqlstate: bool = False
    has_cics_resp: bool = False
    has_cics_resp2: bool = False
    # Decision-mode metadata (all source-derived, not invented)
    status_codes: tuple[JavaStatusCodeMapping, ...] = ()
    threshold_rules: tuple[JavaThresholdRule, ...] = ()
    summary_fields: tuple[JavaSummaryField, ...] = ()
    report_config: JavaReportConfig | None = None
    match_outcomes: tuple[JavaMatchOutcome, ...] = ()
    # Generation mode hint (derived from capabilities, preserved for generator)
    generation_mode: str = ""  # "decision", "file_io", or "minimal"
    # Input record field names (positional — which fields are parsed from input records)
    input_record_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class JavaApplication:
    """A complete Java application model.

    Represents the target application generated from one or more COBOL programs.
    This is the top-level container that a Java source generator consumes.
    """
    application_id: str  # derived from COBOL application
    programs: tuple[JavaProgram, ...] = ()
    dependencies: tuple[JavaDependency, ...] = ()
    # Shared resources
    shared_file_resources: tuple[JavaFileResource, ...] = ()
    shared_database_resources: tuple[JavaDatabaseResource, ...] = ()
    shared_transaction_boundaries: tuple[JavaTransactionBoundary, ...] = ()
    # Source traceability
    source_paths: tuple[str, ...] = ()  # paths to original COBOL sources

    def get_program(self, program_id: str) -> JavaProgram | None:
        """Find a program by its ID."""
        for p in self.programs:
            if p.program_id == program_id:
                return p
        return None

    def get_dependencies(self, program_id: str) -> list[JavaDependency]:
        """Get all dependencies for a program."""
        return [d for d in self.dependencies if d.source == program_id]

    def get_callers(self, target: str) -> list[str]:
        """Find all programs that call the target."""
        return [d.source for d in self.dependencies
                if d.target == target
                and d.dependency_type in (JavaDependencyType.METHOD_CALL, JavaDependencyType.INTERFACE_CALL)]

    def get_callees(self, source: str) -> list[str]:
        """Find all programs called by the source."""
        return [d.target for d in self.dependencies
                if d.source == source
                and d.dependency_type in (JavaDependencyType.METHOD_CALL, JavaDependencyType.INTERFACE_CALL)]

    def get_all_file_resources(self) -> list[JavaFileResource]:
        """Get all file resources (shared + per-program)."""
        resources: list[JavaFileResource] = list(self.shared_file_resources)
        for prog in self.programs:
            for res in prog.file_resources:
                if res.name not in [r.name for r in resources]:
                    resources.append(res)
        return resources

    def get_all_database_resources(self) -> list[JavaDatabaseResource]:
        """Get all database resources (shared + per-program)."""
        resources: list[JavaDatabaseResource] = list(self.shared_database_resources)
        for prog in self.programs:
            for res in prog.database_resources:
                if res.name not in [r.name for r in resources]:
                    resources.append(res)
        return resources

    def validate(self) -> list[str]:
        """Validate the Java application model.

        Returns list of validation errors.
        """
        errors: list[str] = []

        # Check for duplicate program IDs
        seen_ids: set[str] = set()
        for p in self.programs:
            if p.program_id in seen_ids:
                errors.append(f"Duplicate program ID: {p.program_id}")
            seen_ids.add(p.program_id)

        # Check for unresolved dependencies
        for dep in self.dependencies:
            if dep.dependency_type in (JavaDependencyType.METHOD_CALL, JavaDependencyType.INTERFACE_CALL):
                if dep.target not in seen_ids:
                    errors.append(f"Unresolved dependency target: {dep.target} (from {dep.source})")

        # Check for programs without classes
        for p in self.programs:
            if p.java_class is None:
                errors.append(f"Program {p.program_id} has no Java class")

        return errors

    def detect_cycles(self) -> list[list[str]]:
        """Detect cycles in the CALL dependency graph.

        Returns list of cycles found. Each cycle is a list of program IDs.
        Empty list means no cycles.
        """
        cycles: list[list[str]] = []
        visited: set[str] = set()
        rec_stack: set[str] = set()
        path: list[str] = []

        def _dfs(node: str) -> None:
            visited.add(node)
            rec_stack.add(node)
            path.append(node)

            for dep in self.dependencies:
                if dep.source == node and dep.dependency_type in (
                    JavaDependencyType.METHOD_CALL,
                    JavaDependencyType.INTERFACE_CALL,
                ):
                    if dep.target not in visited:
                        _dfs(dep.target)
                    elif dep.target in rec_stack:
                        cycle_start = path.index(dep.target)
                        cycles.append(path[cycle_start:] + [dep.target])

            path.pop()
            rec_stack.discard(node)

        for prog in self.programs:
            if prog.program_id not in visited:
                _dfs(prog.program_id)

        return cycles

    def get_call_chain(self, source: str) -> list[str]:
        """Get the full call chain from a source program (BFS).

        Returns list of program IDs reachable from source via CALL dependencies.
        """
        chain: list[str] = []
        visited: set[str] = {source}
        queue = [source]

        while queue:
            current = queue.pop(0)
            for dep in self.dependencies:
                if dep.source == current and dep.dependency_type in (
                    JavaDependencyType.METHOD_CALL,
                    JavaDependencyType.INTERFACE_CALL,
                ):
                    if dep.target not in visited:
                        visited.add(dep.target)
                        chain.append(dep.target)
                        queue.append(dep.target)

        return chain

    def get_all_resources_deduplicated(self) -> dict[str, list]:
        """Get all resources across programs, deduplicated by name.

        Returns dict with keys: files, databases, transactions.
        Each value is a list of unique resources.
        """
        files: dict[str, JavaFileResource] = {}
        databases: dict[str, JavaDatabaseResource] = {}
        transactions: dict[str, JavaTransactionBoundary] = {}

        for res in self.shared_file_resources:
            files[res.name] = res
        for res in self.shared_database_resources:
            databases[res.name] = res
        for res in self.shared_transaction_boundaries:
            transactions[res.name] = res

        for prog in self.programs:
            for res in prog.file_resources:
                if res.name not in files:
                    files[res.name] = res
            for res in prog.database_resources:
                if res.name not in databases:
                    databases[res.name] = res
            for res in prog.transaction_boundaries:
                if res.name not in transactions:
                    transactions[res.name] = res

        return {
            "files": list(files.values()),
            "databases": list(databases.values()),
            "transactions": list(transactions.values()),
        }
