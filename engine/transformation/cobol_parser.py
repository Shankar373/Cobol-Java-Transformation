"""COBOL parser for generic supported constructs.

Parses COBOL source into the IR. This is NOT a general-purpose COBOL parser.
It handles only the supported constructs:

- IDENTIFICATION DIVISION
- ENVIRONMENT DIVISION (FILE-CONTROL)
- DATA DIVISION (FILE SECTION, WORKING-STORAGE SECTION)
- PROCEDURE DIVISION (paragraphs, statements)
- PIC X(n), PIC 9(n)
- OCCURS clause
- OPEN, CLOSE, READ, WRITE, START, REWRITE, DELETE, MOVE, ADD, DIVIDE,
  IF/ELSE, PERFORM, UNSTRING, STRING
- DISPLAY, GO TO, STOP RUN
- File verbs carry AT END / NOT AT END (READ) and INVALID KEY /
  NOT INVALID KEY (READ, WRITE, START, REWRITE, DELETE) clause bodies
  for the deterministic single-file subset.  Alternate keys, multi-file
  CLOSE, and relational-word START operators (GREATER/LESS/EQUAL) are
  outside the subset: they emit diagnostics and stay fail-closed, never
  silently mapped to the symbolic-operator runtime.

Unsupported constructs will raise CobolParseError.
"""

from __future__ import annotations

import re
from typing import Any

from engine.transformation.diagnostics import DiagnosticCode, DiagnosticCollector
from engine.transformation.figurative import parse_figurative_constant
from engine.transformation.semantic_capability import canonical_usage
from engine.transformation.ir import (
    AddStatement,
    CallStatement,
    BinaryExpression,
    BooleanCondition,
    CobolProgram,
    Comparison,
    Condition,
    DataItem,
    DisplayStatement,
    DivideStatement,
    ExitProgramStatement,
    Expression,
    FileAccessMode,
    FieldReference,
    FileDefinition,
    FigurativeConstant,
    IntrinsicCall,
    FileKey,
    FileKeyType,
    FileOrganization,
    GoToStatement,
    IfStatement,
    InputRecordMapping,
    Literal,
    LogicalCondition,
    LookupOperation,
    MoveStatement,
    NegatedCondition,
    OpenStatement,
    CloseStatement,
    OutputFieldDefinition,
    OutputFormat,
    Paragraph,
    PerformStatement,
    PicType,
    ReadStatement,
    RecordFormat,
    StartStatement,
    RewriteStatement,
    DeleteStatement,
    StatusCodeMapping,
    StopRunStatement,
    StringStatement,
    SubtractStatement,
    MultiplyStatement,
    ThresholdRule,
    UnaryExpression,
    UnstringStatement,
    WriteStatement,
)


class CobolParseError(Exception):
    """Raised when COBOL source contains unsupported or invalid syntax."""


# A statement's own closing delimiter (or a stand-alone paragraph/section
# terminator).  These are structure, not constructs: recognising them keeps a
# left-over END-* out of the unsupported-statement diagnostic channel, where it
# would otherwise be reported as semantic loss.
_SCOPE_TERMINATOR = re.compile(
    r"^END-(?:READ|WRITE|REWRITE|DELETE|START|STRING|UNSTRING|PERFORM|IF|EVALUATE"
    r"|SEARCH|CALL|EXEC|PARA(?:GRAPH)?|SECTION)\.?$"
    r"|^(?:CONTINUE)\.?$",
    re.IGNORECASE,
)

# Words that end in a period but are statements, not paragraph headings.
# Treating them as paragraph names silently splits the program and drops the
# statement itself, so the paragraph detector refuses them explicitly.
_NON_PARAGRAPH_WORDS = frozenset({
    "EXIT", "CONTINUE", "GOBACK", "STOP", "NEXT", "END",
})


# Verbs that can legally begin a statement *inside* a scoped construct.
# COBOL allows a statement to sit on the same line as the control verb that
# opens the scope, e.g. `WHEN 1 DISPLAY "X"` or `IF A > 1 THEN MOVE ...`.
# The parser previously treated every token after `WHEN `/`IF ` as part of the
# condition, so those statements were absorbed into the condition string and
# silently dropped (BL-020).  Detecting the boundary needs the same verb
# vocabulary `_parse_statement` dispatches on, so the two stay in step.
_STATEMENT_LEADING_VERBS: tuple[str, ...] = (
    "OPEN", "READ", "WRITE", "CLOSE", "START", "REWRITE", "DELETE",
    "MOVE", "ADD", "SUBTRACT", "MULTIPLY", "DIVIDE", "COMPUTE",
    "CALL", "EVALUATE", "PERFORM", "UNSTRING", "STRING", "DISPLAY",
    "SET", "INITIALIZE", "INSPECT", "SEARCH", "IF", "STOP", "EXIT",
    "GOBACK", "GO", "GOTO", "ACCEPT", "SORT", "MERGE", "ALTER",
)


def split_condition_from_inline_statements(text: str) -> tuple[str, str]:
    """Split ``text`` into (condition, inline statement text).

    Returns the leading condition and everything from the first statement verb
    onward.  Quoted literals are masked first so a ``DISPLAY`` *inside* a
    literal (``IF WS-F = "DISPLAY"``) can never be mistaken for a verb.

    ``END-IF`` / ``END-EVALUATE`` are scope terminators, not statements, so
    they are excluded from the returned statement text and left for the caller
    to consume.
    """
    masked = CobolParser._mask_quoted(text)
    match = _re_inline_statement.search(masked)
    if match is None:
        return text.strip(), ""
    condition = text[: match.start()].strip()
    remainder = text[match.start():].strip()
    # A bare scope terminator is structure, not an executable statement.
    if _SCOPE_TERMINATOR.match(remainder):
        return condition, ""
    return condition, remainder


# COBOL intrinsic function call: ``FUNCTION NAME(args)``.  Matched on the whole
# text so a *field* named e.g. ``FUNCTION-CODE`` (no parentheses) never matches
# and still parses as a normal field reference (BL-024).
_re_intrinsic = re.compile(
    r"^FUNCTION\s+([A-Z][A-Z0-9-]*)\s*\(.*\)$",
    re.IGNORECASE | re.DOTALL,
)


def _split_statements_on_dashes(text: str) -> list[str]:
    """Split inline statement text on the separators between COBOL statements.

    A statement separator inside COBOL is ambiguous (a hyphen is also a word
    character, as in ``WS-NAME``).  Splitting only at a *verb* that follows a
    space is the conservative choice: it keeps ``WS-NAME`` intact while still
    separating ``DISPLAY "A" MOVE X TO Y``.
    """
    masked = CobolParser._mask_quoted(text)
    matches = list(_re_inline_statement.finditer(masked))
    if not matches:
        return [text]
    parts = [text[: matches[0].start()]]
    for idx, match in enumerate(matches):
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        parts.append(text[match.start(): end])
    return [p for p in parts if p.strip()]


_re_inline_statement = re.compile(
    r"(?<![\w-])(?:" + "|".join(_STATEMENT_LEADING_VERBS) + r")(?![\w-])",
    re.IGNORECASE,
)


def _is_paragraph_name(name: str) -> bool:
    """True when ``name`` may be a paragraph heading rather than a statement."""
    upper = name.upper()
    if upper.startswith("END-"):
        return False
    return upper not in _NON_PARAGRAPH_WORDS


# USAGE clause tokens (longest first so COMP-3/COMP-5 are not shadowed by the
# bare COMP alternative).  Only the part of a data-description entry after the
# item name is scanned, so a field literally named COMP cannot be mistaken for
# a usage clause.
_USAGE_CLAUSE = re.compile(
    r"(?<![\w-])(?:COMPUTATIONAL-1|COMPUTATIONAL-2|COMPUTATIONAL-3"
    r"|COMPUTATIONAL-4|COMPUTATIONAL-5|COMPUTATIONAL"
    r"|COMP-1|COMP-2|COMP-3|COMP-4|COMP-5|COMP|PACKED-DECIMAL|BINARY)(?![\w-])",
    re.IGNORECASE,
)


def _parse_usage_clause(rest: str) -> str | None:
    """Extract a canonical USAGE token from a data-description entry tail.

    Quoted literals are stripped first so ``VALUE "COMP"`` never registers as
    a usage clause.  Returns ``None`` when no (non-DISPLAY) usage is present.
    """
    without_literals = re.sub(r"'[^']*'|\"[^\"]*\"", " ", rest)
    match = _USAGE_CLAUSE.search(without_literals)
    if not match:
        return None
    return canonical_usage(match.group(0))


def _clean_line(line: str) -> str:
    """Remove leading/trailing whitespace and trailing period."""
    return line.rstrip()


def _is_area_a(line: str) -> bool:
    """Check if line starts in COBOL Area A (columns 8-11)."""
    return len(line) >= 8 and line[7:8] in (" ", "*", "/")


def _strip_area_prefix(line: str) -> str:
    """Strip COBOL area prefix (first 6 chars of identification + 2 of area A)."""
    if len(line) <= 6:
        return line
    # Lines typically start with spaces + content
    stripped = line.lstrip()
    return stripped


def _parse_pic(pic_str: str) -> tuple[PicType, int]:
    """Parse a PIC clause like 'X(60)', '9(5)', 'XX', '99', etc."""
    pic_str = pic_str.strip().rstrip(".").upper()
    if pic_str.startswith("X(") and pic_str.endswith(")"):
        length = int(pic_str[2:-1])
        return PicType.ALPHANUMERIC, length
    if pic_str.startswith("9(") and pic_str.endswith(")"):
        length = int(pic_str[2:-1])
        return PicType.NUMERIC, length
    if pic_str == "X":
        return PicType.ALPHANUMERIC, 1
    if pic_str == "9":
        return PicType.NUMERIC, 1
    # Handle repeated characters like XX, XXX, 99, 999, etc.
    if pic_str and all(c == "X" for c in pic_str):
        return PicType.ALPHANUMERIC, len(pic_str)
    if pic_str and all(c == "9" for c in pic_str):
        return PicType.NUMERIC, len(pic_str)
    # Handle PIC 9(n)V99 or similar
    if "(" in pic_str:
        try:
            match = re.match(r"([X9])\((\d+)\)", pic_str)
            if match:
                char = match.group(1)
                length = int(match.group(2))
                pic_type = PicType.ALPHANUMERIC if char == "X" else PicType.NUMERIC
                return pic_type, length
        except (ValueError, IndexError):
            pass
    raise CobolParseError(f"Unsupported PIC clause: {pic_str}")


