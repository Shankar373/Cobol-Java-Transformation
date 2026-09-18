"""COBOL source model — typed AST for parsed COBOL programs.

This module defines the concrete syntax tree produced by the parser.
It is the input to semantic analysis and the foundation for the IR.

Architecture:

    COBOL source text
        ↓
    Parser
        ↓
    CobolProgram (source model)
        ↓
    Semantic Analyzer
        ↓
    IR (CobolProgramIR)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DivisionType(Enum):
    IDENTIFICATION = "IDENTIFICATION"
    ENVIRONMENT = "ENVIRONMENT"
    DATA = "DATA"
    PROCEDURE = "PROCEDURE"


class SectionType(Enum):
    FILE_CONTROL = "FILE_CONTROL"
    INPUT_OUTPUT = "INPUT_OUTPUT"
    FILE_SECTION = "FILE_SECTION"
    WORKING_STORAGE = "WORKING_STORAGE"
    PROCEDURE = "PROCEDURE"


class StatementType(Enum):
    OPEN = "OPEN"
    CLOSE = "CLOSE"
    READ = "READ"
    WRITE = "WRITE"
    MOVE = "MOVE"
    ADD = "ADD"
    SUBTRACT = "SUBTRACT"
    MULTIPLY = "MULTIPLY"
    DIVIDE = "DIVIDE"
    COMPUTE = "COMPUTE"
    IF = "IF"
    PERFORM = "PERFORM"
    DISPLAY = "DISPLAY"
    ACCEPT = "ACCEPT"
    STRING = "STRING"
    UNSTRING = "UNSTRING"
    GO_TO = "GO_TO"
    STOP_RUN = "STOP_RUN"
    EVALUATE = "EVALUATE"
    CALL = "CALL"
    SORT = "SORT"


@dataclass(frozen=True)
class SourceLocation:
    """Location in COBOL source."""
    line: int
    column: int = 0


@dataclass(frozen=True)
class SourceSpan:
    """Range in COBOL source."""
    start: SourceLocation
    end: SourceLocation


@dataclass(frozen=True)
class PicClause:
    """PICTURE clause representation."""
    raw: str  # e.g., "X(10)", "9(5)V99"
    is_alphanumeric: bool
    is_numeric: bool
    is_edited: bool
    length: int
    scale: int = 0  # decimal places (V position)


@dataclass(frozen=True)
class FileControlEntry:
    """FILE-CONTROL SELECT statement."""
    file_name: str
    assign_to: str
    organization: str = "LINE SEQUENTIAL"
    location: SourceSpan | None = None


@dataclass(frozen=True)
class FileSectionEntry:
    """FILE SECTION FD entry."""
    fd_name: str
    record_name: str
    record_pic: PicClause | None = None
    location: SourceSpan | None = None


@dataclass(frozen=True)
class WorkingStorageItem:
    """WORKING-STORAGE data item."""
    level: int
    name: str
    pic: PicClause | None = None
    value: str | None = None
    occurs: int | None = None
    children: tuple[WorkingStorageItem, ...] = ()
    location: SourceSpan | None = None


@dataclass(frozen=True)
class StatementNode:
    """Base for all statement nodes."""
    statement_type: StatementType
    location: SourceSpan | None = None


@dataclass(frozen=True)
class OpenNode(StatementNode):
    """OPEN INPUT/OUTPUT."""
    mode: str  # "INPUT" or "OUTPUT"
    file_name: str = ""

    def __post_init__(self):
        object.__setattr__(self, 'statement_type', StatementType.OPEN)


@dataclass(frozen=True)
class CloseNode(StatementNode):
    """CLOSE file."""
    file_name: str = ""

    def __post_init__(self):
        object.__setattr__(self, 'statement_type', StatementType.CLOSE)


@dataclass(frozen=True)
class ReadNode(StatementNode):
    """READ file AT END / NOT AT END."""
    file_name: str = ""
    record_name: str = ""
    at_end_body: tuple[StatementNode, ...] = ()
    not_at_end_body: tuple[StatementNode, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, 'statement_type', StatementType.READ)


@dataclass(frozen=True)
class WriteNode(StatementNode):
    """WRITE record."""
    record_name: str = ""
    file_name: str = ""

    def __post_init__(self):
        object.__setattr__(self, 'statement_type', StatementType.WRITE)


@dataclass(frozen=True)
class MoveNode(StatementNode):
    """MOVE source TO target."""
    source: str = ""
    target: str = ""

    def __post_init__(self):
        object.__setattr__(self, 'statement_type', StatementType.MOVE)


@dataclass(frozen=True)
class AddNode(StatementNode):
    """ADD source TO target."""
    source: str = ""
    target: str = ""

    def __post_init__(self):
        object.__setattr__(self, 'statement_type', StatementType.ADD)


@dataclass(frozen=True)
class ComputeNode(StatementNode):
    """COMPUTE target = expression."""
    target: str = ""
    expression: str = ""

    def __post_init__(self):
        object.__setattr__(self, 'statement_type', StatementType.COMPUTE)


@dataclass(frozen=True)
class IfNode(StatementNode):
    """IF condition THEN ... ELSE ... END-IF."""
    condition: str = ""
    then_body: tuple[StatementNode, ...] = ()
    else_body: tuple[StatementNode, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, 'statement_type', StatementType.IF)


@dataclass(frozen=True)
class PerformNode(StatementNode):
    """PERFORM paragraph."""
    paragraph_name: str = ""
    until_condition: str | None = None
    varying_var: str | None = None
    from_value: str | None = None
    by_value: str | None = None
    times: int | None = None

    def __post_init__(self):
        object.__setattr__(self, 'statement_type', StatementType.PERFORM)


@dataclass(frozen=True)
class DisplayNode(StatementNode):
    """DISPLAY parts UPON destination."""
    parts: tuple[str, ...] = ()
    destination: str = "STDOUT"

    def __post_init__(self):
        object.__setattr__(self, 'statement_type', StatementType.DISPLAY)


@dataclass(frozen=True)
class StringNode(StatementNode):
    """STRING parts INTO target."""
    parts: tuple[str, ...] = ()
    target: str = ""

    def __post_init__(self):
        object.__setattr__(self, 'statement_type', StatementType.STRING)


@dataclass(frozen=True)
class UnstringNode(StatementNode):
    """UNSTRING source DELIMITED BY delimiter INTO targets."""
    source: str = ""
    delimiter: str = ""
    targets: tuple[str, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, 'statement_type', StatementType.UNSTRING)


@dataclass(frozen=True)
class GoToNode(StatementNode):
    """GO TO paragraph."""
    target: str = ""

    def __post_init__(self):
        object.__setattr__(self, 'statement_type', StatementType.GO_TO)


@dataclass(frozen=True)
class StopRunNode(StatementNode):
    """STOP RUN."""

    def __post_init__(self):
        object.__setattr__(self, 'statement_type', StatementType.STOP_RUN)


@dataclass(frozen=True)
class ParagraphNode:
    """A COBOL paragraph."""
    name: str
    statements: tuple[StatementNode, ...] = ()
    location: SourceSpan | None = None


@dataclass(frozen=True)
class CobolProgram:
    """Complete parsed COBOL program (source model).

    This is the output of the parser and the input to semantic analysis.
    """
    program_id: str
    author: str = ""
    file_control: tuple[FileControlEntry, ...] = ()
    file_section: tuple[FileSectionEntry, ...] = ()
    working_storage: tuple[WorkingStorageItem, ...] = ()
    paragraphs: tuple[ParagraphNode, ...] = ()
    raw_source: str = ""
    diagnostics: tuple[str, ...] = ()
