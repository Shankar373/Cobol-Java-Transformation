"""Intermediate representation for COBOL programs.

Defines the IR nodes that represent a parsed COBOL program. The IR
preserves enough semantics to generate correct Java for the supported
COBOL constructs.

Architecture:

    CobolProgram
    ├── FileDefinition (FILE-CONTROL → file paths)
    ├── DataItem (WORKING-STORAGE → variables/tables)
    └── Paragraph (PROCEDURE DIVISION → statements)
        └── Statement (control flow, I/O, data manipulation)

Expression hierarchy:

    Expression
    ├── Literal (numeric/string literal)
    ├── FieldReference (COBOL field name)
    ├── UnaryExpression (NOT, -)
    └── BinaryExpression (+, -, *, /, =, <>, >, <, >=, <=, AND, OR)

Condition hierarchy:

    Condition
    ├── Comparison (left op right)
    ├── BooleanCondition (field IS/IS NOT condition-name)
    ├── LogicalCondition (left AND/OR right)
    └── NegatedCondition (NOT condition)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

# ---------------------------------------------------------------------------
# PIC clause types
# ---------------------------------------------------------------------------

class PicType(Enum):
    ALPHANUMERIC = "ALPHANUMERIC"
    NUMERIC = "NUMERIC"


# ---------------------------------------------------------------------------
# Expressions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Expression:
    """Base class for COBOL expressions."""
    pass


@dataclass(frozen=True)
class Literal(Expression):
    """A literal value (numeric or string).

    Examples:
        42
        3.14
        'HELLO'
        "WORLD"
    """
    value: str  # the raw literal text
    is_numeric: bool = False
    is_signed: bool = False


@dataclass(frozen=True)
class FieldReference(Expression):
    """A reference to a COBOL field/variable.

    Examples:
        CUSTOMER-ID
        WS-TOTAL
        AMOUNT
    """
    name: str  # the COBOL field name


@dataclass(frozen=True)
class UnaryExpression(Expression):
    """A unary operation.

    Examples:
        NOT flag
        -amount
    """
    operator: str  # "NOT", "-"
    operand: Expression


@dataclass(frozen=True)
class BinaryExpression(Expression):
    """A binary operation.

    Examples:
        A + B
        AMOUNT * RATE
        TOTAL / COUNT
        flag1 AND flag2
    """
    left: Expression
    operator: str  # "+", "-", "*", "/", "AND", "OR"
    right: Expression


# ---------------------------------------------------------------------------
# Conditions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Condition:
    """Base class for COBOL conditions."""
    pass


@dataclass(frozen=True)
class Comparison(Condition):
    """A comparison condition.

    Examples:
        AMOUNT > 1000
        STATUS = 'R'
        BALANCE <= LIMIT
    """
    left: Expression
    operator: str  # "=", "<>", ">", "<", ">=", "<="
    right: Expression


@dataclass(frozen=True)
class BooleanCondition(Condition):
    """A boolean condition (field IS/IS NOT condition-name).

    Examples:
        flag IS HIGH
        flag IS NOT ZERO
    """
    field: FieldReference
    is_negated: bool = False
    condition_name: str = ""  # the 88-level condition name


@dataclass(frozen=True)
class LogicalCondition(Condition):
    """A logical combination of conditions.

    Examples:
        A > 1 AND B < 10
        X = 'Y' OR Z = 'N'
    """
    left: Condition
    operator: str  # "AND", "OR"
    right: Condition


@dataclass(frozen=True)
class NegatedCondition(Condition):
    """A negated condition.

    Examples:
        NOT (A > B)
        NOT flag
    """
    condition: Condition


# ---------------------------------------------------------------------------
# Data definitions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DataItem:
    """A single data item (variable or table entry).

    Represents COBOL PIC definitions in WORKING-STORAGE or FILE SECTION.

    Supports:
    - Level numbers (01, 05, 10, etc.)
    - Field names
    - PIC clauses (X, 9, etc.)
    - VALUE clauses
    - OCCURS clauses
    - Group hierarchy (children)
    """
    name: str
    level: int = 1  # COBOL level number (01, 05, 10, 77, 88, etc.)
    pic_type: PicType = PicType.ALPHANUMERIC
    pic_length: int = 0
    decimal_places: int = 0  # V clause: digits after decimal point
    value: str | None = None
    occurs: int | None = None
    redefines: str | None = None  # REDEFINES clause
    children: tuple[DataItem, ...] = ()

    @property
    def is_alphanumeric(self) -> bool:
        return self.pic_type == PicType.ALPHANUMERIC

    @property
    def is_numeric(self) -> bool:
        return self.pic_type == PicType.NUMERIC

    @property
    def is_table(self) -> bool:
        return self.occurs is not None and self.occurs > 0

    @property
    def is_group(self) -> bool:
        return len(self.children) > 0

    @property
    def is_elementary(self) -> bool:
        return len(self.children) == 0 and self.pic_length > 0

    @property
    def is_condition_name(self) -> bool:
        return self.level == 88

    @property
    def format_width(self) -> int:
        """Total display width for numeric formatting.

        Derived from PIC: integer digits + decimal places.
        For PIC 9(6): width=6, decimal_places=0
        For PIC 9(6)V99: width=8, decimal_places=2
        """
        return self.pic_length + self.decimal_places

    @property
    def is_decimal(self) -> bool:
        """Whether this field has decimal places (V clause)."""
        return self.decimal_places > 0


# ---------------------------------------------------------------------------
# File definitions
# ---------------------------------------------------------------------------

class FileOrganization(Enum):
    """File organization type."""
    SEQUENTIAL = "SEQUENTIAL"
    INDEXED = "INDEXED"
    RELATIVE = "RELATIVE"


class FileAccessMode(Enum):
    """File access mode."""
    SEQUENTIAL = "SEQUENTIAL"
    RANDOM = "RANDOM"
    DYNAMIC = "DYNAMIC"


class FileKeyType(Enum):
    """File key type."""
    PRIMARY = "PRIMARY"
    ALTERNATE = "ALTERNATE"
    RELATIVE = "RELATIVE"


@dataclass(frozen=True)
class FileKey:
    """A file key definition.

    Represents RECORD KEY or ALTERNATE RECORD KEY.
    """
    field_name: str  # the COBOL field name
    key_type: FileKeyType = FileKeyType.PRIMARY
    is_duplicated: bool = False  # DUPLICATES option for alternate keys


@dataclass(frozen=True)
class FileDefinition:
    """A COBOL file definition from FILE-CONTROL and FILE SECTION.

    Maps a COBOL file name to a container path and record structure.
    Enhanced with organization, access mode, keys, and status.
    """
    name: str
    container_path: str
    record_name: str
    record_items: tuple[DataItem, ...] = ()
    # File semantics (from SELECT clause)
    organization: FileOrganization = FileOrganization.SEQUENTIAL
    access_mode: FileAccessMode = FileAccessMode.SEQUENTIAL
    record_key: FileKey | None = None
    alternate_keys: tuple[FileKey, ...] = ()
    relative_key: str = ""  # RELATIVE KEY IS field-name
    file_status_field: str = ""  # FILE STATUS IS field-name
    # FD metadata
    record_contains: int | None = None  # RECORD CONTAINS n CHARACTERS
    block_contains: int | None = None  # BLOCK CONTAINS n RECORDS


@dataclass(frozen=True)
class OpenStatement:
    """OPEN INPUT/OUTPUT/I-O/EXTEND file."""
    mode: str  # "INPUT", "OUTPUT", "I-O", "EXTEND"
    file_name: str


@dataclass(frozen=True)
class CloseStatement:
    """CLOSE file."""
    file_name: str


@dataclass(frozen=True)
class ReadStatement:
    """READ file AT END / NOT AT END / INVALID KEY / NOT INVALID KEY."""
    file_name: str
    record_name: str
    key: str = ""  # READ with key for indexed/relative
    into_field: str = ""  # READ INTO field
    read_next: bool = False  # READ NEXT RECORD
    at_end_body: tuple[Statement, ...] = ()
    not_at_end_body: tuple[Statement, ...] = ()
    invalid_key_body: tuple[Statement, ...] = ()
    not_invalid_key_body: tuple[Statement, ...] = ()


@dataclass(frozen=True)
class StartStatement:
    """START file KEY IS [relational-operator] key."""
    file_name: str
    key: str = ""
    operator: str = ""  # "=", "<", "<=", ">", ">="
    invalid_key_body: tuple[Statement, ...] = ()
    not_invalid_key_body: tuple[Statement, ...] = ()


@dataclass(frozen=True)
class WriteStatement:
    """WRITE record FROM file."""
    record_name: str
    file_name: str
    from_field: str = ""  # WRITE FROM field
    invalid_key_body: tuple[Statement, ...] = ()
    not_invalid_key_body: tuple[Statement, ...] = ()


@dataclass(frozen=True)
class RewriteStatement:
    """REWRITE record."""
    record_name: str
    file_name: str = ""
    from_field: str = ""  # REWRITE FROM field
    invalid_key_body: tuple[Statement, ...] = ()
    not_invalid_key_body: tuple[Statement, ...] = ()


@dataclass(frozen=True)
class DeleteStatement:
    """DELETE file record."""
    file_name: str
    invalid_key_body: tuple[Statement, ...] = ()
    not_invalid_key_body: tuple[Statement, ...] = ()


@dataclass(frozen=True)
class MoveStatement:
    """MOVE source TO one or more targets."""
    source: str
    target: str
    source_expr: Expression | None = None
    target_ref: FieldReference | None = None
    targets: tuple[str, ...] = ()


@dataclass(frozen=True)
class AddStatement:
    """ADD source TO target.

    Supports both raw string mode (backward compatible) and structured mode.
    """
    source: str
    target: str
    source_expr: Expression | None = None  # structured source expression
    target_ref: FieldReference | None = None  # structured target reference
    giving_target: str | None = None  # ADD ... GIVING result


@dataclass(frozen=True)
class SubtractStatement:
    """SUBTRACT source FROM from_field [GIVING to_field]."""
    source: str
    from_field: str
    to_field: str | None = None
    source_expr: Expression | None = None
    from_ref: FieldReference | None = None
    to_ref: FieldReference | None = None
    sources: tuple[str, ...] = ()  # multi-source SUBTRACT A B C FROM D


@dataclass(frozen=True)
class MultiplyStatement:
    """MULTIPLY source BY multiplicand [GIVING target]."""
    source: str
    multiplicand: str
    target: str | None = None
    source_expr: Expression | None = None
    multiplicand_ref: FieldReference | None = None
    target_ref: FieldReference | None = None


@dataclass(frozen=True)
class CallStatement:
    """CALL a statically or dynamically named COBOL program."""
    program_name: str
    arguments: tuple[str, ...] = ()
    passing_modes: tuple[str, ...] = ()
    is_dynamic: bool = False


@dataclass(frozen=True)
class DivideStatement:
    """DIVIDE source BY divisor GIVING target [REMAINDER rem].

    Supports both raw string mode (backward compatible) and structured mode.
    """
    source: str
    divisor: str
    target: str
    remainder: str = ""  # REMAINDER target field
    source_expr: Expression | None = None
    divisor_expr: Expression | None = None
    target_ref: FieldReference | None = None


@dataclass(frozen=True)
class ComputeStatement:
    """COMPUTE target = expression.

    Supports both raw string mode (backward compatible) and structured mode.
    """
    target: str
    expression: str
    target_ref: FieldReference | None = None
    expression_expr: Expression | None = None


@dataclass(frozen=True)
class IfStatement:
    """IF condition THEN ... ELSE ... END-IF.

    Supports both raw string mode (backward compatible) and structured mode.
    """
    condition: str
    then_body: tuple[Statement, ...] = ()
    else_body: tuple[Statement, ...] = ()
    structured_condition: Condition | None = None  # structured condition tree


@dataclass(frozen=True)
class PerformStatement:
    """PERFORM paragraph/inline block with optional UNTIL, TIMES, VARYING or THRU."""
    paragraph_name: str
    until_condition: str | None = None
    structured_condition: Condition | None = None
    body: tuple[Statement, ...] = ()
    thru_target: str | None = None
    test_after: bool = False  # WITH TEST AFTER → do-while; default (BEFORE) → while


@dataclass(frozen=True)
class PerformTimesStatement:
    """PERFORM paragraph-name VARYING ... FROM ... BY ... UNTIL ... TIMES."""
    paragraph_name: str
    varying_var: str | None = None
    from_value: str | None = None
    by_value: str | None = None
    until_condition: str | None = None
    times: int | None = None


@dataclass(frozen=True)
class UnstringStatement:
    """UNSTRING source DELIMITED BY delimiter INTO targets.

    Supports both raw string mode (backward compatible) and structured mode.
    """
    source: str
    delimiter: str
    targets: tuple[str, ...] = ()
    source_ref: FieldReference | None = None
    target_refs: tuple[FieldReference, ...] = ()


@dataclass(frozen=True)
class StringStatement:
    """STRING parts INTO target.

    Supports both raw string mode (backward compatible) and structured mode.
    """
    parts: tuple[str, ...] = ()
    target: str = ""
    structured_parts: tuple[Expression, ...] = ()  # structured source expressions
    target_ref: FieldReference | None = None  # structured target reference


@dataclass(frozen=True)
class DisplayStatement:
    """DISPLAY parts UPON destination.

    Supports both raw string mode (backward compatible) and structured mode.
    """
    parts: tuple[str, ...] = ()
    destination: str = "STDOUT"
    structured_parts: tuple[Expression, ...] = ()  # structured expressions


@dataclass(frozen=True)
class GoToStatement:
    """GO TO paragraph-name."""
    target: str = ""


@dataclass(frozen=True)
class StopRunStatement:
    """STOP RUN."""


# Union type for all statements
Statement = (
    OpenStatement
    | CloseStatement
    | ReadStatement
    | StartStatement
    | WriteStatement
    | RewriteStatement
    | DeleteStatement
    | MoveStatement
    | AddStatement
    | SubtractStatement
    | MultiplyStatement
    | CallStatement
    | DivideStatement
    | IfStatement
    | PerformStatement
    | PerformTimesStatement
    | UnstringStatement
    | StringStatement
    | DisplayStatement
    | GoToStatement
    | StopRunStatement
)


# ---------------------------------------------------------------------------
# Paragraphs and program
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Paragraph:
    """A COBOL paragraph (named block of statements)."""
    name: str
    statements: tuple[Statement, ...] = ()


@dataclass(frozen=True)
class ThresholdRule:
    """A numeric threshold condition extracted from COBOL IF statements.

    Represents a condition like ``IF amount < 500`` parsed from COBOL.
    """
    field_name: str
    operator: str  # "<" or ">" or "<=" or ">="
    value: int


@dataclass(frozen=True)
class StatusCodeMapping:
    """A status code value and its corresponding label.

    Extracted from COBOL IF conditions like ``IF FIELD = 'X'``
    followed by ``MOVE 'LABEL' TO TARGET``.

    Maps a raw status character to its semantic meaning.
    """
    code: str  # e.g. "R", "P", "A"
    label: str  # e.g. "REJECTED", "PENDING"
    field_name: str  # the COBOL field being tested


@dataclass(frozen=True)
class OutputFieldDefinition:
    """A field definition in an output record.

    Represents one field in a STRING/record output format.
    """
    field_name: str
    delimiter: str  # "|" or " " or SIZE
    width: int | None = None  # pad width, None = no padding


@dataclass(frozen=True)
class RecordFormat:
    """A record format extracted from COBOL STRING statements.

    Represents the field ordering, delimiters, and widths for a
    WRITE/STRING output record.
    """
    record_name: str  # e.g. "REPORT-REC", "SETTLE-REC"
    fields: tuple[OutputFieldDefinition, ...] = ()
    separator: str = " "  # default separator between fields


@dataclass(frozen=True)
class OutputFormat:
    """A generic output record format.

    Represents a single output record with its format and optional header.
    Replaces the domain-shaped report_format/settle_format fields.
    """
    record_format: RecordFormat
    header: str = ""  # optional header line written before records


@dataclass(frozen=True)
class LookupOperation:
    """A generic table/file lookup extracted from COBOL PERFORM/IF patterns.

    Represents a linear search through a table or file:
        PERFORM paragraph UNTIL condition
    where the paragraph does:
        IF table-field(idx) = search-field
            MOVE value TO result-field
        ADD 1 TO idx
    """
    table_field: str  # the field being searched (e.g. table key)
    search_field: str  # the field being matched against
    amount_field: str  # the field retrieved on match
    match_found_field: str  # field set to indicate match
    match_amount_field: str  # field holding the matched value
    index_field: str  # loop index variable
    count_field: str  # table count variable
    match_char: str = "Y"  # character written to match-found field



@dataclass(frozen=True)
class InputRecordMapping:
    """Maps a delimited input record to ordered fields.

    Represents UNSTRING source DELIMITED BY delimiter INTO field1 field2 ...
    The parser extracts field ordering and delimiter from COBOL source.
    The generator derives Java parsing code from this IR.
    """
    record_name: str  # e.g. "CLAIM-REC", "PAYMENT-REC"
    file_name: str  # e.g. "CLAIMS-FILE"
    delimiter: str  # e.g. "|"
    fields: tuple[str, ...] = ()  # ordered target field names


@dataclass(frozen=True)
class ProgramCapabilities:
    """Semantic capabilities derived from the COBOL program IR.

    Each field represents whether the program uses a particular COBOL
    construct. Capabilities are derived from IR elements (statements,
    file definitions, data items) — NOT from program names, filenames,
    or workload-specific terminology.
    """
    assignment: bool = False          # MOVE statements
    arithmetic: bool = False          # ADD, SUBTRACT, MULTIPLY, DIVIDE, COMPUTE
    condition: bool = False           # IF/ELSE statements
    file_input: bool = False          # READ statements or input file definitions
    file_output: bool = False         # WRITE statements or output file definitions
    unstring: bool = False            # UNSTRING parsing
    string_build: bool = False          # STRING record building
    lookup: bool = False              # PERFORM + table search (LookupOperation)
    display: bool = False             # DISPLAY output
    goto: bool = False                # GO TO statements
    perform: bool = False             # PERFORM statements
    decision: bool = False            # IF+MOVE conditional assignment patterns
    record_output: bool = False       # RecordFormat for output records
    summary_output: bool = False      # Summary counters/fields for DISPLAY
    input_record_mapping: bool = False  # InputRecordMapping for delimited records


def derive_capabilities(program: CobolProgram) -> ProgramCapabilities:
    """Derive ProgramCapabilities from the parsed COBOL program IR.

    Inspects IR elements to determine which COBOL constructs are present.
    No workload-specific detection — purely semantic analysis of IR nodes.

    Capability derivation is based exclusively on generic IR elements:
    - Statement types (MoveStatement, IfStatement, AddStatement, etc.)
    - Compound statement patterns (IfStatement with MOVE in body)
    - File definitions (input/output paths)
    - InputRecordMapping (UNSTRING patterns)
    - IfStatement with array indexing (table search)
    - StringStatement + WriteStatement intersection (record output)
    - DisplayStatement with label=value pattern (summary output)

    No capability depends on Claims terminology, domain-specific field names,
    or any domain-shaped container. All detection uses generic IR elements.
    """

    # Scan all statements recursively (all paragraphs)
    all_stmts: list[Statement] = []
    for para in program.paragraphs:
        for stmt in para.statements:
            all_stmts.extend(_flatten_statements(stmt))

    has_move = any(isinstance(s, MoveStatement) for s in all_stmts)
    has_arithmetic = any(isinstance(s, (AddStatement, DivideStatement)) for s in all_stmts)
    has_condition = any(isinstance(s, IfStatement) for s in all_stmts)
    has_display = any(isinstance(s, DisplayStatement) for s in all_stmts)
    has_goto = any(isinstance(s, GoToStatement) for s in all_stmts)
    has_perform = any(isinstance(s, PerformStatement) for s in all_stmts)
    has_read = any(isinstance(s, ReadStatement) for s in all_stmts)
    has_string = any(isinstance(s, StringStatement) for s in all_stmts)

    # File roles from OPEN statements — not from path names
    input_files = set()
    output_files = set()
    for stmt in program.open_statements:
        if stmt.mode.upper() == "INPUT":
            input_files.add(stmt.file_name)
        elif stmt.mode.upper() == "OUTPUT":
            output_files.add(stmt.file_name)

    # InputRecordMapping
    has_input_record = bool(program.input_record_mappings)

    # --- Decision: any IfStatement with MoveStatement in then_body ---
    decision = False
    if has_condition and has_move:
        for s in all_stmts:
            if isinstance(s, IfStatement):
                if any(isinstance(x, MoveStatement) for x in s.then_body):
                    decision = True
                    break

    # --- Lookup: table search pattern (IF with array indexing) ---
    # Generic COBOL table search: IF field(idx) = search-value
    # The ") =" pattern distinguishes array indexing from grouping parentheses.
    # Grouping: (A = B) — = is INSIDE parens
    # Array indexing: field(idx) = value — = is OUTSIDE closing paren
    has_lookup = any(
        isinstance(s, IfStatement) and ') =' in s.condition
        for s in all_stmts
    )

    # --- Record output: STRING builds a record that is subsequently written ---
    # Generic evidence: StringStatement.target matches WriteStatement.record_name
    # STRING INTO a variable that is never written = just string building
    # STRING INTO a record that IS written = record output
    string_targets: set[str] = set()
    write_records: set[str] = set()
    for s in all_stmts:
        if isinstance(s, StringStatement):
            string_targets.add(s.target)
        if isinstance(s, WriteStatement):
            write_records.add(s.record_name)
    has_record_output = bool(string_targets & write_records)

    # --- Summary output: DISPLAY with "LABEL=" VARIABLE pattern ---
    # Generic evidence: first part is a quoted string ending with "=",
    # second part is a variable (not quoted).
    # This captures: DISPLAY "TOTAL=" WS-COUNT
    # This excludes:  DISPLAY "ERROR" (no variable), DISPLAY "REJECT:" ID (no =)
    has_summary = False
    for s in all_stmts:
        if isinstance(s, DisplayStatement) and len(s.parts) >= 2:
            first = s.parts[0].strip('"')
            second = s.parts[1]
            if first.endswith('=') and not second.startswith('"'):
                has_summary = True
                break

    return ProgramCapabilities(
        assignment=has_move,
        arithmetic=has_arithmetic,
        condition=has_condition,
        file_input=has_read or bool(input_files),
        file_output=bool(write_records) or bool(output_files),
        unstring=has_input_record,
        string_build=has_string,
        lookup=has_lookup,
        display=has_display,
        goto=has_goto,
        perform=has_perform,
        decision=decision,
        record_output=has_record_output,
        summary_output=has_summary,
        input_record_mapping=has_input_record,
    )


def _flatten_statements(stmt: Statement) -> list[Statement]:
    """Recursively flatten compound statements into a list."""
    result = [stmt]
    if isinstance(stmt, IfStatement):
        for s in stmt.then_body:
            result.extend(_flatten_statements(s))
        for s in stmt.else_body:
            result.extend(_flatten_statements(s))
    if isinstance(stmt, ReadStatement):
        for s in stmt.not_at_end_body:
            result.extend(_flatten_statements(s))
        for s in stmt.at_end_body:
            result.extend(_flatten_statements(s))
    if isinstance(stmt, PerformStatement):
        # PERFORM body statements are in paragraphs, not in the statement itself
        pass
    return result


@dataclass(frozen=True)
class CobolProgram:
    """Complete parsed COBOL program IR.

    This is the output of the parser and the input to the Java generator.
    All fields are generic semantic IR — no domain-shaped containers.
    """
    program_id: str
    file_definitions: tuple[FileDefinition, ...] = ()
    working_storage: tuple[DataItem, ...] = ()
    paragraphs: tuple[Paragraph, ...] = ()
    threshold_rules: tuple[ThresholdRule, ...] = ()
    input_record_mappings: tuple[InputRecordMapping, ...] = ()
    open_statements: tuple[OpenStatement, ...] = ()  # OPEN INPUT/OUTPUT/I-O/EXTEND
    # Generic semantic fields (replaces settlement_logic / DecisionLogic)
    status_codes: tuple[StatusCodeMapping, ...] = ()
    output_formats: tuple[OutputFormat, ...] = ()
    lookup_operations: tuple[LookupOperation, ...] = ()
    match_outcome_labels: tuple[str, ...] = ()
    summary_fields: tuple[str, ...] = ()
    report_header: str = ""
    # Dependency information
    called_programs: tuple[str, ...] = ()
    copybooks: tuple[str, ...] = ()  # COPY references
    entry_points: tuple[str, ...] = ()  # ENTRY statements
    linkage_section: tuple[DataItem, ...] = ()
    using_parameters: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Application-level IR
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProgramCall:
    """A COBOL CALL statement dependency.

    Represents a call from one program to another.
    """
    caller: str  # PROGRAM-ID of calling program
    target: str  # target program name (may be literal or variable)
    arguments: tuple[str, ...] = ()  # USING arguments
    call_type: str = "STATIC"  # STATIC, DYNAMIC, FUNCTION-POINTER
    resolution: str = "UNRESOLVED"  # UNRESOLVED, RESOLVED, EXTERNAL


@dataclass(frozen=True)
class CopybookReference:
    """A COPY statement dependency.

    Represents a copybook inclusion.
    """
    source_program: str  # PROGRAM-ID of program containing COPY
    copybook_name: str  # name of the copybook
    location: str = ""  # line/column if available


@dataclass(frozen=True)
class FileDependency:
    """A file access dependency.

    Represents READ or WRITE access to a file.
    """
    program_id: str  # PROGRAM-ID of accessing program
    file_name: str  # COBOL file name
    operation: str  # READ, WRITE, OPEN, CLOSE
    mode: str = ""  # INPUT, OUTPUT, I-O, EXTEND


@dataclass(frozen=True)
class DependencyEdge:
    """A single dependency edge in the application graph.

    Represents a relationship between two program units.
    """
    source: str  # source program ID
    target: str  # target program ID or resource
    edge_type: str  # CALL, COPY, FILE_READ, FILE_WRITE, ENTRY
    metadata: str = ""  # additional information


@dataclass(frozen=True)
class CobolProgramUnit:
    """A single program unit within an application.

    Contains the parsed program and its dependency information.
    """
    program_id: str
    source_path: str  # filesystem path to the source file
    program: CobolProgram
    calls: tuple[ProgramCall, ...] = ()
    copybooks: tuple[CopybookReference, ...] = ()
    entry_points: tuple[str, ...] = ()
    file_dependencies: tuple[FileDependency, ...] = ()


@dataclass(frozen=True)
class CobolApplication:
    """A multi-program COBOL application.

    Represents a collection of related COBOL programs with their
    dependency relationships.
    """
    application_id: str  # derived from directory or explicit
    programs: tuple[CobolProgramUnit, ...] = ()
    copybooks: tuple[str, ...] = ()  # discovered copybook names
    edges: tuple[DependencyEdge, ...] = ()  # dependency graph edges

    def get_program(self, program_id: str) -> CobolProgramUnit | None:
        """Find a program by its PROGRAM-ID."""
        for p in self.programs:
            if p.program_id == program_id:
                return p
        return None

    def get_callers(self, target: str) -> list[str]:
        """Find all programs that call the target."""
        return [e.source for e in self.edges if e.target == target and e.edge_type == "CALL"]

    def get_callees(self, source: str) -> list[str]:
        """Find all programs called by the source."""
        return [e.target for e in self.edges if e.source == source and e.edge_type == "CALL"]

    def get_dependencies(self, program_id: str) -> list[DependencyEdge]:
        """Get all dependencies for a program."""
        return [e for e in self.edges if e.source == program_id]

    def detect_cycles(self) -> list[list[str]]:
        """Detect cycles in the CALL dependency graph.

        Returns list of cycles found. Each cycle is a list of program IDs.
        Empty list means no cycles.
        """
        cycles: list[list[str]] = []
        visited: set[str] = set()
        rec_stack: list[str] = []

        def dfs(node: str) -> None:
            visited.add(node)
            rec_stack.append(node)

            for edge in self.edges:
                if edge.source == node and edge.edge_type == "CALL":
                    if edge.target not in visited:
                        dfs(edge.target)
                    elif edge.target in rec_stack:
                        # Found a cycle
                        cycle_start = rec_stack.index(edge.target)
                        cycle = rec_stack[cycle_start:] + [edge.target]
                        cycles.append(cycle)

            rec_stack.pop()

        for program in self.programs:
            if program.program_id not in visited:
                dfs(program.program_id)

        return cycles

    def validate(self) -> list[str]:
        """Validate the application model.

        Returns list of validation errors. Empty list means valid.
        """
        errors: list[str] = []

        # Check for duplicate program IDs
        seen_ids: set[str] = set()
        for p in self.programs:
            if p.program_id in seen_ids:
                errors.append(f"Duplicate PROGRAM-ID: {p.program_id}")
            seen_ids.add(p.program_id)

        # Check for unresolved CALL targets
        for edge in self.edges:
            if edge.edge_type == "CALL" and edge.target not in seen_ids:
                errors.append(f"Unresolved CALL target: {edge.target} (called by {edge.source})")

        # Check for missing COPY targets
        for p in self.programs:
            for cb in p.copybooks:
                if cb.copybook_name not in self.copybooks:
                    errors.append(f"Missing COPY target: {cb.copybook_name} (in {p.program_id})")

        # Check dependency graph consistency
        for edge in self.edges:
            if edge.source not in seen_ids:
                errors.append(f"Dependency source not in application: {edge.source}")
            if edge.target not in seen_ids and edge.edge_type == "CALL":
                pass  # Already reported as unresolved

        # Detect cycles (informational, not necessarily errors)
        cycles = self.detect_cycles()
        for cycle in cycles:
            errors.append(f"Cyclic dependency detected: {' -> '.join(cycle)}")

        return errors


# ---------------------------------------------------------------------------
# JCL IR
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class JclJob:
    """A JCL JOB statement.

    Represents a job unit with its name, parameters, and execution steps.
    Job identity comes from JCL syntax (//JOBNAME JOB ...).
    Filename is metadata only.
    """
    name: str  # JOB name from //JOBNAME JOB
    parameters: dict[str, str] | None = None  # JOB parameters (CLASS, MSGLEVEL, etc.)
    steps: tuple[JclStep, ...] = ()
    comments: tuple[str, ...] = ()
    source_path: str = ""  # filesystem path to the JCL source


@dataclass(frozen=True)
class JclStep:
    """A JCL EXEC step.

    Represents a single execution step within a job.
    Step identity comes from JCL syntax (//STEPNAME EXEC ...).
    """
    name: str  # STEP name from //STEPNAME EXEC
    exec_: JclExec | None = None
    dd_statements: tuple[JclDD, ...] = ()
    condition: JclCondition | None = None
    comments: tuple[str, ...] = ()


@dataclass(frozen=True)
class JclExec:
    """A JCL EXEC statement.

    Represents program execution or procedure invocation.
    Distinguishes PGM (program) from PROC (procedure).
    """
    program: str = ""  # PGM= value
    procedure: str = ""  # PROC= value
    parameters: dict[str, str] | None = None  # PARM, REGION, TIME, etc.


@dataclass(frozen=True)
class JclDD:
    """A JCL DD statement.

    Represents a data definition for a step.
    DD name, dataset reference, and disposition are generic.
    """
    name: str  # DD name (e.g., "INPUT", "OUTPUT")
    dataset: str = ""  # DSN= value
    disposition: str = ""  # DISP= value
    space: str = ""  # SPACE= value
    unit: str = ""  # UNIT= value
    dcb: str = ""  # DCB= value
    vol: str = ""  # VOL= value
    sysout: str = ""  # SYSOUT= value
    sysin: bool = False  # SYSIN DD * indicator
    is_temporary: bool = False  # temporary dataset (SYSOUT=* or DSN=&&...)
    is_inline: bool = False  # inline data (DD * or DD DATA)


@dataclass(frozen=True)
class JclDataset:
    """A JCL dataset reference.

    Represents a dataset with its name and type.
    """
    name: str  # dataset name
    type: str = ""  # PS, PO, VSAM, etc. (if known)
    disposition: str = ""  # NEW, OLD, SHR, MOD


@dataclass(frozen=True)
class JclCondition:
    """A JCL step condition (COND or IF/THEN/ELSE/ENDIF).

    Represents conditional execution for a step.
    """
    condition_type: str = "COND"  # "COND" or "IF"
    code: str = ""  # COND code (e.g., "EVEN", "ONLY", "RC<4")
    if_expression: str = ""  # IF expression if condition_type is "IF"
    then_steps: tuple[str, ...] = ()  # steps in THEN branch
    else_steps: tuple[str, ...] = ()  # steps in ELSE branch


@dataclass(frozen=True)
class JclProcedure:
    """A JCL cataloged procedure.

    Represents a reusable procedure definition.
    """
    name: str
    steps: tuple[JclStep, ...] = ()
    parameters: dict[str, str] | None = None


@dataclass(frozen=True)
class JclSymbol:
    """A JCL symbolic parameter.

    Represents a symbolic substitution parameter (e.g., &VALUE).
    """
    name: str
    value: str = ""  # resolved value (empty if unresolved)
    is_resolved: bool = False


@dataclass(frozen=True)
class JclDependency:
    """A dependency between JCL steps or between JCL and COBOL.

    Represents a relationship such as:
    - Step execution order
    - Step to program reference
    - DD to dataset reference
    - Dataset to COBOL file reference
    """
    source: str
    target: str
    dependency_type: str  # JCL_EXEC, JCL_DD, JCL_STEP_ORDER, COBOL_PROGRAM, COBOL_FILE
    metadata: str = ""


@dataclass(frozen=True)
class JclApplication:
    """A complete JCL application model.

    Represents one or more JCL jobs with their step dependencies,
    dataset relationships, and links to COBOL programs.
    """
    jobs: tuple[JclJob, ...] = ()
    procedures: tuple[JclProcedure, ...] = ()
    symbols: tuple[JclSymbol, ...] = ()
    dependencies: tuple[JclDependency, ...] = ()
    source_path: str = ""  # root directory of JCL sources

    def get_job(self, job_name: str) -> JclJob | None:
        """Find a job by name."""
        for job in self.jobs:
            if job.name == job_name:
                return job
        return None

    def get_step(self, job_name: str, step_name: str) -> JclStep | None:
        """Find a step by job and step name."""
        job = self.get_job(job_name)
        if job is None:
            return None
        for step in job.steps:
            if step.name == step_name:
                return step
        return None

    def get_dependencies(self, source: str) -> list[JclDependency]:
        """Get all dependencies from a source."""
        return [d for d in self.dependencies if d.source == source]

    def get_step_order(self, job_name: str) -> list[str]:
        """Get ordered step names for a job."""
        job = self.get_job(job_name)
        if job is None:
            return []
        return [s.name for s in job.steps]

    def get_program_references(self) -> list[tuple[str, str]]:
        """Get all (step, program) references."""
        refs: list[tuple[str, str]] = []
        for job in self.jobs:
            for step in job.steps:
                if step.exec_ and step.exec_.program:
                    refs.append((step.name, step.exec_.program))
        return refs

    def get_dataset_references(self) -> list[tuple[str, str]]:
        """Get all (dd_name, dataset_name) references."""
        refs: list[tuple[str, str]] = []
        for job in self.jobs:
            for step in job.steps:
                for dd in step.dd_statements:
                    if dd.dataset:
                        refs.append((dd.name, dd.dataset))
        return refs

    def validate(self) -> list[str]:
        """Validate the JCL application model.

        Returns list of validation errors. Empty list means valid.
        """
        errors: list[str] = []

        # Check for duplicate step names within each job
        for job in self.jobs:
            seen_steps: set[str] = set()
            for step in job.steps:
                if step.name in seen_steps:
                    errors.append(f"Duplicate step name: {step.name} in job {job.name}")
                seen_steps.add(step.name)

        # Check for malformed JOB
        for job in self.jobs:
            if not job.name:
                errors.append("Malformed JOB: missing name")

        # Check for malformed EXEC
        for job in self.jobs:
            for step in job.steps:
                if step.exec_ is None:
                    errors.append(f"Malformed EXEC: step {step.name} has no EXEC statement")
                elif not step.exec_.program and not step.exec_.procedure:
                    errors.append(f"Malformed EXEC: step {step.name} has no PGM or PROC")

        # Check for unresolved PGM references
        known_programs = set()  # Would need COBOL application to resolve
        for job in self.jobs:
            for step in job.steps:
                if step.exec_ and step.exec_.program:
                    if step.exec_.program not in known_programs:
                        pass  # Will be resolved when linked with COBOL

        # Check for invalid dependency references
        all_step_names: set[str] = set()
        for job in self.jobs:
            for step in job.steps:
                all_step_names.add(step.name)

        for dep in self.dependencies:
            if dep.dependency_type == "JCL_STEP_ORDER":
                if dep.source not in all_step_names:
                    errors.append(f"Invalid step dependency source: {dep.source}")
                if dep.target not in all_step_names:
                    errors.append(f"Invalid step dependency target: {dep.target}")

        return errors


# ---------------------------------------------------------------------------
# SQL IR (DB2 / Embedded SQL)
# ---------------------------------------------------------------------------

class SqlStatementType(Enum):
    """SQL statement type."""
    SELECT = "SELECT"
    INSERT = "INSERT"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    DECLARE_CURSOR = "DECLARE_CURSOR"
    OPEN_CURSOR = "OPEN_CURSOR"
    FETCH_CURSOR = "FETCH_CURSOR"
    CLOSE_CURSOR = "CLOSE_CURSOR"
    COMMIT = "COMMIT"
    ROLLBACK = "ROLLBACK"
    EXECUTE = "EXECUTE"
    PREPARE = "PREPARE"
    CALL = "CALL"


class SqlJoinType(Enum):
    """SQL join type."""
    INNER = "INNER"
    LEFT = "LEFT"
    RIGHT = "RIGHT"
    FULL = "FULL"
    CROSS = "CROSS"


class SqlOperator(Enum):
    """SQL comparison operator."""
    EQUALS = "="
    NOT_EQUALS = "<>"
    GREATER = ">"
    LESS = "<"
    GREATER_EQUALS = ">="
    LESS_EQUALS = "<="
    LIKE = "LIKE"
    IN = "IN"
    BETWEEN = "BETWEEN"
    IS_NULL = "IS NULL"
    IS_NOT_NULL = "IS NOT NULL"


class SqlAggregateFunction(Enum):
    """SQL aggregate function."""
    COUNT = "COUNT"
    SUM = "SUM"
    AVG = "AVG"
    MIN = "MIN"
    MAX = "MAX"


@dataclass(frozen=True)
class SqlTableReference:
    """A SQL table reference.

    Represents a table name, optionally with schema.
    """
    table_name: str
    schema: str = ""
    alias: str = ""


@dataclass(frozen=True)
class SqlColumnReference:
    """A SQL column reference.

    Represents a column name, optionally with table qualifier.
    """
    column_name: str
    table_name: str = ""
    alias: str = ""


@dataclass(frozen=True)
class SqlHostVariable:
    """A SQL host variable.

    Represents :WS-FIELD or :WS-FIELD:IND-FIELD.
    Distinguishes COBOL field from DB column.
    """
    name: str  # the COBOL field name (without :)
    indicator: str = ""  # indicator variable name (without :)
    has_indicator: bool = False


@dataclass(frozen=True)
class SqlParameter:
    """A SQL parameter marker or host variable.

    Used in WHERE clauses, VALUES, SET, etc.
    """
    name: str  # host variable name or parameter marker
    is_parameter_marker: bool = False  # True for ? markers
    indicator: str = ""


@dataclass(frozen=True)
class SqlExpression:
    """A SQL expression.

    Represents column references, literals, host variables, and operations.
    """
    column: SqlColumnReference | None = None
    literal: str = ""  # literal value
    host_variable: SqlHostVariable | None = None
    function: SqlAggregateFunction | None = None
    operand_left: SqlExpression | None = None
    operator: str = ""
    operand_right: SqlExpression | None = None


@dataclass(frozen=True)
class SqlPredicate:
    """A SQL predicate (WHERE condition).

    Represents comparison, NULL check, LIKE, IN, BETWEEN, etc.
    """
    left: SqlExpression
    operator: SqlOperator = SqlOperator.EQUALS
    right: SqlExpression | None = None
    right_list: tuple[SqlExpression, ...] = ()  # for IN clause
    left_operand: SqlExpression | None = None  # for BETWEEN
    right_operand: SqlExpression | None = None  # for BETWEEN
    negated: bool = False


@dataclass(frozen=True)
class SqlJoin:
    """A SQL JOIN clause.

    Represents table join with condition.
    """
    join_type: SqlJoinType = SqlJoinType.INNER
    table: SqlTableReference | None = None
    on_condition: SqlPredicate | None = None


@dataclass(frozen=True)
class SqlOrderBy:
    """A SQL ORDER BY element.

    Represents column ordering.
    """
    column: SqlColumnReference | None = None
    ascending: bool = True
    nulls_first: bool = False


@dataclass(frozen=True)
class SqlGroupBy:
    """A SQL GROUP BY element.

    Represents column grouping.
    """
    column: SqlColumnReference | None = None


@dataclass(frozen=True)
class SqlSelect:
    """A SQL SELECT statement.

    Represents full SELECT with columns, tables, predicates, etc.
    """
    columns: tuple[SqlColumnReference, ...] = ()
    into_variables: tuple[SqlHostVariable, ...] = ()  # SELECT INTO
    from_tables: tuple[SqlTableReference, ...] = ()
    joins: tuple[SqlJoin, ...] = ()
    where_predicate: SqlPredicate | None = None
    group_by: tuple[SqlGroupBy, ...] = ()
    having: SqlPredicate | None = None
    order_by: tuple[SqlOrderBy, ...] = ()
    distinct: bool = False
    fetch_first: int | None = None  # FETCH FIRST n ROWS ONLY


@dataclass(frozen=True)
class SqlInsert:
    """A SQL INSERT statement.

    Represents INSERT INTO table (columns) VALUES (values).
    """
    table: SqlTableReference | None = None
    columns: tuple[SqlColumnReference, ...] = ()
    values: tuple[SqlExpression, ...] = ()


@dataclass(frozen=True)
class SqlUpdate:
    """A SQL UPDATE statement.

    Represents UPDATE table SET col = val WHERE predicate.
    """
    table: SqlTableReference | None = None
    assignments: tuple[tuple[SqlColumnReference, SqlExpression], ...] = ()
    where_predicate: SqlPredicate | None = None


@dataclass(frozen=True)
class SqlDelete:
    """A SQL DELETE statement.

    Represents DELETE FROM table WHERE predicate.
    """
    table: SqlTableReference | None = None
    where_predicate: SqlPredicate | None = None


@dataclass(frozen=True)
class SqlCursor:
    """A SQL cursor declaration.

    Represents DECLARE cursor_name CURSOR FOR select.
    """
    name: str
    query: SqlSelect | None = None
    is_hold: bool = False  # WITH HOLD


@dataclass(frozen=True)
class SqlTransactionOperation:
    """A SQL transaction operation (COMMIT/ROLLBACK)."""
    operation: str  # "COMMIT" or "ROLLBACK"


@dataclass(frozen=True)
class SqlStatement:
    """A generic SQL statement wrapper.

    Wraps specific SQL statement types with metadata.
    """
    statement_type: SqlStatementType
    raw_sql: str = ""  # original SQL text
    select: SqlSelect | None = None
    insert: SqlInsert | None = None
    update: SqlUpdate | None = None
    delete: SqlDelete | None = None
    cursor: SqlCursor | None = None
    transaction: SqlTransactionOperation | None = None
    cursor_name: str = ""  # for OPEN/FETCH/CLOSE cursor
    procedure_name: str = ""  # for CALL
    prepare_statement: str = ""  # for PREPARE
    execute_immediate: bool = False  # for EXECUTE IMMEDIATE


@dataclass(frozen=True)
class EmbeddedSqlBlock:
    """An embedded SQL block within COBOL.

    Represents EXEC SQL ... END-EXEC region.
    """
    statements: tuple[SqlStatement, ...] = ()
    raw_text: str = ""  # original embedded SQL text


@dataclass(frozen=True)
class Db2TableDependency:
    """A DB2 table dependency.

    Represents program access to a DB2 table.
    """
    program_id: str
    table_name: str
    schema: str = ""
    operation: str = ""  # READ, INSERT, UPDATE, DELETE
    columns: tuple[str, ...] = ()  # accessed columns


@dataclass(frozen=True)
class Db2Application:
    """A DB2 application model.

    Represents COBOL programs with embedded SQL dependencies.
    """
    program_id: str
    sql_blocks: tuple[EmbeddedSqlBlock, ...] = ()
    cursors: tuple[SqlCursor, ...] = ()
    table_dependencies: tuple[Db2TableDependency, ...] = ()
    host_variables: tuple[SqlHostVariable, ...] = ()

    def get_tables(self) -> list[str]:
        """Get all referenced tables."""
        tables: list[str] = []
        for dep in self.table_dependencies:
            if dep.table_name not in tables:
                tables.append(dep.table_name)
        return tables

    def get_table_columns(self, table_name: str) -> list[str]:
        """Get all accessed columns for a table."""
        columns: list[str] = []
        for dep in self.table_dependencies:
            if dep.table_name == table_name:
                for col in dep.columns:
                    if col not in columns:
                        columns.append(col)
        return columns

    def get_dependencies(self, table_name: str) -> list[Db2TableDependency]:
        """Get all dependencies for a table."""
        return [d for d in self.table_dependencies if d.table_name == table_name]

    def validate(self) -> list[str]:
        """Validate the DB2 application model.

        Returns list of validation errors.
        """
        errors: list[str] = []

        # Check for duplicate cursor names
        seen_cursors: set[str] = set()
        for cursor in self.cursors:
            if cursor.name in seen_cursors:
                errors.append(f"Duplicate cursor name: {cursor.name}")
            seen_cursors.add(cursor.name)

        # Check for unresolved cursor references
        for sql_stmt in self._all_statements():
            if sql_stmt.statement_type in (
                SqlStatementType.OPEN_CURSOR,
                SqlStatementType.FETCH_CURSOR,
                SqlStatementType.CLOSE_CURSOR,
            ):
                if sql_stmt.cursor_name and sql_stmt.cursor_name not in seen_cursors:
                    errors.append(f"Unresolved cursor reference: {sql_stmt.cursor_name}")

        return errors

    def _all_statements(self) -> list[SqlStatement]:
        """Get all SQL statements from all blocks."""
        stmts: list[SqlStatement] = []
        for block in self.sql_blocks:
            stmts.extend(block.statements)
        return stmts


# ---------------------------------------------------------------------------
# CICS IR (Transaction / Terminal / Resource)
# ---------------------------------------------------------------------------

class CicsCommandType(Enum):
    """CICS command type."""
    SEND = "SEND"
    RECEIVE = "RECEIVE"
    READ = "READ"
    WRITE = "WRITE"
    REWRITE = "REWRITE"
    DELETE = "DELETE"
    STARTBR = "STARTBR"
    READNEXT = "READNEXT"
    READPREV = "READPREV"
    ENDBR = "ENDBR"
    LINK = "LINK"
    XCTL = "XCTL"
    RETURN = "RETURN"
    SYNCPOINT = "SYNCPOINT"
    ABEND = "ABEND"
    HANDLE_CONDITION = "HANDLE_CONDITION"
    HANDLE_AID = "HANDLE_AID"
    ASSIGN = "ASSIGN"
    ALLOCATE = "ALLOCATE"
    FREE = "FREE"
    HOLD = "HOLD"
    RELEASE = "RELEASE"
    WRITEQ = "WRITEQ"
    READQ = "READQ"
    DELETEQ = "DELETEQ"
    SET = "SET"
    IGNORE = "IGNORE"
    POP = "POP"
    PUSH = "PUSH"


class CicsResourceType(Enum):
    """CICS resource type."""
    FILE = "FILE"
    QUEUE = "QUEUE"
    PROGRAM = "PROGRAM"
    TRANSID = "TRANSID"
    MAP = "MAP"
    MAPSET = "MAPSET"
    TD_QUEUE = "TD_QUEUE"
    TS_QUEUE = "TS_QUEUE"
    JOURNAL = "JOURNAL"
    DB2TABLE = "DB2TABLE"


class CicsConditionType(Enum):
    """CICS condition type for HANDLE CONDITION."""
    NORMAL = "NORMAL"
    ERROR = "ERROR"
    NOTFND = "NOTFND"
    DUPKEY = "DUPKEY"
    INVREQ = "INVREQ"
    IOERR = "IOERR"
    NOSPACE = "NOSPACE"
    NOTOPEN = "NOTOPEN"
    ENDDATA = "ENDDATA"
    ITEMERR = "ITEMERR"
    LENGERR = "LENGERR"
    QIDERR = "QIDERR"
    MAPFAIL = "MAPFAIL"
    ISSUEERR = "ISSUEERR"
    OVERFLOW = "OVERFLOW"
    INBFMH = "INBFMH"
    TERMERR = "TERMERR"
    RLINEMGR = "RLINEMGR"
    UCERR = "UCERR"
    TRANSIDERR = "TRANSIDERR"
    ENDAID = "ENDAID"
    KEYERR = "KEYERR"
    NOSTART = "NOSTART"
    NONVAL = "NONVAL"


class CicsAidType(Enum):
    """CICS AID type for HANDLE AID."""
    CLEAR = "CLEAR"
    PA1 = "PA1"
    PA2 = "PA2"
    PA3 = "PA3"
    PF1 = "PF1"
    PF2 = "PF2"
    PF3 = "PF3"
    PF4 = "PF4"
    PF5 = "PF5"
    PF6 = "PF6"
    PF7 = "PF7"
    PF8 = "PF8"
    PF9 = "PF9"
    PF10 = "PF10"
    PF11 = "PF11"
    PF12 = "PF12"
    PF13 = "PF13"
    PF14 = "PF14"
    PF15 = "PF15"
    PF16 = "PF16"
    PF17 = "PF17"
    PF18 = "PF18"
    PF19 = "PF19"
    PF20 = "PF20"
    PF21 = "PF21"
    PF22 = "PF22"
    PF23 = "PF23"
    PF24 = "PF24"
    ENTER = "ENTER"
    TAB = "TAB"
    BOTHRONE = "BOTHRONE"
    TRIGGER = "TRIGGER"


class CicsRespHandling(Enum):
    """CICS RESP/RESP2 handling mode."""
    NO_HANDLE = "NO_HANDLE"
    HANDLE_CONDITION = "HANDLE_CONDITION"
    RESP_VARIABLE = "RESP_VARIABLE"
    RESP2_VARIABLE = "RESP2_VARIABLE"


@dataclass(frozen=True)
class CicsOperand:
    """A single CICS command operand.

    Represents KEY=VALUE or bare keyword within a CICS command.
    """
    keyword: str  # e.g. "DATASET", "LENGTH", "SET", "RESP"
    value: str  # e.g. "MYFILE", ":WS-LENGTH", ":WS-RESP"
    is_host_variable: bool = False  # True if value starts with :
    is_literal: bool = False  # True if value is quoted literal


@dataclass(frozen=True)
class CicsCommand:
    """A single CICS command.

    Represents one EXEC CICS ... END-EXEC block.
    Normalized command name, structured operands, extracted references.
    """
    command_type: CicsCommandType
    raw_text: str  # original CICS command text
    operands: tuple[CicsOperand, ...] = ()
    # Extracted references (populated by parser)
    resource_name: str = ""  # DATASET, QUEUE, PROGRAM, TRANSID value
    resource_type: CicsResourceType | None = None
    commarea_length: str = ""  # LENGTH for COMMAREA
    commarea_data: str = ""  # DATAAREA for COMMAREA
    channel_name: str = ""  # CHANNEL operand
    container_names: tuple[str, ...] = ()  # CONTAINER operands
    program_name: str = ""  # PROGRAM operand (LINK/XCTL)
    transaction_id: str = ""  # TRANSID operand
    into_field: str = ""  # INTO operand
    from_field: str = ""  # FROM operand
    set_field: str = ""  # SET operand
    length_field: str = ""  # LENGTH operand
    key_field: str = ""  # KEY operand
    resp_field: str = ""  # RESP operand
    resp2_field: str = ""  # RESP2 operand
    resp_handling: CicsRespHandling = CicsRespHandling.NO_HANDLE
    map_name: str = ""  # MAP operand
    mapset_name: str = ""  # MAPSET operand
    terminal_id: str = ""  # TERMID operand
    rid_field: str = ""  # RIDFLD operand


@dataclass(frozen=True)
class CicsHandleCondition:
    """A HANDLE CONDITION specification.

    Represents HANDLE CONDITION condition=paragraph.
    """
    condition: CicsConditionType
    paragraph: str  # target paragraph name


@dataclass(frozen=True)
class CicsHandleAid:
    """A HANDLE AID specification.

    Represents HANDLE AID key=paragraph.
    """
    aid_type: CicsAidType
    paragraph: str  # target paragraph name


@dataclass(frozen=True)
class CicsAssignment:
    """An ASSIGN variable specification.

    Represents ASSIGN field=variable.
    """
    field: str  # the CICS field being assigned (EIBAID, EIBDATE, etc.)
    variable: str  # the COBOL variable receiving the value


@dataclass(frozen=True)
class CicsContainer:
    """A CICS channel/container reference.

    Represents a container within a channel for inter-program communication.
    """
    name: str  # container name
    data_area: str = ""  # DATAAREA field
    length: str = ""  # LENGTH field
    data_type: str = ""  # data type hint


@dataclass(frozen=True)
class CicsChannel:
    """A CICS channel.

    Represents a channel with containers for inter-program communication.
    """
    name: str  # channel name
    containers: tuple[CicsContainer, ...] = ()


@dataclass(frozen=True)
class CicsTransaction:
    """A CICS transaction definition.

    Maps transaction ID to program and attributes.
    """
    transaction_id: str
    program_id: str
    terminal_id: str = ""
    user_id: str = ""


@dataclass(frozen=True)
class CicsApplication:
    """A CICS application model.

    Represents a COBOL program running under CICS with its
    CICS commands, resources, and dependencies.
    """
    program_id: str
    commands: tuple[CicsCommand, ...] = ()
    handle_conditions: tuple[CicsHandleCondition, ...] = ()
    handle_aids: tuple[CicsHandleAid, ...] = ()
    assignments: tuple[CicsAssignment, ...] = ()
    channels: tuple[CicsChannel, ...] = ()
    transactions: tuple[CicsTransaction, ...] = ()
    # Resource dependencies
    file_resources: tuple[str, ...] = ()  # DATASET names
    queue_resources: tuple[str, ...] = ()  # QUEUE names
    program_resources: tuple[str, ...] = ()  # PROGRAM names (LINK/XCTL)
    map_resources: tuple[str, ...] = ()  # MAP/MAPSET names
    terminal_resources: tuple[str, ...] = ()  # TERMID values
    # Host variable references
    host_variables: tuple[str, ...] = ()  # all :WS-xxx references
    # Raw embedded CICS text
    raw_text: str = ""

    def get_program_dependencies(self) -> list[str]:
        """Get all programs referenced via LINK or XCTL."""
        deps: list[str] = []
        for cmd in self.commands:
            if cmd.command_type in (CicsCommandType.LINK, CicsCommandType.XCTL):
                if cmd.program_name and cmd.program_name not in deps:
                    deps.append(cmd.program_name)
        return deps

    def get_file_dependencies(self) -> list[tuple[str, str]]:
        """Get all (operation, dataset) file dependencies."""
        deps: list[tuple[str, str]] = []
        for cmd in self.commands:
            if cmd.command_type in (
                CicsCommandType.READ, CicsCommandType.WRITE,
                CicsCommandType.REWRITE, CicsCommandType.DELETE,
                CicsCommandType.STARTBR, CicsCommandType.READNEXT,
                CicsCommandType.READPREV, CicsCommandType.ENDBR,
            ):
                if cmd.resource_name:
                    dep = (cmd.command_type.value, cmd.resource_name)
                    if dep not in deps:
                        deps.append(dep)
        return deps

    def get_transaction_dependencies(self) -> list[tuple[str, str]]:
        """Get all (transaction_id, program_id) relationships."""
        deps: list[tuple[str, str]] = []
        for txn in self.transactions:
            dep = (txn.transaction_id, txn.program_id)
            if dep not in deps:
                deps.append(dep)
        return deps

    def validate(self) -> list[str]:
        """Validate the CICS application model.

        Returns list of validation errors.
        """
        errors: list[str] = []

        # Check for commands with missing resource names
        for cmd in self.commands:
            if cmd.command_type in (
                CicsCommandType.READ, CicsCommandType.WRITE,
                CicsCommandType.REWRITE, CicsCommandType.DELETE,
                CicsCommandType.STARTBR, CicsCommandType.READNEXT,
                CicsCommandType.READPREV, CicsCommandType.ENDBR,
            ):
                if not cmd.resource_name:
                    errors.append(
                        f"{cmd.command_type.value} command missing DATASET resource name"
                    )

        # Check for LINK/XCTL without PROGRAM
        for cmd in self.commands:
            if cmd.command_type in (CicsCommandType.LINK, CicsCommandType.XCTL):
                if not cmd.program_name:
                    errors.append(
                        f"{cmd.command_type.value} command missing PROGRAM name"
                    )

        # Check for SEND without terminal/map
        for cmd in self.commands:
            if cmd.command_type == CicsCommandType.SEND:
                if not cmd.map_name and not cmd.terminal_id:
                    errors.append("SEND command missing MAP or TERMID")

        return errors