class CobolParser:
    """Parses COBOL source into IR.

    Usage:
        parser = CobolParser()
        program = parser.parse(cobol_source_text)
    """

    def __init__(self, diagnostics: DiagnosticCollector | None = None) -> None:
        self._diagnostics = diagnostics or DiagnosticCollector()
        self._unsupported_statements: list[str] = []
        self._record_owner: dict[str, str] = {}

    @property
    def diagnostics(self) -> DiagnosticCollector:
        """Diagnostics produced by the most recent parse calls.

        Callers that must not lose semantic information (application
        discovery feeding capability analysis) read this collector so that a
        statement the parser could not turn into IR stays visible downstream.
        """
        return self._diagnostics

    def _emit_unparsed(self, statement: str, line: str) -> None:
        """Record that a recognised statement produced no usable IR.

        Without this the statement becomes an empty-but-present IR node that
        still maps to a SUPPORTED registry key, so the capability analyzer
        can never observe the loss.
        """
        self._diagnostics.warning(
            DiagnosticCode.UNSUPPORTED_CONSTRUCT,
            f"Statement did not parse into IR: {statement} ({line.strip()[:60]})",
            location=statement,
        )

    def _note_usage(self, name: str, usage: str | None) -> None:
        """Record a non-DISPLAY USAGE clause as a PARTIAL_SUPPORT diagnostic.

        The numeric *value* path is certified, but the record-area *byte
        encoding* of COMP/COMP-2/COMP-3/... is not.  Emitting this keeps the
        narrowing visible to raw parser consumers (the capability analyzer
        classifies it from ``DataItem.usage`` and must not treat it as loss).
        """
        if not usage:
            return
        self._diagnostics.warning(
            DiagnosticCode.PARTIAL_SUPPORT,
            f"USAGE {usage} on {name}: value semantics only; record-area byte "
            "encoding not certified",
            location=name,
        )

    def parse(self, source: str) -> CobolProgram:
        """Parse COBOL source text into a CobolProgram IR."""
        lines = source.split("\n")
        # Remove comments and empty lines
        code_lines = []
        for line in lines:
            cleaned = _strip_area_prefix(line)
            # Fixed-format source carries a 6-column sequence number and a
            # column-7 indicator.  Free-format source has no such prefix, so
            # only lines that actually begin with six digits are rewritten.
            # Without this every fixed-format source fails to parse.
            area_match = re.match(r"^(\d{6})(.)(.*)$", cleaned)
            if area_match:
                indicator = area_match.group(2)
                if indicator in ("*", "/"):
                    continue  # comment line (column 7 is * or /)
                cleaned = area_match.group(3).lstrip()
            if cleaned and not cleaned.startswith("*"):
                code_lines.append(cleaned)

        # Parse divisions
        # These clauses continue an operation header; they are not new
        # statements. Both structured parsing and semantic extraction need
        # the same logical header (without rewriting the original source).
        logical_lines = []
        for line in code_lines:
            if logical_lines and (
                re.match(r"^(MOVE|ADD)\b", logical_lines[-1], re.IGNORECASE)
                and re.match(r"^TO\b", line, re.IGNORECASE)
                or re.match(r"^IF\b", logical_lines[-1], re.IGNORECASE)
                and re.match(r"^(?:=|<>|<=|>=|<|>|AND\b|OR\b)", line, re.IGNORECASE)
            ):
                logical_lines[-1] += " " + line
            else:
                logical_lines.append(line)
        code_lines = logical_lines
        program_id = self._parse_program_id(code_lines)
        file_defs = self._parse_file_control(code_lines)
        file_section = self._parse_file_section(code_lines)
        # WRITE names a record, not a file.  Resolve record -> owning FD while
        # parsing PROCEDURE DIVISION so the statement carries the real file
        # name instead of a "-REC" -> "-FILE" naming guess.
        self._record_owner = {
            fd.record_name: fd.name
            for fd in file_section
            if fd.record_name and fd.name
        }
        working_storage = self._parse_working_storage(code_lines)
        linkage_section = self._parse_linkage_section(code_lines)
        using_parameters = self._parse_procedure_using(code_lines)
        paragraphs = self._parse_procedure_division(code_lines)
        threshold_rules = self._extract_threshold_rules(code_lines)

        # Extract generic semantic IR directly (no domain-shaped container)
        status_codes = self._extract_status_codes(code_lines)
        has_status = bool(status_codes)
        report_header = self._extract_report_header(code_lines) if has_status else ""
        summary_fields = self._extract_summary_fields(code_lines) if has_status else []
        lookup_op = self._extract_lookup_operation(code_lines) if has_status else None
        match_labels = self._extract_match_outcome_labels(code_lines) if has_status else []

        # Extract output record formats (generic — no domain-specific prefix)
        output_formats = self._extract_output_formats(code_lines) if has_status else []

        # Merge file definitions with record items from FILE SECTION
        file_section_map = {fd.name: fd for fd in file_section}
        merged_files = []
        for fd in file_defs:
            if fd.name in file_section_map:
                fsd = file_section_map[fd.name]
                merged_files.append(FileDefinition(
                    name=fd.name,
                    container_path=fd.container_path,
                    record_name=fsd.record_name,
                    record_items=fsd.record_items,
                    organization=fd.organization,
                    access_mode=fd.access_mode,
                    record_key=fd.record_key,
                    alternate_keys=fd.alternate_keys,
                    relative_key=fd.relative_key,
                    file_status_field=fd.file_status_field,
                    record_contains=fd.record_contains,
                    block_contains=fd.block_contains,
                ))
            else:
                merged_files.append(fd)

        # Extract input record mappings from UNSTRING statements
        input_record_mappings = self._extract_input_record_mappings(
            code_lines, file_section_map,
        )

        # Collect OPEN statements from paragraphs for file role derivation
        open_stmts: list[OpenStatement] = []
        for para in paragraphs:
            for stmt in para.statements:
                if isinstance(stmt, OpenStatement):
                    open_stmts.append(stmt)

        program = CobolProgram(
            program_id=program_id,
            file_definitions=tuple(merged_files),
            working_storage=tuple(working_storage),
            paragraphs=tuple(paragraphs),
            threshold_rules=tuple(threshold_rules),
            input_record_mappings=tuple(input_record_mappings),
            open_statements=tuple(open_stmts),
            status_codes=tuple(status_codes),
            output_formats=tuple(output_formats),
            lookup_operations=(lookup_op,) if lookup_op else (),
            match_outcome_labels=tuple(match_labels),
            summary_fields=tuple(summary_fields),
            report_header=report_header,
            linkage_section=tuple(linkage_section),
            using_parameters=tuple(using_parameters),
        )

        # Validate that input contains a recognizable COBOL structure
        self._validate_program_structure(program, source)

        return program

    def _validate_program_structure(self, program: CobolProgram, source: str) -> None:
        """Emit PARSE_ERROR if input contains no valid COBOL program structure.

        This prevents completely invalid or empty input from being treated
        as a successful transformation.
        """
        has_structure = (
            program.program_id != "UNKNOWN"
            or len(program.file_definitions) > 0
            or len(program.working_storage) > 0
            or len(program.paragraphs) > 0
        )

        if not has_structure:
            self._diagnostics.error(
                DiagnosticCode.PARSE_ERROR,
                "Input contains no valid transformable COBOL program structure. "
                "Expected IDENTIFICATION DIVISION with PROGRAM-ID.",
                location="source input",
            )

    def _parse_program_id(self, lines: list[str]) -> str:
        """Extract PROGRAM-ID from IDENTIFICATION DIVISION."""
        for line in lines:
            match = re.match(r"PROGRAM-ID\.\s*(\S+)", line, re.IGNORECASE)
            if match:
                return match.group(1).rstrip(".")
        return "UNKNOWN"

    def _parse_file_control(self, lines: list[str]) -> list[FileDefinition]:
        """Parse FILE-CONTROL section to extract file definitions.

        Extracts:
        - SELECT clause (file name)
        - ASSIGN TO (container path)
        - ORGANIZATION IS (SEQUENTIAL, INDEXED, RELATIVE)
        - ACCESS MODE IS (SEQUENTIAL, RANDOM, DYNAMIC)
        - RECORD KEY IS (primary key)
        - ALTERNATE RECORD KEY IS (alternate keys)
        - RELATIVE KEY IS (relative key)
        - FILE STATUS IS (status field)
        """
        in_file_control = False
        file_defs: list[FileDefinition] = []
        current_file: str | None = None
        current_path: str | None = None
        current_org = FileOrganization.SEQUENTIAL
        current_access = FileAccessMode.SEQUENTIAL
        current_key: FileKey | None = None
        current_alt_keys: list[FileKey] = []
        current_relative_key = ""
        current_status = ""

        for line in lines:
            upper = line.upper().strip()
            if "FILE-CONTROL" in upper:
                in_file_control = True
                continue
            if in_file_control:
                if upper.startswith("SELECT "):
                    # Save previous file if exists
                    if current_file:
                        file_defs.append(FileDefinition(
                            name=current_file,
                            container_path=current_path or "",
                            record_name="",
                            organization=current_org,
                            access_mode=current_access,
                            record_key=current_key,
                            alternate_keys=tuple(current_alt_keys),
                            relative_key=current_relative_key,
                            file_status_field=current_status,
                        ))
                    parts = line.strip().split()
                    if len(parts) >= 2:
                        current_file = parts[1].rstrip(".")
                        current_path = None
                        current_org = FileOrganization.SEQUENTIAL
                        current_access = FileAccessMode.SEQUENTIAL
                        current_key = None
                        current_alt_keys = []
                        current_relative_key = ""
                        current_status = ""

                if "ASSIGN TO" in upper:
                    match = re.search(r'ASSIGN TO\s*"([^"]+)"', line, re.IGNORECASE)
                    if match:
                        current_path = match.group(1)

                # ORGANIZATION IS
                if "ORGANIZATION" in upper:
                    if "INDEXED" in upper:
                        current_org = FileOrganization.INDEXED
                    elif "RELATIVE" in upper:
                        current_org = FileOrganization.RELATIVE
                    else:
                        current_org = FileOrganization.SEQUENTIAL

                # ACCESS MODE IS
                if "ACCESS MODE" in upper:
                    if "RANDOM" in upper:
                        current_access = FileAccessMode.RANDOM
                    elif "DYNAMIC" in upper:
                        current_access = FileAccessMode.DYNAMIC
                    else:
                        current_access = FileAccessMode.SEQUENTIAL

                # RECORD KEY IS
                if "RECORD KEY" in upper and "ALTERNATE" not in upper:
                    key_match = re.search(r"RECORD KEY\s+IS\s+(\S+)", upper)
                    if key_match:
                        key_name = key_match.group(1).rstrip(".")
                        current_key = FileKey(
                            field_name=key_name,
                            key_type=FileKeyType.PRIMARY,
                        )

                # ALTERNATE RECORD KEY IS
                if "ALTERNATE RECORD KEY" in upper:
                    alt_match = re.search(r"ALTERNATE RECORD KEY\s+IS\s+(\S+)", upper)
                    if alt_match:
                        alt_name = alt_match.group(1).rstrip(".")
                        is_dup = "DUPLICATES" in upper
                        current_alt_keys.append(FileKey(
                            field_name=alt_name,
                            key_type=FileKeyType.ALTERNATE,
                            is_duplicated=is_dup,
                        ))

                # RELATIVE KEY IS
                if "RELATIVE KEY" in upper:
                    rel_match = re.search(r"RELATIVE KEY\s+IS\s+(\S+)", upper)
                    if rel_match:
                        current_relative_key = rel_match.group(1).rstrip(".")

                # FILE STATUS IS
                if "FILE STATUS" in upper:
                    status_match = re.search(r"FILE STATUS\s+IS\s+(\S+)", upper)
                    if status_match:
                        current_status = status_match.group(1).rstrip(".")

                if upper.startswith(("DATA DIVISION", "PROCEDURE DIVISION")):
                    # Save last file
                    if current_file:
                        file_defs.append(FileDefinition(
                            name=current_file,
                            container_path=current_path or "",
                            record_name="",
                            organization=current_org,
                            access_mode=current_access,
                            record_key=current_key,
                            alternate_keys=tuple(current_alt_keys),
                            relative_key=current_relative_key,
                            file_status_field=current_status,
                        ))
                    break

        return file_defs

    def _parse_file_section(self, lines: list[str]) -> list[FileDefinition]:
        """Parse FILE SECTION to extract record definitions."""
        in_file_section = False
        file_defs: list[FileDefinition] = []
        current_fd: str | None = None
        current_record: str | None = None
        current_items: list[DataItem] = []

        for line in lines:
            upper = line.upper().strip()
            if upper == "FILE SECTION.":
                in_file_section = True
                continue
            if in_file_section:
                if upper.startswith("FD "):
                    if current_fd and current_record:
                        file_defs.append(FileDefinition(
                            name=current_fd,
                            container_path="",
                            record_name=current_record,
                            record_items=tuple(current_items),
                        ))
                    parts = line.strip().split()
                    current_fd = parts[1].rstrip(".") if len(parts) >= 2 else None
                    current_record = None
                    current_items = []
                elif current_fd and upper.startswith("01 "):
                    parts = line.strip().split()
                    if len(parts) >= 2:
                        current_record = parts[1].rstrip(".")
                        pic_match = re.search(r"PIC\s+(\S+)", line, re.IGNORECASE)
                        if pic_match:
                            pic_type, pic_length, decimal_places = self._parse_pic_details(
                                pic_match.group(1)
                            )
                            tail = line.strip().split(None, 2)
                            rest = tail[2] if len(tail) > 2 else ""
                            usage = _parse_usage_clause(rest)
                            self._note_usage(current_record, usage)
                            current_items.append(DataItem(
                                name=current_record,
                                pic_type=pic_type,
                                pic_length=pic_length,
                                decimal_places=decimal_places,
                                signed=self._pic_is_signed(pic_match.group(1)),
                                usage=usage,
                            ))
                elif current_fd and re.match(r"\d{2}\s+", upper):
                    # Handle sub-level items (05, 10, 15, etc.)
                    parts = line.strip().split()
                    if len(parts) >= 2:
                        item_name = parts[1].rstrip(".")
                        pic_match = re.search(r"PIC\s+(\S+)", line, re.IGNORECASE)
                        if pic_match:
                            pic_type, pic_length, decimal_places = self._parse_pic_details(
                                pic_match.group(1)
                            )
                            tail = line.strip().split(None, 2)
                            rest = tail[2] if len(tail) > 2 else ""
                            usage = _parse_usage_clause(rest)
                            self._note_usage(item_name, usage)
                            current_items.append(DataItem(
                                name=item_name,
                                pic_type=pic_type,
                                pic_length=pic_length,
                                decimal_places=decimal_places,
                                signed=self._pic_is_signed(pic_match.group(1)),
                                usage=usage,
                            ))
                elif upper.startswith(("WORKING-STORAGE", "PROCEDURE")):
                    if current_fd and current_record:
                        file_defs.append(FileDefinition(
                            name=current_fd,
                            container_path="",
                            record_name=current_record,
                            record_items=tuple(current_items),
                        ))
                    break
        return file_defs

    def parse_data_description_lines(self, lines: list[str]) -> list[DataItem]:
        """Parse COBOL data-description entries for WORKING-STORAGE, LINKAGE or COPYBOOKs."""
        parsed = []
        for raw in lines:
            stripped = raw.strip()
            if not stripped or stripped.startswith(("*", "/")):
                continue
            m = re.match(r"^(\d{1,2})\s+([A-Z0-9][\w-]*)\b(.*)$", stripped, re.IGNORECASE)
            if not m:
                continue
            level, name, rest = int(m.group(1)), m.group(2).rstrip("."), m.group(3)
            pic = re.search(r"\bPIC(?:TURE)?\s+([A-Z0-9()V+\-]+)", rest, re.IGNORECASE)
            if pic:
                pic_type, pic_length, decimals = self._parse_pic_details(pic.group(1))
            else:
                pic_type, pic_length, decimals = PicType.ALPHANUMERIC, 0, 0
            value_m = re.search(r"(?:^|\s)VALUE\s+(.+?)(?=\s+(?:PIC|OCCURS|REDEFINES|VALUE)\b|\.$|$)", rest, re.IGNORECASE)
            occurs_m = re.search(r"\bOCCURS\s+(\d+)", rest, re.IGNORECASE)
            redef_m = re.search(r"\bREDEFINES\s+([A-Z0-9][\w-]*)", rest, re.IGNORECASE)
            usage = _parse_usage_clause(rest)
            self._note_usage(name, usage)
            parsed.append((level, DataItem(
                name=name, level=level, pic_type=pic_type, pic_length=pic_length,
                decimal_places=decimals,
                signed=self._pic_is_signed(pic.group(1)) if pic else False,
                value=value_m.group(1).strip().rstrip(".") if value_m else None,
                occurs=int(occurs_m.group(1)) if occurs_m else None,
                redefines=redef_m.group(1).rstrip(".") if redef_m else None,
                usage=usage,
            )))
        roots = []
        stack = []
        def replace_node(root, target, replacement):
            if root is target:
                return replacement
            if not root.children:
                return root
            children = tuple(replacement if c is target else replace_node(c, target, replacement) for c in root.children)
            return DataItem(name=root.name, level=root.level, pic_type=root.pic_type,
                            pic_length=root.pic_length, decimal_places=root.decimal_places,
                            signed=root.signed, value=root.value, occurs=root.occurs, redefines=root.redefines,
                            usage=root.usage,
                            children=children)
        for level, item in parsed:
            while stack and stack[-1][0] >= level:
                stack.pop()
            if not stack:
                roots.append(item)
            else:
                parent_level, parent = stack[-1]
                updated = DataItem(name=parent.name, level=parent.level, pic_type=parent.pic_type,
                                   pic_length=parent.pic_length, decimal_places=parent.decimal_places,
                                   signed=parent.signed, value=parent.value, occurs=parent.occurs, redefines=parent.redefines,
                                   usage=parent.usage,
                                   children=parent.children + (item,))
                roots = [replace_node(r, parent, updated) for r in roots]
                stack[-1] = (parent_level, updated)
            stack.append((level, item))
        return roots

    @staticmethod
    def _pic_is_signed(pic_str: str) -> bool:
        """Return True when a PIC has an explicit leading S sign."""
        return pic_str.strip().upper().startswith("S")

    def _parse_pic_details(self, pic_str: str) -> tuple[PicType, int, int]:
        pic = pic_str.strip().rstrip(".").upper()
        if pic.startswith("S"):
            pic = pic[1:]
        if "V" in pic:
            left, right = pic.split("V", 1)
            typ, left_len = _parse_pic(left)
            right_len = len(re.findall(r"9", right))
            return typ, left_len + right_len, right_len
        typ, length = _parse_pic(pic)
        return typ, length, 0

    def _parse_linkage_section(self, lines: list[str]) -> list[DataItem]:
        start = next((i + 1 for i, line in enumerate(lines) if "LINKAGE SECTION" in line.upper()), None)
        if start is None:
            return []
        end = next((i for i in range(start, len(lines)) if "PROCEDURE DIVISION" in lines[i].upper()), len(lines))
        return self.parse_data_description_lines(lines[start:end])

    def _parse_procedure_using(self, lines: list[str]) -> list[str]:
        for line in lines:
            m = re.search(r"PROCEDURE DIVISION\s+USING\s+(.+)", line, re.IGNORECASE)
            if m:
                return [token.rstrip(".") for token in m.group(1).split()]
        return []

    def _parse_working_storage(self, lines: list[str]) -> list[DataItem]:
        """Parse WORKING-STORAGE SECTION to extract data items."""
        in_ws = False
        items: list[DataItem] = []
        current_group_name: str | None = None
        current_group_children: list[DataItem] = []

        for line in lines:
            upper = line.upper().strip()
            if "WORKING-STORAGE SECTION" in upper:
                in_ws = True
                continue
            if in_ws:
                if upper.startswith("PROCEDURE DIVISION"):
                    break
                if not upper or upper.startswith("*"):
                    continue

                # Check for level 01 or 05 items
                level_match = re.match(r"\s*(\d+)\s+(\S+)", line)
                if not level_match:
                    continue

                level = int(level_match.group(1))
                item_name = level_match.group(2).rstrip(".")

                # Check for PIC clause
                pic_match = re.search(r"PIC\s+(\S+)", line, re.IGNORECASE)
                value_match = re.search(
                    r"(?:^|\s)VALUE\s+(.+?)(?=\s+(?:PIC|OCCURS|REDEFINES|VALUE)\b|\.?$)",
                    line,
                    re.IGNORECASE,
                )
                occurs_match = re.search(r"OCCURS\s+(\d+)", line, re.IGNORECASE)
                usage = _parse_usage_clause(line[level_match.end():])
                self._note_usage(item_name, usage)

                if pic_match:
                    pic_type, pic_length, decimal_places = self._parse_pic_details(
                        pic_match.group(1)
                    )
                    value = value_match.group(1).strip().rstrip(".") if value_match else None
                    occurs = int(occurs_match.group(1)) if occurs_match else None

                    if level == 5 and current_group_name:
                        # Level 05 under a group
                        current_group_children.append(DataItem(
                            name=item_name,
                            pic_type=pic_type,
                            pic_length=pic_length,
                            decimal_places=decimal_places,
                                signed=self._pic_is_signed(pic_match.group(1)),
                            value=value,
                            usage=usage,
                        ))
                    else:
                        # Level 01 — standalone item
                        items.append(DataItem(
                            name=item_name,
                            pic_type=pic_type,
                            pic_length=pic_length,
                            decimal_places=decimal_places,
                                signed=self._pic_is_signed(pic_match.group(1)),
                            value=value,
                            occurs=occurs,
                            usage=usage,
                        ))
                        current_group_name = item_name if level == 1 else None
                        current_group_children = []

                elif occurs_match and level == 5:
                    # Level 05 group with OCCURS (table structure)
                    current_group_name = item_name
                    current_group_children = []
                elif level == 10 and current_group_name:
                    # Level 10 under a group — children
                    if pic_match:
                        pic_type, pic_length, decimal_places = self._parse_pic_details(
                            pic_match.group(1)
                        )
                        current_group_children.append(DataItem(
                            name=item_name,
                            pic_type=pic_type,
                            pic_length=pic_length,
                            decimal_places=decimal_places,
                                signed=self._pic_is_signed(pic_match.group(1)),
                            usage=usage,
                        ))

        return items

    def _parse_procedure_division(self, lines: list[str]) -> list[Paragraph]:
        """Parse PROCEDURE DIVISION into paragraphs with statements.
        
        Uses a two-pass approach:
        1. First pass: collect all paragraph names
        2. Second pass: parse statements with knowledge of all paragraph names
        """
        # First pass: collect all paragraph names (exclude scope terminators)
        paragraph_names: set[str] = set()
        for line in lines:
            upper = line.upper().strip()
            if not upper or upper.startswith("*"):
                continue
            para_match = re.match(r"([A-Z0-9][\w-]*)\.", line.strip())
            if para_match and "PIC" not in upper and "VALUE" not in upper:
                name = para_match.group(1)
                if _is_paragraph_name(name):
                    paragraph_names.add(name)

        # Second pass: parse with knowledge of all paragraph names
        in_procedure = False
        paragraphs: list[Paragraph] = []
        current_paragraph: str | None = None
        current_statements: list[Any] = []

        i = 0
        while i < len(lines):
            line = lines[i]
            upper = line.upper().strip()

            if "PROCEDURE DIVISION" in upper:
                in_procedure = True
                i += 1
                continue

            if not in_procedure:
                i += 1
                continue

            # Skip empty/comment lines
            if not upper or upper.startswith("*"):
                i += 1
                continue

            # Check for paragraph name (ends with period, no PIC/VALUE/etc.)
            # Scope terminators (END-PERFORM., END-EVALUATE., ...) are NOT
            # paragraph names — treating them as such splits STOP RUN out of
            # the driver paragraph and triggers false fall-through flags.
            para_match = re.match(r"([A-Z0-9][\w-]*)\.", line.strip())
            if para_match and "PIC" not in upper and "VALUE" not in upper:
                name = para_match.group(1)
                if _is_paragraph_name(name):
                    # Save previous paragraph
                    if current_paragraph:
                        paragraphs.append(Paragraph(
                            name=current_paragraph,
                            statements=tuple(current_statements),
                        ))
                    current_paragraph = name
                    current_statements = []
                    i += 1
                    continue

            # Parse statements within the current paragraph. If the source
            # has no named paragraph, create one only when the first real
            # statement is encountered; this avoids an empty synthetic
            # paragraph before a normal named paragraph.
            if current_paragraph is None:
                current_paragraph = "MAIN"
                current_statements = []
            if current_paragraph:
                stmt, new_i = self._parse_statement(lines, i)
                if stmt is not None:
                    current_statements.append(stmt)
                i = new_i
            else:
                i += 1

        # Save last paragraph
        if current_paragraph:
            paragraphs.append(Paragraph(
                name=current_paragraph,
                statements=tuple(current_statements),
            ))

        return paragraphs

    def _parse_statement(self, lines: list[str], start: int) -> tuple[Any, int]:
        """Parse a single statement starting at the given line index."""
        line = lines[start].strip()
        upper = line.upper()

        # OPEN
        if upper.startswith("OPEN "):
            return self._parse_open(lines, start)

        # READ
        if upper.startswith("READ "):
            return self._parse_read(lines, start)

        # WRITE
        if upper.startswith("WRITE "):
            return self._parse_write(lines, start)

        # CLOSE (single-file deterministic subset; multi-file CLOSE warns)
        if upper.startswith("CLOSE "):
            return self._parse_close(lines, start)

        # START file KEY IS [op] key [INVALID KEY ...] (indexed/relative)
        if upper.startswith("START "):
            return self._parse_start(lines, start)

        # REWRITE record [FROM field] [INVALID KEY ...]
        if upper.startswith("REWRITE "):
            return self._parse_rewrite(lines, start)

        # DELETE file [RECORD] [INVALID KEY ...]
        if upper.startswith("DELETE "):
            return self._parse_delete(lines, start)

        # MOVE
        if upper.startswith("MOVE "):
            return self._parse_move(lines, start)

        # ADD
        if upper.startswith("ADD "):
            return self._parse_add(lines, start)

        # SUBTRACT
        if upper.startswith("SUBTRACT "):
            return self._parse_subtract(lines, start)

        # MULTIPLY
        if upper.startswith("MULTIPLY "):
            return self._parse_multiply(lines, start)

        # CALL
        if upper.startswith("CALL "):
            return self._parse_call(lines, start)

        # DIVIDE
        if upper.startswith("DIVIDE "):
            return self._parse_divide(lines, start)

        # COMPUTE
        if upper.startswith("COMPUTE "):
            return self._parse_compute(lines, start)

        # EVALUATE
        if upper.startswith("EVALUATE "):
            return self._parse_evaluate(lines, start)

        # IF
        if upper.startswith("IF "):
            return self._parse_if(lines, start)

        # PERFORM
        if upper.startswith("PERFORM "):
            return self._parse_perform(lines, start)

        # UNSTRING
        if upper.startswith("UNSTRING "):
            return self._parse_unstring(lines, start)

        # STRING
        if upper.startswith("STRING "):
            return self._parse_string(lines, start)

        # DISPLAY
        if upper.startswith("DISPLAY "):
            return self._parse_display(lines, start)

        # GO TO
        if upper.startswith(("GO TO", "GOTO")):
            return self._parse_goto(lines, start)

        # EXIT PROGRAM — terminate this program and return to the caller.
        # Recognised explicitly so it reaches the IR instead of being dropped
        # by the unknown-statement fallthrough.
        if upper.startswith("EXIT PROGRAM"):
            return ExitProgramStatement(), start + 1

        # STOP RUN
        if upper.startswith("STOP RUN"):
            return StopRunStatement(), start + 1

        # Scope terminators left behind by a statement parser that returned
        # before its closing delimiter.  They carry no executable semantics of
        # their own, so consuming them here keeps them out of the
        # unsupported-statement channel instead of degrading the program on a
        # non-construct.
        if _SCOPE_TERMINATOR.match(line):
            return None, start + 1

        # Unknown statement — skip
        line = lines[start].strip()
        self._diagnostics.warning(
            DiagnosticCode.UNSUPPORTED_CONSTRUCT,
            f"Skipped unsupported statement: {line[:60]}",
            location=f"line {start + 1}",
        )
        return None, start + 1

    def _parse_open(self, lines: list[str], start: int) -> tuple[OpenStatement, int]:
        """Parse OPEN INPUT/OUTPUT/I-O/EXTEND statement (single-file subset)."""
        line = lines[start].strip()
        upper = line.upper()

        if re.search(r"\bI-O\b|\bI\s+O\b", upper):
            mode = "I-O"
        elif "INPUT" in upper:
            mode = "INPUT"
        elif "OUTPUT" in upper:
            mode = "OUTPUT"
        elif "EXTEND" in upper:
            mode = "EXTEND"
        else:
            mode = "INPUT"
            self._diagnostics.warning(
                DiagnosticCode.UNSUPPORTED_CONSTRUCT,
                f"OPEN: unrecognised mode, defaulting to INPUT (fail-closed): "
                f"{line[:60]}",
                location=f"line {start + 1}",
            )

        # Extract file name
        match = re.search(
            r"OPEN\s+(?:INPUT|OUTPUT|I-O|I\s+O|EXTEND)\s+(\S+)",
            line, re.IGNORECASE,
        )
        file_name = match.group(1).rstrip(".") if match else ""

        return OpenStatement(mode=mode, file_name=file_name), start + 1

    # Clause headers for file verbs, longest match first so NOT-forms win
    # over their bare counterparts.  Section names are collector-internal.
    _FILE_CLAUSE_HEADERS: tuple[tuple[str, re.Pattern[str]], ...] = (
        ("not_at_end", re.compile(r"\bNOT\s+AT\s+END\b", re.IGNORECASE)),
        ("at_end", re.compile(r"\bAT\s+END\b", re.IGNORECASE)),
        ("not_invalid", re.compile(r"\bNOT\s+INVALID\s+KEY\b", re.IGNORECASE)),
        ("invalid", re.compile(r"\bINVALID\s+KEY\b", re.IGNORECASE)),
    )

    # Quoted-literal mask for clause-header scanning.  Body statements such
    # as DISPLAY "READ K999 INVALID KEY ..." carry clause keywords inside
    # literals; scanning raw text misclassifies the body line as a clause
    # header, silently dropping the statement.  Masking replaces each
    # literal with equal-length blanks so match offsets stay valid for the
    # original text (same discipline as semantic_capability scanning).
    _QUOTED_LITERAL = re.compile(r"'(?:''|[^'])*'|\"[^\"]*\"")

    @staticmethod
    def _mask_quoted(text: str) -> str:
        """Blank quoted literals, preserving string length/offsets."""
        return CobolParser._QUOTED_LITERAL.sub(
            lambda match: " " * len(match.group(0)), text,
        )

    def _collect_file_clauses(
        self,
        lines: list[str],
        start: int,
        allowed: tuple[str, ...],
        end_markers: tuple[str, ...],
        verb_label: str,
    ) -> tuple[dict[str, list[Any]], int]:
        """Collect AT END / INVALID KEY clause bodies for one file verb.

        Deterministic single-statement subset: the verb header lives on
        ``lines[start]``; clause headers (``allowed``) may sit on the verb
        line or on following lines; bodies end at the scope terminator
        (``end_markers``, e.g. END-READ) or at the terminating period
        (COBOL scope rule).  Consumption is bounded: a line that is
        neither a clause header, a scope terminator, nor a body statement
        of an open clause ends the verb instead of being swallowed.
        Unclosed clauses emit an UNSUPPORTED_CONSTRUCT diagnostic and stay
        fail-closed (the partial body is kept, never silently completed).
        """
        sections: dict[str, list[Any]] = {name: [] for name in allowed}
        headers = tuple(
            (name, pattern)
            for name, pattern in self._FILE_CLAUSE_HEADERS
            if name in allowed
        )
        line0 = lines[start].strip()

        def _header_at(text: str) -> tuple[str, re.Match[str]] | None:
            masked = self._mask_quoted(text)
            for name, pattern in headers:
                match = pattern.search(masked)
                if match:
                    return name, match
            return None

        def _feed(section: str, text: str) -> None:
            for segment in [s for s in re.split(r"\s*\.\s*", text) if s.strip()]:
                stmt, _ = self._parse_statement([segment], 0)
                if stmt is not None:
                    sections[section].append(stmt)

        def _cut_end(text: str) -> tuple[str, bool]:
            masked = self._mask_quoted(text)
            for marker in end_markers:
                marker_match = re.search(
                    r"\b" + re.escape(marker) + r"\b", masked, re.IGNORECASE,
                )
                if marker_match:
                    return text[:marker_match.start()], True
            return text, False

        # Inline headers on the verb line itself (literals masked so a
        # quoted keyword can never open a clause).
        masked_line0 = self._mask_quoted(line0)
        ordered: list[tuple[int, str, re.Match[str]]] = []
        for name, pattern in headers:
            for match in pattern.finditer(masked_line0):
                ordered.append((match.start(), name, match))
        ordered.sort(key=lambda item: item[0])
        current_section: str | None = None
        closed = False
        if ordered:
            for index, (_, name, match) in enumerate(ordered):
                end = ordered[index + 1][0] if index + 1 < len(ordered) else len(line0)
                tail = line0[match.end():end]
                tail, saw_end = _cut_end(tail)
                if saw_end:
                    closed = True
                _feed(name, tail)
                current_section = name
            if closed or line0.rstrip().endswith("."):
                closed = True
                return sections, start + 1
        elif line0.rstrip().endswith("."):
            # Period-terminated verb with no clause: the statement is complete.
            return sections, start + 1

        i = start + 1
        while i < len(lines):
            raw = lines[i].strip()
            upper = raw.upper()

            if not raw or raw.startswith("*"):
                i += 1
                continue
            if any(
                upper.startswith(marker) for marker in end_markers
            ):
                i += 1
                closed = True
                break
            found = _header_at(raw)
            if found is not None:
                name, match = found
                current_section = name
                tail = raw[match.end():]
                tail, saw_end = _cut_end(tail)
                if tail.strip().strip("."):
                    _feed(name, tail)
                if saw_end or raw.rstrip().endswith("."):
                    # A period ends the sentence and with it the clause
                    # (COBOL scope rule); the scope terminator itself is left
                    # for the dispatcher so no statement is swallowed.
                    closed = True
                    break
                i += 1
                continue

            if current_section is None:
                # No clause header yet: the verb statement already ended on a
                # previous line.  Stop instead of consuming this statement.
                break

            stmt, i = self._parse_statement(lines, i)
            if stmt is not None and current_section is not None:
                sections[current_section].append(stmt)
            if raw.endswith("."):
                # The period terminates the sentence, and with it the clause.
                closed = True
                break

        if current_section is not None and not closed:
            self._diagnostics.warning(
                DiagnosticCode.UNSUPPORTED_CONSTRUCT,
                f"{verb_label}: {end_markers[0]} not found; clause body may be "
                "incomplete",
                location=f"line {start + 1}",
            )

        return sections, i

    @staticmethod
    def _verb_header_text(line: str, allowed: tuple[str, ...]) -> str:
        """Return the verb-header portion of a file-verb line.

        Everything from the first clause header on is clause tail, not
        header: NEXT/KEY/INTO/FROM extraction must never read the body.
        """
        masked = CobolParser._mask_quoted(line)
        cut = len(line)
        for name, pattern in CobolParser._FILE_CLAUSE_HEADERS:
            if name in allowed:
                match = pattern.search(masked)
                if match:
                    cut = min(cut, match.start())
        return line[:cut]

    def _parse_read(self, lines: list[str], start: int) -> tuple[ReadStatement, int]:
        """Parse READ [NEXT] [KEY IS k] [INTO w] with AT END / INVALID KEY.

        Consumption is bounded (see :meth:`_collect_file_clauses`): the
        statement ends at END-READ, at the terminating period, or — when no
        clause header has been seen yet — at the end of the READ line itself.
        An unbounded scan would swallow every following statement with no
        diagnostic, which is silent semantic loss.
        """
        line = lines[start].strip()
        allowed = ("at_end", "not_at_end", "invalid", "not_invalid")
        header_text = self._verb_header_text(line, allowed)

        # Extract file name (first token after READ; NEXT/RECORD are keywords)
        match = re.search(r"READ\s+(\S+)", header_text, re.IGNORECASE)
        raw_file = match.group(1).rstrip(".") if match else ""
        if raw_file.upper() in ("NEXT", "RECORD", "KEY", "INTO"):
            raw_file = ""
        file_name = raw_file

        # Find record name from FILE SECTION (convention: FILE-NAME becomes record)
        record_name = file_name.replace("-FILE", "-REC").replace("_FILE", "_REC")

        read_next = bool(re.search(r"\bNEXT\b", header_text, re.IGNORECASE))
        key_match = re.search(
            r"\bKEY\s+(?:IS\s+)?(\S+)", header_text, re.IGNORECASE,
        )
        key = key_match.group(1).rstrip(".") if key_match else ""
        into_match = re.search(r"\bINTO\s+(\S+)", header_text, re.IGNORECASE)
        into_field = into_match.group(1).rstrip(".") if into_match else ""

        sections, next_index = self._collect_file_clauses(
            lines, start, allowed, ("END-READ",), f"READ {file_name}",
        )

        return ReadStatement(
            file_name=file_name,
            record_name=record_name,
            key=key,
            into_field=into_field,
            read_next=read_next,
            at_end_body=tuple(sections["at_end"]),
            not_at_end_body=tuple(sections["not_at_end"]),
            invalid_key_body=tuple(sections["invalid"]),
            not_invalid_key_body=tuple(sections["not_invalid"]),
        ), next_index

    def _parse_write(self, lines: list[str], start: int) -> tuple[WriteStatement, int]:
        """Parse WRITE record [FROM field] with INVALID KEY clauses."""
        line = lines[start].strip()
        allowed = ("invalid", "not_invalid")
        header_text = self._verb_header_text(line, allowed)

        match = re.search(r"WRITE\s+(\S+)", header_text, re.IGNORECASE)
        record_name = match.group(1).rstrip(".") if match else ""
        from_match = re.search(r"\bFROM\s+(\S+)", header_text, re.IGNORECASE)
        from_field = from_match.group(1).rstrip(".") if from_match else ""

        # Determine file name from the FILE SECTION record owner.  The
        # "-REC" -> "-FILE" convention is only a fallback for programs whose
        # record never appears in a FILE SECTION FD.
        file_name = (
            self._record_owner.get(record_name)
            or record_name.replace("-REC", "-FILE").replace("_REC", "_FILE")
        )

        sections, next_index = self._collect_file_clauses(
            lines, start, allowed, ("END-WRITE",), f"WRITE {record_name}",
        )

        return WriteStatement(
            record_name=record_name,
            file_name=file_name,
            from_field=from_field,
            invalid_key_body=tuple(sections["invalid"]),
            not_invalid_key_body=tuple(sections["not_invalid"]),
        ), next_index

    def _parse_close(self, lines: list[str], start: int) -> tuple[CloseStatement, int]:
        """Parse CLOSE file (single-file deterministic subset)."""
        line = lines[start].strip()
        tokens = [
            token.rstrip(".")
            for token in re.split(r"\s+", line, flags=re.IGNORECASE)[1:]
            if token.rstrip(".")
        ]
        file_name = tokens[0] if tokens else ""
        if len(tokens) > 1:
            self._diagnostics.warning(
                DiagnosticCode.UNSUPPORTED_CONSTRUCT,
                "CLOSE lists multiple files; deterministic subset closes the "
                f"first ({file_name}), remainder unsupported",
                location=f"line {start + 1}",
            )
        return CloseStatement(file_name=file_name), start + 1

    def _parse_start(self, lines: list[str], start: int) -> tuple[StartStatement, int]:
        """Parse START file KEY IS [op] key with INVALID KEY clauses.

        Supported operators: ``=``, ``>``, ``>=``, ``<``, ``<=`` (optionally
        after KEY IS).  Relational-word operators (GREATER/LESS/EQUAL/NOT)
        are outside the deterministic subset: they emit an
        UNSUPPORTED_CONSTRUCT diagnostic and the operator passes through to
        the runtime, which yields status ``23`` (observable INVALID KEY)
        instead of silently positioning as ``=``.
        """
        line = lines[start].strip()
        allowed = ("invalid", "not_invalid")
        header_text = self._verb_header_text(line, allowed)

        match = re.search(r"START\s+(\S+)", header_text, re.IGNORECASE)
        file_name = match.group(1).rstrip(".") if match else ""

        key = ""
        operator = ""
        key_match = re.search(
            r"\bKEY\s+(?:IS\s+)?(>=|<=|>|<|=)?\s*(\S+)",
            header_text, re.IGNORECASE,
        )
        if key_match:
            operator = key_match.group(1) or ""
            key = (key_match.group(2) or "").rstrip(".")
        if re.search(
            r"\b(GREATER|LESS|EQUAL|NOT\s+LESS|NOT\s+GREATER)\b",
            header_text, re.IGNORECASE,
        ):
            self._diagnostics.warning(
                DiagnosticCode.UNSUPPORTED_CONSTRUCT,
                f"START {file_name}: relational-word operator outside the "
                "deterministic symbolic subset (=, >, >=, <, <=); runtime "
                "yields status 23 (fail-closed INVALID KEY)",
                location=f"line {start + 1}",
            )
            operator = operator if operator in ("=", ">", ">=", "<", "<=") else "UNSUPPORTED"
            if not key or key.upper() in (
                "GREATER", "LESS", "EQUAL", "THAN", "NOT",
            ):
                tail_tokens = [
                    token.rstrip(".")
                    for token in re.split(r"\s+", header_text)
                    if token.rstrip(".")
                ]
                key = tail_tokens[-1] if tail_tokens else key

        sections, next_index = self._collect_file_clauses(
            lines, start, allowed, ("END-START",), f"START {file_name}",
        )

        return StartStatement(
            file_name=file_name,
            key=key,
            operator=operator,
            invalid_key_body=tuple(sections["invalid"]),
            not_invalid_key_body=tuple(sections["not_invalid"]),
        ), next_index

    def _parse_rewrite(self, lines: list[str], start: int) -> tuple[RewriteStatement, int]:
        """Parse REWRITE record [FROM field] with INVALID KEY clauses."""
        line = lines[start].strip()
        allowed = ("invalid", "not_invalid")
        header_text = self._verb_header_text(line, allowed)

        match = re.search(r"REWRITE\s+(\S+)", header_text, re.IGNORECASE)
        record_name = match.group(1).rstrip(".") if match else ""
        from_match = re.search(r"\bFROM\s+(\S+)", header_text, re.IGNORECASE)
        from_field = from_match.group(1).rstrip(".") if from_match else ""
        file_name = record_name.replace("-REC", "-FILE").replace("_REC", "_FILE")

        sections, next_index = self._collect_file_clauses(
            lines, start, allowed, ("END-REWRITE",), f"REWRITE {record_name}",
        )

        return RewriteStatement(
            record_name=record_name,
            file_name=file_name,
            from_field=from_field,
            invalid_key_body=tuple(sections["invalid"]),
            not_invalid_key_body=tuple(sections["not_invalid"]),
        ), next_index

    def _parse_delete(self, lines: list[str], start: int) -> tuple[DeleteStatement, int]:
        """Parse DELETE file [RECORD] with INVALID KEY clauses."""
        line = lines[start].strip()
        allowed = ("invalid", "not_invalid")
        header_text = self._verb_header_text(line, allowed)

        match = re.search(r"DELETE\s+(\S+)", header_text, re.IGNORECASE)
        file_name = match.group(1).rstrip(".") if match else ""

        sections, next_index = self._collect_file_clauses(
            lines, start, allowed, ("END-DELETE",), f"DELETE {file_name}",
        )

        return DeleteStatement(
            file_name=file_name,
            invalid_key_body=tuple(sections["invalid"]),
            not_invalid_key_body=tuple(sections["not_invalid"]),
        ), next_index

    def _parse_move(self, lines: list[str], start: int) -> tuple[MoveStatement, int]:
        """Parse MOVE source TO target statement."""
        line = lines[start].strip()

        match = re.search(r"MOVE\s+(.+?)\s+TO\s+(.+?)(?:\.)?$", line, re.IGNORECASE)
        if match:
            source = match.group(1).strip()
            targets = tuple(t.rstrip(".") for t in match.group(2).split() if t.strip())
            target = targets[0] if targets else ""
            return MoveStatement(
                source=source,
                target=target,
                targets=targets,
                source_expr=self._build_expression(source),
                target_ref=FieldReference(name=target) if target else None,
            ), start + 1

        self._emit_unparsed("MOVE", lines[start])
        return MoveStatement(source="", target=""), start + 1

    def _parse_add(self, lines: list[str], start: int) -> tuple[AddStatement, int]:
        """Parse ADD source TO target statement."""
        line = lines[start].strip().rstrip(".").strip()

        match = re.search(
            r"ADD\s+(.+?)\s+TO\s+(\S+)(?:\s+GIVING\s+(\S+))?(?:\s+ROUNDED)?\s*$",
            line,
            re.IGNORECASE,
        )
        if match:
            source = match.group(1).strip().rstrip(".")
            target = match.group(2).strip().rstrip(".")
            giving_target = match.group(3).strip().rstrip(".") if match.group(3) else None
            rounded = bool(re.search(r"\sROUNDED(?:\s*\.|\s*)$", line, re.IGNORECASE))
            return AddStatement(
                source=source,
                target=target,
                source_expr=self._build_expression(source),
                target_ref=FieldReference(name=target),
                giving_target=giving_target,
                rounded=rounded,
            ), start + 1

        self._emit_unparsed("ADD", lines[start])
        return AddStatement(source="", target=""), start + 1

    def _parse_subtract(self, lines: list[str], start: int) -> tuple[SubtractStatement, int]:
        """Parse SUBTRACT source FROM field [GIVING target]."""
        line = lines[start].strip().rstrip(".").strip()
        match = re.search(
            r"SUBTRACT\s+(\S+)\s+FROM\s+(\S+)(?:\s+GIVING\s+(\S+))?(?:\s+ROUNDED)?\s*$",
            line,
            re.IGNORECASE,
        )
        if not match:
            self._emit_unparsed("SUBTRACT", lines[start])
            return SubtractStatement(source="", from_field=""), start + 1
        source = match.group(1).rstrip(".")
        from_field = match.group(2).rstrip(".")
        to_field = match.group(3).rstrip(".") if match.group(3) else None
        rounded = bool(re.search(r"\sROUNDED(?:\s*\.|\s*)$", line, re.IGNORECASE))
        return SubtractStatement(
            source=source,
            from_field=from_field,
            to_field=to_field,
            source_expr=self._build_expression(source),
            from_ref=FieldReference(name=from_field),
            to_ref=FieldReference(name=to_field) if to_field else None,
            rounded=rounded,
        ), start + 1

    def _parse_multiply(self, lines: list[str], start: int) -> tuple[MultiplyStatement, int]:
        """Parse MULTIPLY source BY field [GIVING target]."""
        line = lines[start].strip().rstrip(".").strip()
        match = re.search(
            r"MULTIPLY\s+(\S+)\s+BY\s+(\S+)(?:\s+GIVING\s+(\S+))?(?:\s+ROUNDED)?\s*$",
            line,
            re.IGNORECASE,
        )
        if not match:
            return MultiplyStatement(source="", multiplicand=""), start + 1
        source = match.group(1).rstrip(".")
        multiplicand = match.group(2).rstrip(".")
        target = match.group(3).rstrip(".") if match.group(3) else None
        rounded = bool(re.search(r"\sROUNDED(?:\s*\.|\s*)$", line, re.IGNORECASE))
        return MultiplyStatement(
            source=source,
            multiplicand=multiplicand,
            target=target,
            source_expr=self._build_expression(source),
            multiplicand_ref=FieldReference(name=multiplicand),
            target_ref=FieldReference(name=target) if target else None,
            rounded=rounded,
        ), start + 1

    def _parse_call(self, lines: list[str], start: int) -> tuple[CallStatement, int]:
        """Parse CALL literal/identifier USING arguments, including continuations.

        Continuation stops at file-clause headers and file scope terminators
        so a CALL body inside a file clause (e.g. under INVALID KEY) never
        swallows the clause structure into its argument list.
        """
        i = start
        parts = [lines[i].strip()]
        while i + 1 < len(lines) and not parts[-1].rstrip().endswith("."):
            nxt = lines[i + 1].strip()
            masked = self._mask_quoted(nxt)
            if any(
                pattern.search(masked)
                for _, pattern in self._FILE_CLAUSE_HEADERS
            ):
                break
            if re.match(
                r"^END-(?:READ|WRITE|REWRITE|DELETE|START)\b",
                nxt, re.IGNORECASE,
            ):
                break
            i += 1
            parts.append(lines[i].strip())
        text = " ".join(parts).rstrip(".").strip()
        match = re.match(r"CALL\s+(?:'([^']+)'|\"([^\"]+)\"|(\S+))(?:\s+USING\s+(.+))?$", text, re.IGNORECASE)
        if not match:
            self._emit_unparsed("CALL", text)
            return CallStatement(program_name="", is_dynamic=True), i + 1
        program_name = next((g for g in match.groups()[:3] if g), "")
        using = match.group(4) or ""
        tokens = using.split()
        arguments=[]
        modes=[]
        current_mode="REFERENCE"
        j=0
        while j < len(tokens):
            tok=tokens[j].upper()
            if tok == "BY" and j + 1 < len(tokens):
                current_mode=tokens[j+1].upper()
                j += 2
                continue
            arguments.append(tokens[j].rstrip(","))
            modes.append(current_mode)
            j += 1
        is_dynamic = not bool(match.group(1) or match.group(2))
        return CallStatement(program_name=program_name, arguments=tuple(arguments), passing_modes=tuple(modes), is_dynamic=is_dynamic), i + 1

    def _parse_divide(self, lines: list[str], start: int) -> tuple[DivideStatement, int]:
        """Parse DIVIDE source BY divisor GIVING target [REMAINDER rem] statement."""
        line = lines[start].strip()

        # Match with optional REMAINDER
        match = re.search(
            r"DIVIDE\s+(\S+)\s+BY\s+(\S+)\s+GIVING\s+(\S+)(?:\s+ROUNDED)?(?:\s+REMAINDER\s+(\S+))?",
            line, re.IGNORECASE,
        )
        if match:
            source = match.group(1).strip().rstrip(".")
            divisor = match.group(2).strip().rstrip(".")
            target = match.group(3).strip().rstrip(".")
            remainder = match.group(4).strip().rstrip(".") if match.group(4) else ""
            rounded = bool(re.search(r"\sROUNDED(?:\s+REMAINDER\b|\s*\.|\s*)", line, re.IGNORECASE))
            return DivideStatement(
                source=source,
                divisor=divisor,
                target=target,
                remainder=remainder,
                source_expr=self._build_expression(source),
                divisor_expr=self._build_expression(divisor),
                target_ref=FieldReference(name=target),
                rounded=rounded,
            ), start + 1

        # DIVIDE <a> INTO <b> [GIVING <c>]: result = b / a.
        # With GIVING, <c> receives b / a and <b> is unchanged; without it
        # <b> itself is overwritten.  Expressed with the same IR fields as the
        # BY form (source = numerator, divisor = denominator).
        into_match = re.search(
            r"DIVIDE\s+(\S+)\s+INTO\s+(\S+)(?:\s+GIVING\s+(\S+))?"
            r"(?:\s+ROUNDED)?(?:\s+REMAINDER\s+(\S+))?",
            line, re.IGNORECASE,
        )
        if into_match:
            numerator = into_match.group(2).strip().rstrip(".")
            denominator = into_match.group(1).strip().rstrip(".")
            target = (
                into_match.group(3).strip().rstrip(".")
                if into_match.group(3)
                else numerator
            )
            remainder = into_match.group(4).strip().rstrip(".") if into_match.group(4) else ""
            rounded = bool(re.search(r"\sROUNDED(?:\s+REMAINDER\b|\s*\.|\s*)", line, re.IGNORECASE))
            return DivideStatement(
                source=numerator,
                divisor=denominator,
                target=target,
                remainder=remainder,
                source_expr=self._build_expression(numerator),
                divisor_expr=self._build_expression(denominator),
                target_ref=FieldReference(name=target),
                rounded=rounded,
            ), start + 1

        self._emit_unparsed("DIVIDE", lines[start])
        return DivideStatement(source="", divisor="", target=""), start + 1

    def _parse_compute(self, lines: list[str], start: int) -> tuple['ComputeStatement', int]:
        """Parse COMPUTE target = expression."""
        from engine.transformation.ir import ComputeStatement

        line = lines[start].strip()

        match = re.search(
            r"COMPUTE\s+(\S+)(?:\s+(ROUNDED))?\s*=\s*(.+?)\.?\s*$",
            line,
            re.IGNORECASE,
        )
        if match:
            target = match.group(1).strip().rstrip(".")
            expression = match.group(3).strip().rstrip(".")
            rounded = bool(match.group(2))
            return ComputeStatement(
                target=target,
                expression=expression,
                target_ref=FieldReference(name=target),
                expression_expr=self._build_expression(expression),
                rounded=rounded,
            ), start + 1

        self._emit_unparsed("COMPUTE", lines[start])
        return ComputeStatement(target="", expression=""), start + 1

    def _parse_inline_statements(self, text: str) -> tuple[list[Any], list[str]]:
        """Parse statements written inline on a control-verb line.

        Returns ``(statements, unparsed)``.  Anything that cannot be turned
        into IR is returned in ``unparsed`` so the caller can emit an explicit
        diagnostic — the construct is never silently discarded (BL-020).
        """
        parsed: list[Any] = []
        unparsed: list[str] = []
        for fragment in _split_statements_on_dashes(text):
            fragment = fragment.strip()
            if not fragment:
                continue
            # A scope terminator shares the line with the statement it closes
            # (`IF A > 1 ADD 1 TO B END-IF`). It is structure, not an operand,
            # so it must not reach the statement parser: `ADD 1 TO B END-IF`
            # would otherwise produce `B = (B + END_IF)`.
            terminator = re.search(
                r"\s+END-(?:IF|EVALUATE|PERFORM|STRING|UNSTRING|READ|WRITE)\s*\.?\s*$",
                fragment, re.IGNORECASE,
            )
            if terminator:
                fragment = fragment[: terminator.start()].strip()
                if not fragment:
                    continue
            synthetic = [fragment]
            stmt, next_i = self._parse_statement(synthetic, 0)
            if stmt is not None and next_i >= len(synthetic):
                parsed.append(stmt)
            else:
                unparsed.append(fragment)
        return parsed, unparsed

    def _parse_evaluate(self, lines: list[str], start: int) -> tuple[IfStatement, int]:
        """Lower EVALUATE/WHEN into nested IF statements."""
        subject = lines[start].strip()[len("EVALUATE "):].rstrip(".").strip()
        arms = []
        i = start + 1
        while i < len(lines):
            u = lines[i].strip().upper()
            if u.startswith("END-EVALUATE"):
                i += 1
                break
            if not u.startswith("WHEN "):
                i += 1
                continue
            spec = lines[i].strip()[len("WHEN "):].rstrip(".").strip()
            i += 1
            body = []
            # BL-020: a statement may sit on the same line as WHEN, e.g.
            # `WHEN 1 DISPLAY "ONE"`.  Without this split the statement text
            # was absorbed into `spec`, turning it into a bogus comparison
            # operand and silently dropping an executable statement.
            spec, inline = split_condition_from_inline_statements(spec)
            if inline:
                inlined, unparsed = self._parse_inline_statements(inline)
                body.extend(inlined)
                for lost in unparsed:
                    self._diagnostics.warning(
                        DiagnosticCode.UNSUPPORTED_CONSTRUCT,
                        f"Inline WHEN statement did not parse into IR: {lost[:60]}",
                        location="EVALUATE",
                    )
            while i < len(lines) and not lines[i].strip().upper().startswith(("WHEN ", "END-EVALUATE")):
                stmt, new_i = self._parse_statement(lines, i)
                if stmt is not None:
                    body.append(stmt)
                i = max(new_i, i + 1)
            arms.append((spec, tuple(body)))
        def cond(spec):
            if spec.upper() == "OTHER":
                return "OTHER"
            # BL-021: `WHEN a ALSO b ALSO c` lists alternative values.  ALSO
            # is a keyword, not a value, so treating it as an operand produced
            # `A = 1 OR A = ALSO OR A = 2`.  Split on ALSO and OR the real
            # alternatives.  The condition mapper renders a top-level
            # ` OR ` chain left-to-right, so alternatives are emitted flat
            # rather than parenthesised: parentheses are stripped downstream
            # and would silently change operator precedence.
            alternatives: list[str] = []
            for group in re.split(r"\s+ALSO\s+", spec, flags=re.IGNORECASE):
                tokens = group.split()
                if not tokens:
                    continue
                up = [t.upper() for t in tokens]
                if "THRU" in up:
                    k = up.index("THRU")
                    if k > 0 and k + 1 < len(tokens):
                        alternatives.append(
                            f"{subject} >= {tokens[k-1]} AND {subject} <= {tokens[k+1]}"
                        )
                        continue
                    # A malformed range must not be silently dropped.
                    self._diagnostics.warning(
                        DiagnosticCode.UNSUPPORTED_CONSTRUCT,
                        f"WHEN range with THRU is incomplete: {group[:60]}",
                        location="EVALUATE",
                    )
                    alternatives.append(f"{subject} = {tokens[0]}")
                    continue
                alternatives.extend(f"{subject} = {token}" for token in tokens)
            if not alternatives:
                return "OTHER"
            return " OR ".join(alternatives)
        def build(idx):
            if idx >= len(arms):
                return None
            spec, body = arms[idx]
            if spec.upper() == "OTHER":
                return IfStatement(condition="OTHER", then_body=body)
            condition = cond(spec)
            if idx + 1 < len(arms) and arms[idx + 1][0].upper() == "OTHER":
                return IfStatement(condition=condition, then_body=body, else_body=arms[idx + 1][1],
                                   structured_condition=self._build_condition(condition))
            nested = build(idx + 1)
            return IfStatement(condition=condition, then_body=body, else_body=(nested,) if nested else (),
                               structured_condition=self._build_condition(condition))
        return (build(0) or IfStatement(condition="OTHER")), i

    def _parse_if(self, lines: list[str], start: int) -> tuple[IfStatement, int]:
        """Parse IF condition THEN ... ELSE ... END-IF."""
        line = lines[start].strip()

        # Extract condition.  A statement may sit inline on the IF line
        # (`IF A > 1 THEN DISPLAY "YES" END-IF`, or without THEN), so the
        # condition is split at the first statement verb and the remainder is
        # parsed into the THEN body instead of being swallowed as comparison
        # operands (BL-020).
        match = re.search(r"IF\s+(.+)", line, re.IGNORECASE)
        condition = match.group(1).strip() if match else ""
        condition, inline_then = split_condition_from_inline_statements(condition)
        # THEN is a structural keyword, never part of the comparison.
        condition = re.sub(r"\s+THEN\s*$", "", condition, flags=re.IGNORECASE).strip()
        # A trailing END-IF on the same line closes this IF, not a statement.
        trailing_end_if = False
        end_if_match = re.search(r"\s+END-IF\s*\.?\s*$", inline_then, re.IGNORECASE)
        if end_if_match:
            inline_then = inline_then[: end_if_match.start()].strip()
            trailing_end_if = True

        then_body: list[Any] = []
        else_body: list[Any] = []
        if inline_then:
            inlined, unparsed = self._parse_inline_statements(inline_then)
            then_body.extend(inlined)
            for lost in unparsed:
                self._diagnostics.warning(
                    DiagnosticCode.UNSUPPORTED_CONSTRUCT,
                    f"Inline IF statement did not parse into IR: {lost[:60]}",
                    location="IF",
                )

        current_section = "then"

        # A period closes a scope opened on its own line: in
        # `IF A > 1 DISPLAY "YES".` the period ends the statement, so the IF
        # body is only what was written inline. Without this the scan below
        # would keep consuming following statements (STOP RUN) into the body.
        self_closed_by_period = bool(inline_then) and inline_then.rstrip().endswith(".")

        i = start + 1
        while i < len(lines):
            l = lines[i].strip()
            u = l.upper()

            if trailing_end_if or self_closed_by_period:
                # The IF was already closed on its own line; nothing more is in scope.
                break

            if u.startswith("ELSE"):
                current_section = "else"
                i += 1
                continue

            if u.startswith("END-IF"):
                i += 1
                break

            # Nested IF statements parse themselves through their own END-IF.
            # Treat the resulting IfStatement as one child so the outer ELSE
            # and END-IF remain scoped to this IF only.
            stmt, new_i = self._parse_statement(lines, i)
            if stmt is not None:
                if current_section == "then":
                    then_body.append(stmt)
                else:
                    else_body.append(stmt)
            i = max(new_i, i + 1)

        return IfStatement(
            condition=condition,
            then_body=tuple(then_body),
            else_body=tuple(else_body),
            structured_condition=self._build_condition(condition),
        ), i

    def _parse_perform(self, lines: list[str], start: int) -> tuple[PerformStatement, int]:
        """Parse paragraph, inline, TIMES, UNTIL, VARYING and THRU PERFORM forms."""
        line = lines[start].strip().rstrip(".")
        upper = line.upper()

        header_end = start + 1
        if re.match(r"PERFORM\s+VARYING\b", upper):
            # FROM/BY/UNTIL may continue a VARYING header on later lines.
            # Consuming them as body statements loses the stopping condition.
            while header_end < len(lines) and re.match(
                r"^(FROM|BY|UNTIL)\b", lines[header_end].strip(), re.IGNORECASE,
            ):
                line += " " + lines[header_end].strip().rstrip(".")
                header_end += 1
            upper = line.upper()

        # WITH TEST AFTER / WITH TEST BEFORE (strip before form matching)
        test_after = False
        test_m = re.search(r"\bWITH\s+TEST\s+(AFTER|BEFORE)\b", line, re.IGNORECASE)
        if test_m:
            test_after = test_m.group(1).upper() == "AFTER"
            line = re.sub(
                r"\bWITH\s+TEST\s+(?:AFTER|BEFORE)\b\s*", "", line,
                flags=re.IGNORECASE,
            ).strip()
            upper = line.upper()

        inline = upper.startswith("PERFORM UNTIL ") or upper.startswith("PERFORM VARYING ") or bool(re.match(r"PERFORM\s+\d+\s+TIMES$", upper)) or bool(re.match(r"PERFORM\s+WITH\s+TEST", upper))
        # After stripping WITH TEST, inline forms may start with PERFORM UNTIL/VARYING/TIMES
        if not inline and upper.startswith("PERFORM "):
            rest = upper[len("PERFORM "):]
            inline = (
                rest.startswith("UNTIL ")
                or rest.startswith("VARYING ")
                or bool(re.match(r"\d+\s+TIMES$", rest))
                or bool(re.match(r"\d+\s+TIMES", rest))
            )
        if inline:
            if upper.startswith("PERFORM VARYING "):
                suffix = line[len("PERFORM "):].strip()
                structured_condition = (
                    self._build_condition(line.split(" UNTIL ", 1)[1].strip())
                    if " UNTIL " in upper else None
                )
            elif " UNTIL " in upper:
                suffix = line.split(" UNTIL ", 1)[1].strip()
                structured_condition = self._build_condition(suffix)
            else:
                suffix = line[len("PERFORM "):].strip()
                structured_condition = None
                if re.search(r"\s+TIMES$", upper):
                    suffix = f"TIMES={suffix[: -len('TIMES')].strip()}"
            body = []
            i = header_end
            while i < len(lines):
                if lines[i].strip().upper().startswith("END-PERFORM"):
                    return PerformStatement(paragraph_name="", until_condition=suffix,
                                            structured_condition=structured_condition,
                                            body=tuple(body), test_after=test_after), i + 1
                stmt, new_i = self._parse_statement(lines, i)
                if stmt is not None:
                    body.append(stmt)
                i = max(new_i, i + 1)
            return PerformStatement(paragraph_name="", until_condition=suffix,
                                    structured_condition=structured_condition,
                                    body=tuple(body), test_after=test_after), i
        m = re.match(r"PERFORM\s+([\w-]+)\s+THRU\s+([\w-]+)$", line, re.IGNORECASE)
        if m:
            return PerformStatement(paragraph_name=m.group(1), thru_target=m.group(2),
                                    test_after=test_after), start + 1
        m = re.match(r"PERFORM\s+([\w-]+)\s+(.+?)\s+TIMES$", line, re.IGNORECASE)
        if m:
            return PerformStatement(paragraph_name=m.group(1),
                                    until_condition=f"TIMES={m.group(2).strip()}",
                                    test_after=test_after), start + 1
        m = re.match(r"PERFORM\s+([\w-]+)\s+VARYING\s+(.+)$", line, re.IGNORECASE)
        if m:
            suffix = "VARYING " + m.group(2).strip()
            return PerformStatement(paragraph_name=m.group(1), until_condition=suffix,
                                    test_after=test_after), start + 1
        m = re.match(r"PERFORM\s+([\w-]+)\s+UNTIL\s+(.+)$", line, re.IGNORECASE)
        if m:
            cond = m.group(2).strip()
            return PerformStatement(paragraph_name=m.group(1), until_condition=cond,
                                    structured_condition=self._build_condition(cond),
                                    test_after=test_after), start + 1
        m = re.match(r"PERFORM\s+([\w-]+)$", line, re.IGNORECASE)
        if m:
            return PerformStatement(paragraph_name=m.group(1), test_after=test_after), start + 1
        self._emit_unparsed("PERFORM", lines[start])
        return PerformStatement(paragraph_name="", test_after=test_after), start + 1

    def _parse_unstring(self, lines: list[str], start: int) -> tuple[UnstringStatement, int]:
        """Parse UNSTRING source DELIMITED BY delimiter INTO targets."""
        line = lines[start].strip()

        source_match = re.search(r"UNSTRING\s+(\S+)", line, re.IGNORECASE)
        source = source_match.group(1) if source_match else ""

        delim_match = re.search(r"DELIMITED BY\s+(\S+)", line, re.IGNORECASE)
        delimiter = delim_match.group(1).strip() if delim_match else ""

        # Parse INTO targets (may span multiple lines)
        targets: list[str] = []
        into_match = re.search(r"INTO\s+(.+)", line, re.IGNORECASE)
        if into_match:
            target_str = into_match.group(1).strip()
            # Remove END-UNSTRING if present
            target_str = re.sub(r"\s*END-UNSTRING.*", "", target_str, flags=re.IGNORECASE)
            target_str = target_str.rstrip(".")
            targets = [t.strip() for t in target_str.split() if t.strip() and t.strip() != "INTO"]

        # Check for continuation lines with more targets.  File-clause
        # headers and file scope terminators end the target list so an
        # UNSTRING body inside a file clause never swallows the clause.
        i = start + 1
        while i < len(lines):
            l = lines[i].strip()
            u = l.upper()
            if u.startswith(("END-UNSTRING", "MOVE", "IF", "WRITE")):
                break
            if u.startswith((
                "END-READ", "END-WRITE", "END-START", "END-REWRITE",
                "END-DELETE", "AT END", "NOT AT END",
                "INVALID KEY", "NOT INVALID KEY",
            )):
                break
            if l and not u.startswith("*"):
                more_targets = re.findall(r"([A-Z][\w-]*)", l.upper())
                for t in more_targets:
                    if t not in ("INTO", "END-UNSTRING", "DELIMITED"):
                        targets.append(t)
            i += 1

        return UnstringStatement(
            source=source,
            delimiter=delimiter,
            targets=tuple(targets),
        ), i

    def _parse_string(self, lines: list[str], start: int) -> tuple[StringStatement, int]:
        """Parse STRING parts INTO target."""
        line = lines[start].strip()

        # Collect STRING parts (may span multiple lines)
        parts: list[str] = []
        target = ""

        # Parse the STRING line and continuation lines
        full_text = line
        i = start + 1
        while i < len(lines):
            l = lines[i].strip()
            u = l.upper()
            if u.startswith("END-STRING"):
                i += 1
                break
            if l:
                full_text += " " + l
            i += 1

        # Extract parts between STRING and INTO
        into_match = re.search(r"INTO\s+(\S+)", full_text, re.IGNORECASE)
        if into_match:
            target = into_match.group(1).rstrip(".")

        # Extract parts: look for quoted strings and variable names
        string_match = re.search(r"STRING\s+(.+?)\s+INTO", full_text, re.IGNORECASE)
        if string_match:
            parts_str = string_match.group(1)
            # Parse individual parts (quoted strings and variable names)
            for token in re.findall(r'"([^"]+)"|([A-Z][\w-]*)', parts_str, re.IGNORECASE):
                if token[0]:
                    parts.append(f'"{token[0]}"')
                elif token[1] and token[1].upper() not in ("DELIMITED", "BY", "SIZE", "SPACE", "SPACES"):
                    parts.append(token[1])

        return StringStatement(parts=tuple(parts), target=target), i

    def _parse_display(self, lines: list[str], start: int) -> tuple[DisplayStatement, int]:
        """Parse DISPLAY parts UPON destination.

        Continuation lines are only consumed while the statement is open.
        A DISPLAY that already ends with '.' is complete on that line —
        otherwise the following CALL/PERFORM/EVALUATE would be swallowed.
        """
        line = lines[start].strip()
        upper = line.upper()

        destination = "STDOUT"
        if "UPON STDERR" in upper:
            destination = "STDERR"

        # Extract parts
        parts_match = re.search(r"DISPLAY\s+(.+?)(?:\s+UPON|$)", line, re.IGNORECASE)
        parts: list[str] = []
        if parts_match:
            parts_str = parts_match.group(1).strip()
            for token in re.findall(r'"([^"]+)"|\'([^\']+)\'|([A-Z][\w-]*)', parts_str, re.IGNORECASE):
                if token[0]:
                    parts.append(f'"{token[0]}"')
                elif token[1]:
                    parts.append(f"'{token[1]}'")
                elif token[2]:
                    parts.append(token[2])

        # Statement already terminated on the opening line — do not continue.
        if line.endswith("."):
            return DisplayStatement(parts=tuple(parts), destination=destination), start + 1

        # Keywords that open a new statement (or close a scope) — never
        # DISPLAY continuation. Missing CALL/PERFORM/EVALUATE here was the
        # root cause of swallowed CALL statements.  File-clause headers
        # (AT END / INVALID KEY and their NOT-forms) are included so a
        # DISPLAY body inside a file clause never swallows the next clause:
        # without this, `AT END DISPLAY "EOF"` followed by `INVALID KEY`
        # loses the header (and the body) with no diagnostic.
        break_prefixes = (
            "END-", "ELSE", "IF", "MOVE", "DISPLAY", "WRITE", "STOP RUN",
            "CLOSE", "GO TO", "CALL", "PERFORM", "EVALUATE", "ADD",
            "SUBTRACT", "MULTIPLY", "DIVIDE", "COMPUTE", "READ", "OPEN",
            "STRING", "UNSTRING", "SET", "INITIALIZE", "WHEN",
            "AT END", "NOT AT END", "INVALID KEY", "NOT INVALID KEY",
            "START", "REWRITE", "DELETE",
        )

        i = start + 1
        while i < len(lines):
            l = lines[i].strip()
            u = l.upper()
            if u.startswith(("UPON STDERR", "UPON STDOUT")):
                destination = "STDERR" if "STDERR" in u else "STDOUT"
                i += 1
                continue
            if u.startswith(break_prefixes):
                break
            if l and not u.startswith("*") and not u.startswith("END-"):
                for token in re.findall(r'"([^"]+)"|\'([^\']+)\'|([A-Z][\w-]*)', l, re.IGNORECASE):
                    if token[0]:
                        parts.append(f'"{token[0]}"')
                    elif token[1]:
                        parts.append(f"'{token[1]}'")
                    elif token[2]:
                        parts.append(token[2])
            if l.endswith("."):
                i += 1
                break
            i += 1

        return DisplayStatement(parts=tuple(parts), destination=destination), i

    def _parse_goto(self, lines: list[str], start: int) -> tuple[GoToStatement, int]:
        """Parse GO TO paragraph-name."""
        line = lines[start].strip()

        match = re.search(r"GO\s+TO\s+(\S+)", line, re.IGNORECASE)
        target = match.group(1).rstrip(".") if match else ""

        return GoToStatement(target=target), start + 1

    def _extract_threshold_rules(self, lines: list[str]) -> list[ThresholdRule]:
        """Extract numeric threshold rules from IF conditions.

        Scans for patterns like ``IF amount < 500`` and extracts the
        field name, operator, and numeric value as a ThresholdRule.
        """
        rules: list[ThresholdRule] = []
        seen: set[str] = set()

        for line in lines:
            upper = line.upper().strip()
            if not upper.startswith("IF "):
                continue

            # Match: IF <field> <op> <number>
            match = re.search(
                r"IF\s+(\S+)\s*(<=|>=|<|>|=)\s*(\d+)",
                line, re.IGNORECASE,
            )
            if match:
                field_name = match.group(1).rstrip(".")
                operator = match.group(2)
                value = int(match.group(3))
                key = f"{field_name}:{operator}:{value}"
                if key not in seen:
                    seen.add(key)
                    rules.append(ThresholdRule(
                        field_name=field_name,
                        operator=operator,
                        value=value,
                    ))

        return rules

    def _extract_status_codes(self, lines: list[str]) -> list[StatusCodeMapping]:
        """Extract status code definitions from IF/MOVE patterns.

        Looks for patterns like:
            IF FIELD = 'X'
                MOVE 'LABEL' TO TARGET

        Finds IF conditions that test a field against a single-character
        code and are followed by a MOVE to any target variable.
        """
        codes: list[StatusCodeMapping] = []
        seen: set[str] = set()

        for i, line in enumerate(lines):
            upper = line.upper().strip()
            if not upper.startswith("IF "):
                continue

            # Match: IF <field> = '<single-char-code>'
            match = re.search(
                r"IF\s+(\S+)\s*=\s*'([^']{1})'",
                line, re.IGNORECASE,
            )
            if not match:
                continue

            field_name = match.group(1)
            code = match.group(2)

            if code in seen:
                continue

            # The first statement must assign the outcome. Searching ahead
            # can misattribute a nested branch's outcome to this condition.
            label = None
            for j in range(i + 1, min(i + 2, len(lines))):
                move_match = re.search(
                    r"MOVE\s+'([^']+)'\s+TO\s+(\S+)",
                    lines[j], re.IGNORECASE,
                )
                if move_match:
                    label = move_match.group(1)
                    break

            if label is None:
                continue

            seen.add(code)
            codes.append(StatusCodeMapping(
                code=code,
                label=label,
                field_name=field_name,
            ))

        return codes

    def _extract_primary_threshold(self, lines: list[str]) -> ThresholdRule | None:
        """Extract the primary numeric threshold from IF conditions.

        Looks for patterns like:
            IF WS-CLAIM-AMOUNT < 500
        """
        for line in lines:
            match = re.search(
                r"IF\s+(\S+)\s*(<|>)\s*(\d+)",
                line, re.IGNORECASE,
            )
            if match:
                return ThresholdRule(
                    field_name=match.group(1),
                    operator=match.group(2),
                    value=int(match.group(3)),
                )
        return None

    def _extract_report_header(self, lines: list[str]) -> str:
        """Extract the report header from a header VALUE clause.

        Handles multi-line VALUE clauses like:
            01  WS-HEADER  PIC X(80) VALUE
                "CLAIM   PATIENT      ..."
        """
        for i, line in enumerate(lines):
            upper = line.upper()
            if "VALUE" in upper and "PIC X" in upper:
                # Check if the string is on the same line
                match = re.search(r'"([^"]+)"', line)
                if match:
                    return match.group(1)
                # Check the next line
                if i + 1 < len(lines):
                    match = re.search(r'"([^"]+)"', lines[i + 1])
                    if match:
                        return match.group(1)
        return ""

    def _extract_output_fields(self, lines: list[str], record_name: str) -> list[OutputFieldDefinition]:
        """Extract output field definitions from STRING statements.

        Looks for STRING ... INTO <record_name> patterns.
        """
        fields: list[OutputFieldDefinition] = []
        in_string = False
        current_parts: list[str] = []

        for line in lines:
            upper = line.upper().strip()
            if "STRING " in upper and f"INTO {record_name}" in upper:
                in_string = True
                current_parts = []
                # Extract parts from the same line
                parts_match = re.search(r"STRING\s+(.+?)\s+INTO", line, re.IGNORECASE)
                if parts_match:
                    tokens = re.findall(r'"([^"]+)"|(\S+)', parts_match.group(1))
                    for t in tokens:
                        current_parts.append(t[0] if t[0] else t[1])
                continue

            if in_string:
                if "END-STRING" in upper:
                    in_string = False
                    # Process collected parts into field definitions
                    i = 0
                    while i < len(current_parts):
                        part = current_parts[i]
                        if part.startswith('"') and part.endswith('"'):
                            # Delimiter
                            delim = part.strip('"')
                            if delim == "|":
                                fields.append(OutputFieldDefinition(
                                    field_name=f"delim_{len(fields)}",
                                    delimiter="|",
                                ))
                            elif delim == " ":
                                fields.append(OutputFieldDefinition(
                                    field_name=f"space_{len(fields)}",
                                    delimiter=" ",
                                ))
                        else:
                            # Field name
                            fields.append(OutputFieldDefinition(
                                field_name=part,
                                delimiter="FIELD",
                            ))
                        i += 1
                    current_parts = []
                else:
                    # Collect parts
                    tokens = re.findall(r'"([^"]+)"|(\S+)', line.strip())
                    for t in tokens:
                        current_parts.append(t[0] if t[0] else t[1])

        return fields

    def _extract_summary_fields(self, lines: list[str]) -> list[str]:
        """Extract DISPLAY summary field labels.

        Looks for patterns like:
            DISPLAY "TOTAL_CLAIMS=" WS-CLAIM-COUNT
        """
        fields: list[str] = []
        for line in lines:
            match = re.search(
                r'DISPLAY\s+"([^"]+)"',
                line, re.IGNORECASE,
            )
            if match:
                label = match.group(1)
                if "=" in label:
                    fields.append(label.rstrip("="))
        return fields

    def _extract_match_outcome_labels(self, lines: list[str]) -> list[str]:
        """Extract match outcome labels from COBOL MOVE statements.

        Finds MOVE 'LABEL' TO <target> patterns that occur after a lookup
        section (SEARCH, PERFORM ... VARYING).
        These labels represent lookup outcomes like FOUND, NOT_FOUND, MATCHED, UNMATCHED.
        Handles continuation lines where MOVE and TO are on separate lines.
        """
        labels: list[str] = []
        in_lookup_section = False

        # First pass: join continuation lines
        joined = []
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if re.search(r"MOVE\s+'[^']+'\s*$", line, re.IGNORECASE):
                if i + 1 < len(lines):
                    next_line = lines[i + 1].strip()
                    if re.search(r"TO\s+\S+", next_line, re.IGNORECASE):
                        joined.append(line + " " + next_line)
                        i += 2
                        continue
            joined.append(line)
            i += 1

        for line in joined:
            upper = line.upper().strip()
            # Detect start of lookup section (SEARCH, PERFORM ... VARYING)
            if ("SEARCH " in upper or
                "PERFORM " in upper and ("VARYING" in upper or "FIND-" in upper)):
                in_lookup_section = True
                continue

            if not in_lookup_section:
                continue

            match = re.search(
                r"MOVE\s+'([^']+)'\s+TO\s+(\S+)",
                line, re.IGNORECASE,
            )
            if match:
                label = match.group(1)
                # Filter out single-character codes (e.g. 'Y', 'N' are flags, not labels)
                if len(label) > 1 and label not in labels:
                    labels.append(label)
        return labels

    def _find_record_name(self, lines: list[str], prefix: str) -> str | None:
        """Find a record name from STRING ... INTO statements with a given prefix.

        Searches for STRING ... INTO <record> patterns where the record name
        contains the given prefix (case-insensitive).
        """
        prefix_upper = prefix.upper()
        for line in lines:
            upper = line.upper()
            if "STRING " in upper and "INTO " in upper:
                match = re.search(r"INTO\s+(\S+)", line, re.IGNORECASE)
                if match:
                    record_name = match.group(1).rstrip(".")
                    if prefix_upper in record_name.upper():
                        return record_name
        return None

    def _extract_record_format(self, lines: list[str], record_name: str) -> RecordFormat | None:
        """Extract record format from STRING ... INTO <record_name> statements.

        Parses the STRING statement to determine field ordering, delimiters,
        and field names. Handles multi-line STRING statements where STRING
        and INTO are on different lines.
        """
        # First pass: join multi-line STRING blocks into single logical lines
        joined_lines: list[str] = []
        i = 0
        while i < len(lines):
            stripped = lines[i].strip()
            if stripped.upper().startswith("STRING"):
                if "END-STRING" in stripped.upper():
                    joined_lines.append(stripped)
                    i += 1
                    continue
                # Collect entire STRING ... END-STRING block
                block = stripped
                i += 1
                while i < len(lines) and "END-STRING" not in block.upper():
                    next_stripped = lines[i].strip()
                    block += " " + next_stripped
                    if "END-STRING" in next_stripped.upper():
                        break
                    i += 1
                joined_lines.append(block)
            else:
                joined_lines.append(stripped)
            i += 1

        for line in joined_lines:
            if "STRING " not in line.upper() or "INTO " + record_name.upper() not in line.upper():
                continue

            # Extract everything between STRING and INTO <record_name>
            m = re.search(
                r"STRING\s+(.+?)\s+INTO\s+" + record_name,
                line, re.IGNORECASE,
            )
            if not m:
                continue

            parts_str = m.group(1)
            fields: list[OutputFieldDefinition] = []

            # Parse field list from STRING statement.
            # COBOL STRING pattern: field DELIMITED BY SIZE field DELIMITED BY SIZE ...
            # DELIMITED/BY/SIZE are syntax keywords — skip them.
            # Everything else is a field or literal delimiter value.
            tokens = re.findall(r'"[^"]*"|\S+', parts_str)
            for token in tokens:
                if not token:
                    continue
                upper = token.upper()
                if upper in ("DELIMITED", "BY", "SIZE", "STRING", "INTO", "END-STRING"):
                    continue
                # Skip bare quote characters
                if token in ('"', "'"):
                    continue
                # Everything else is a field name or literal value
                fields.append(OutputFieldDefinition(
                    field_name=token,
                    delimiter="FIELD",
                ))

            if fields:
                return RecordFormat(
                    record_name=record_name,
                    fields=tuple(fields),
                )

        return None

    def _extract_output_formats(self, lines: list[str]) -> list[OutputFormat]:
        """Extract all output record formats from STRING ... INTO statements.

        Finds ALL STRING INTO <record> patterns and extracts their formats.
        No domain-specific prefix detection — purely pattern-based.
        """
        # Find all STRING INTO record names
        record_names: list[str] = []
        block = ""
        for line in lines:
            upper = line.upper()
            if upper.strip().startswith("STRING "):
                block = line
            elif block:
                block += " " + line
            if block:
                match = re.search(r"INTO\s+(\S+)", block, re.IGNORECASE)
                if match:
                    name = match.group(1).rstrip(".")
                    if name not in record_names:
                        record_names.append(name)
                    block = ""

        # Extract record format for each found record
        formats: list[OutputFormat] = []
        for name in record_names:
            fmt = self._extract_record_format(lines, name)
            if fmt:
                formats.append(OutputFormat(record_format=fmt))

        return formats

    def _extract_lookup_operation(self, lines: list[str]) -> LookupOperation | None:
        """Extract table lookup semantics from PERFORM + IF patterns.

        Looks for any PERFORM paragraph pattern where the paragraph contains:
            IF table-field(idx) = search-field
                MOVE 'Y' TO match-found
                MOVE table-amount(idx) TO match-amount
            ADD 1 TO idx
        """
        # Find all PERFORM paragraph names
        perform_targets = []
        for i, line in enumerate(lines):
            match = re.search(r"PERFORM\s+(\S+)", line.strip(), re.IGNORECASE)
            if match:
                perform_targets.append(match.group(1).rstrip("."))

        # For each PERFORM target, check if the paragraph has a table search pattern
        for target in perform_targets:
            # Find the paragraph
            in_paragraph = False
            paragraph_lines: list[str] = []
            for line in lines:
                stripped = line.strip()
                if stripped.upper().startswith(target.upper()) and "." in stripped:
                    in_paragraph = True
                    continue
                if in_paragraph:
                    # End of paragraph: non-indented line that isn't a continuation
                    if (stripped and not stripped.startswith(" ")
                        and not stripped.upper().startswith("IF")
                        and not stripped.upper().startswith("MOVE")
                        and not stripped.upper().startswith("ADD")
                        and not stripped.upper().startswith("END")
                        and not stripped.upper().startswith("TO")
                        and not stripped.upper().startswith("OR")
                        and not stripped.upper().startswith("WS-")):
                        break
                    paragraph_lines.append(stripped)

            # Join continuation lines
            joined_lines: list[str] = []
            for cline in paragraph_lines:
                upper = cline.upper()
                if (joined_lines
                    and (upper.startswith("TO ") or upper == "TO")
                    and not joined_lines[-1].rstrip().endswith(".")):
                    joined_lines[-1] += " " + cline
                else:
                    joined_lines.append(cline)

            table_field = ""
            search_field = ""
            amount_field = ""
            match_found = ""
            match_amount = ""
            index_field = ""
            count_field = ""

            for line in joined_lines:
                # IF table-field(idx) = search-field
                m = re.search(r"IF\s+(\S+)\((\S+)\)\s*=\s*(\S+)", line, re.IGNORECASE)
                if m:
                    table_field = m.group(1)
                    index_field = m.group(2)
                    search_field = m.group(3)
                # MOVE 'Y' TO match-found
                m = re.search(r"MOVE\s+'([^']+)'\s+TO\s+(\S+)", line, re.IGNORECASE)
                if m:
                    match_found = m.group(2)
                # MOVE table-amount(idx) TO match-amount
                m = re.search(r"MOVE\s+(\S+)\(\S+\)\s+TO\s+(\S+)", line, re.IGNORECASE)
                if m:
                    amount_field = m.group(1)
                    match_amount = m.group(2)
                # ADD 1 TO idx
                m = re.search(r"ADD\s+1\s+TO\s+(\S+?)[.\s]", line, re.IGNORECASE)
                if m:
                    index_field = m.group(1)

            if table_field and search_field:
                # Find count field from WORKING-STORAGE
                for line in lines:
                    m = re.search(r"01\s+(WS-\S*-COUNT)\s+PIC", line, re.IGNORECASE)
                    if m:
                        count_field = m.group(1)
                        break

                return LookupOperation(
                    table_field=table_field,
                    search_field=search_field,
                    amount_field=amount_field,
                    match_found_field=match_found,
                    match_amount_field=match_amount,
                    index_field=index_field,
                    count_field=count_field,
                )

        return None

    def _extract_input_record_mappings(
        self,
        lines: list[str],
        file_section_map: dict[str, FileDefinition],
    ) -> list[InputRecordMapping]:
        """Extract input record mappings from UNSTRING statements.

        For each UNSTRING source DELIMITED BY delimiter INTO field1 field2 ...,
        creates an InputRecordMapping that links the record name to the file name
        and captures the field ordering and delimiter.

        The record→file linkage comes from FILE SECTION:
            FD CLAIMS-FILE.
            01 CLAIM-REC PIC X(60).
        """
        # Build reverse map: record_name → file_name
        record_to_file: dict[str, str] = {}
        for fd in file_section_map.values():
            if fd.record_name:
                record_to_file[fd.record_name] = fd.name

        # Find all UNSTRING statements
        mappings: list[InputRecordMapping] = []
        for i, line in enumerate(lines):
            stripped = line.strip()
            upper = stripped.upper()
            if not upper.startswith("UNSTRING "):
                continue

            # Extract source record name
            source_match = re.search(r"UNSTRING\s+(\S+)", stripped, re.IGNORECASE)
            if not source_match:
                continue
            source_record = source_match.group(1)

            # Extract delimiter
            delim_match = re.search(r"DELIMITED BY\s+(\S+)", stripped, re.IGNORECASE)
            if not delim_match:
                continue
            delimiter = delim_match.group(1).strip().strip("'\"")

            # Extract INTO targets (may span multiple lines)
            targets: list[str] = []
            into_match = re.search(r"INTO\s+(.+)", stripped, re.IGNORECASE)
            if into_match:
                target_str = into_match.group(1).strip()
                target_str = re.sub(r"\s*END-UNSTRING.*", "", target_str, flags=re.IGNORECASE)
                target_str = target_str.rstrip(".")
                targets = [t.strip() for t in target_str.split() if t.strip() and t.strip() != "INTO"]

            # Check continuation lines
            j = i + 1
            while j < len(lines):
                next_line = lines[j].strip()
                next_upper = next_line.upper()
                if next_upper.startswith(("END-UNSTRING", "MOVE", "IF", "WRITE", "ADD", "CLOSE")):
                    break
                if next_line and not next_upper.startswith("*"):
                    more_targets = re.findall(r"([A-Z][\w-]*)", next_line.upper())
                    for t in more_targets:
                        if t not in ("INTO", "END-UNSTRING", "DELIMITED", "BY"):
                            targets.append(t)
                j += 1

            # Look up file name from record name
            file_name = record_to_file.get(source_record, "")

            if targets:
                mappings.append(InputRecordMapping(
                    record_name=source_record,
                    file_name=file_name,
                    delimiter=delimiter,
                    fields=tuple(targets),
                ))

        return mappings

    # -----------------------------------------------------------------------
    # Structured expression and condition builders
    # -----------------------------------------------------------------------

    def _build_expression(self, text: str) -> Expression:
        """Build a structured Expression from a COBOL expression text.

        Handles:
        - Numeric literals: 42, 3.14, -100
        - String literals: 'HELLO', "WORLD"
        - Figurative constants: ZERO, SPACES, HIGH-VALUE, ALL "x"
        - Field references: CUSTOMER-ID, WS-TOTAL
        - Binary expressions: A + B, X * Y
        - Unary expressions: NOT flag, -amount

        This is a simplified parser for the demonstrated subset.
        """
        text = text.strip()

        # Check for string literal
        if (text.startswith("'") and text.endswith("'")) or \
           (text.startswith('"') and text.endswith('"')):
            return Literal(value=text[1:-1], is_numeric=False)

        # Figurative constants are reserved *words* with a fixed value, not
        # variables.  Resolving them here keeps a `MOVE SPACES TO X` from
        # becoming a FieldReference named SPACES (which maps to an undeclared
        # Java identifier, i.e. non-compiling, silently-lost output).
        figurative = parse_figurative_constant(text)
        if figurative is not None:
            kind, _fill = figurative
            return FigurativeConstant(kind=kind, text=text)

        # BL-024: an intrinsic call (`FUNCTION MIN(1, 2)`) is not a variable.
        # Falling through to FieldReference produced the impossible identifier
        # `FUNCTION MIN(1, 2)`, which maps to an undeclared Java variable.  No
        # intrinsic is mapped by the deterministic lane, so fail closed with an
        # explicit diagnostic instead of modelling it as a field (BL-018's
        # defect class).
        intrinsic = _re_intrinsic.match(text)
        if intrinsic is not None:
            name = intrinsic.group(1).upper()
            self._diagnostics.warning(
                DiagnosticCode.UNSUPPORTED_CONSTRUCT,
                f"Intrinsic function {name} is not implemented by the "
                "deterministic mapper",
                location=name,
            )
            return IntrinsicCall(name=name, arguments=text)

        # BL-023: `**` is exponentiation, not two multiplications.  Treating it
        # as two `*` operators produced `2 * <empty field> * 3` - a wrong
        # numeric result with no diagnostic (Master README Section 18).  No
        # exponentiation mapping is certified, so fail closed explicitly.
        if "**" in self._mask_quoted(text):
            self._diagnostics.warning(
                DiagnosticCode.UNSUPPORTED_CONSTRUCT,
                "Exponentiation (**) is not implemented by the deterministic "
                "mapper",
                location="COMPUTE",
            )
            return IntrinsicCall(name="**", arguments=text)

        # Check for numeric literal
        try:
            float(text)
            return Literal(value=text, is_numeric=True, is_signed=text.startswith('-'))
        except ValueError:
            pass

        # Check for unary NOT
        if text.upper().startswith("NOT "):
            operand = self._build_expression(text[4:])
            return UnaryExpression(operator="NOT", operand=operand)

        # Check for unary minus
        if text.startswith("-") and len(text) > 1:
            operand = self._build_expression(text[1:])
            return UnaryExpression(operator="-", operand=operand)

        # Preserve COBOL arithmetic precedence and left associativity.
        for ops in [("AND", "OR"), ("<>", ">=", "<=", "=", ">", "<"),
                    ("+", "-"), ("*", "/")]:
            pos = self._find_binary_operator_from_right(text, ops)
            if pos is not None:
                op = next(candidate for candidate in ops
                           if text[pos:pos + len(candidate)].upper() == candidate.upper())
                left = self._build_expression(text[:pos])
                right = self._build_expression(text[pos + len(op):])
                return BinaryExpression(left=left, operator=op, right=right)

        # Default: field reference
        return FieldReference(name=text)

    def _find_binary_operator_from_right(
        self, text: str, operators: tuple[str, ...],
    ) -> int | None:
        """Find the rightmost top-level binary operator.

        Rightmost splitting makes operators left-associative while recursive
        descent preserves normal precedence between operator groups.
        """
        depth = 0
        i = len(text) - 1
        while i >= 0:
            if text[i] == ")":
                depth += 1
            elif text[i] == "(":
                depth -= 1
            elif depth == 0:
                for op in operators:
                    start = i - len(op) + 1
                    if start < 0 or text[start:i + 1].upper() != op.upper():
                        continue
                    before = text[start - 1] if start > 0 else ""
                    after = text[i + 1] if i + 1 < len(text) else ""
                    if op == "-" and (not before or before in "+-*/(=<>"):
                        continue
                    if not before.isalnum() and not after.isalnum():
                        return start
            i -= 1
        return None

    def _find_binary_operator(self, text: str, op: str) -> int | None:
        """Find the position of a binary operator in text, respecting parentheses."""
        depth = 0
        i = 0
        while i < len(text):
            if text[i] == '(':
                depth += 1
            elif text[i] == ')':
                depth -= 1
            elif depth == 0:
                # Check for operator at this position
                if text[i:i + len(op)].upper() == op.upper():
                    # Make sure it's not part of a longer word
                    before_ok = (i == 0 or not text[i - 1].isalnum())
                    after_pos = i + len(op)
                    after_ok = (after_pos >= len(text) or not text[after_pos].isalnum())
                    if before_ok and after_ok:
                        return i
            i += 1
        return None

    def _build_condition(self, text: str) -> Condition:
        """Build a structured Condition from a COBOL condition text.

        Handles:
        - Comparisons: A > B, X = 'Y'
        - Logical operators: A AND B, X OR Y
        - Negation: NOT (A > B)
        - Parenthesized conditions: (A > B) AND (C < D)
        """
        text = text.strip()

        # Remove outer parentheses if they match
        if text.startswith("(") and text.endswith(")"):
            depth = 0
            matching = True
            for i, c in enumerate(text):
                if c == '(':
                    depth += 1
                elif c == ')':
                    depth -= 1
                if depth == 0 and i < len(text) - 1:
                    matching = False
                    break
            if matching:
                return self._build_condition(text[1:-1])

        # Check for NOT
        if text.upper().startswith("NOT "):
            inner = self._build_condition(text[4:])
            return NegatedCondition(condition=inner)

        # Check for AND/OR (at top level)
        for op in ["AND", "OR"]:
            pos = self._find_binary_operator(text, op)
            if pos is not None:
                left = self._build_condition(text[:pos])
                right = self._build_condition(text[pos + len(op):])
                return LogicalCondition(left=left, operator=op, right=right)

        # Check for comparison operators
        for op in ["<>", ">=", "<=", "=", ">", "<"]:
            pos = self._find_binary_operator(text, op)
            if pos is not None:
                left_expr = self._build_expression(text[:pos])
                right_expr = self._build_expression(text[pos + len(op):])
                return Comparison(left=left_expr, operator=op, right=right_expr)

        # Default: treat as boolean field reference
        return BooleanCondition(field=FieldReference(name=text))
