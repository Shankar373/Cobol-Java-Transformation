# Phase 5E — COBOL → Native Java Transformation Vertical Slice

**Date:** 2026-09-15
**Status:** COMPLETE

---

## 1. Selected Workload

**Claims Settlement Processor** (`fixtures/workload-claims/`)

- COBOL source: `CLAIMS.cob` (253 lines)
- Inputs: `claims.dat` (10 records), `payments.dat` (5 records)
- Outputs: `report.txt`, `settlement.dat`, stdout summary, stderr rejections
- Existing Java candidate: `Claims.java` (152 lines) — reference implementation
- 11 mutated variants for negative testing

---

## 2. COBOL Features Supported (Claims Settlement)

| Feature | Status | Used In |
|---|---|---|
| IDENTIFICATION DIVISION | ✅ | Program header |
| ENVIRONMENT DIVISION | ✅ | File-control declarations |
| DATA DIVISION | ✅ | File/working-storage sections |
| FILE SECTION (FD) | ✅ | 4 file definitions |
| WORKING-STORAGE SECTION | ✅ | Variables, tables |
| PIC X(n) | ✅ | Alphanumeric fields |
| PIC 9(n) | ✅ | Numeric fields |
| OCCURS clause | ✅ | Payment table |
| PROCEDURE DIVISION | ✅ | Main logic |
| OPEN INPUT/OUTPUT | ✅ | 4 file opens |
| READ ... AT END | ✅ | Claims/payments reading |
| WRITE | ✅ | Report/settlement writing |
| MOVE | ✅ | Variable assignment |
| ADD | ✅ | Counter/total accumulation |
| IF ... ELSE ... END-IF | ✅ | Business rules |
| PERFORM ... UNTIL | ✅ | Loop control |
| PERFORM paragraph | ✅ | Subroutine calls |
| STRING ... INTO | ✅ | Output formatting |
| UNSTRING ... INTO | ✅ | Input parsing |
| DISPLAY ... UPON STDERR | ✅ | Error logging |
| GO TO | ✅ | Loop back |
| STOP RUN | ✅ | Program termination |
| DELIMITED BY SIZE | ✅ | String operations |
| SPACES | ✅ | Blank initialization |
| SUBSCRIPTING | ✅ | Table access |

---

## 3. Transformation Architecture

```
engine/transformation/
├── __init__.py              # Package init
├── cobol_parser.py          # COBOL source → IR
├── ir.py                    # Intermediate representation dataclasses
├── java_generator.py        # IR → Java source
└── producer.py              # TransformationProducer facade
```

### Data Flow

```
COBOL source (.cob file)
        ↓
CobolParser.parse(source_text)
        ↓
CobolProgram IR
        ↓
JavaGenerator.generate(program_ir)
        ↓
Java source tree (.java files)
        ↓
ProducerManifest
```

---

## 4. IR Design

### CobolProgram
- program_id: str
- file_definitions: list[FileDefinition]
- working_storage: list[DataItem]
- paragraphs: list[Paragraph]

### FileDefinition
- name: str (e.g., "CLAIMS-FILE")
- file_path: str (e.g., "/workspace/input/claims.dat")
- record_name: str
- record_length: int

### DataItem
- name: str (e.g., "WS-EOF-CLAIMS")
- pic_clause: str (e.g., "X(1)")
- pic_type: str ("ALPHANUMERIC" | "NUMERIC")
- pic_length: int
- value: str | None
- occurs: int | None
- children: list[DataItem] | None

### Paragraph
- name: str (e.g., "MAIN-LOGIC")
- statements: list[Statement]

### Statement types
- OpenStatement (mode, file_ref)
- ReadStatement (file_ref, at_end_body, not_at_end_body)
- WriteStatement (record_ref, file_ref)
- MoveStatement (source, target)
- AddStatement (source, target)
- IfStatement (condition, then_body, else_body)
- PerformStatement (paragraph_ref, until_condition)
- UnstringStatement (source, delimited_by, into_targets)
- StringStatement (parts, into_target)
- DisplayStatement (parts, destination)
- GoToStatement (target_paragraph)
- StopRunStatement

---

## 5. Java Generation

The generator produces a single `Claims.java` file with:
- `main()` method
- File I/O using BufferedReader/PrintWriter
- Business logic matching COBOL control flow
- Helper methods for padding, string operations
- No COBOL runtime dependency

---

## 6. Native Java Proof

Generated Java must:
1. Read `/workspace/input/claims.dat` and `/workspace/input/payments.dat`
2. Process claims with business rules
3. Write `/workspace/output/report.txt` and `/workspace/output/settlement.dat`
4. Print summary to stdout
5. Log rejections to stderr
6. Exit with status 0
7. Use only standard Java libraries
8. No subprocess/COBOL invocation

---

## 7. Supported Feature Matrix

| COBOL Construct | IR Node | Java Equivalent |
|---|---|---|
| FD declaration | FileDefinition | BufferedReader field |
| PIC X(n) | DataItem(ALPHANUMERIC) | String |
| PIC 9(n) | DataItem(NUMERIC) | int / String |
| OCCURS n | DataItem(occurs=n) | List/Array |
| OPEN INPUT | OpenStatement | new BufferedReader(new FileReader(...)) |
| OPEN OUTPUT | OpenStatement | new PrintWriter(new FileWriter(...)) |
| READ AT END | ReadStatement | while ((line = reader.readLine()) != null) |
| WRITE | WriteStatement | writer.println(...) |
| MOVE | MoveStatement | assignment |
| ADD | AddStatement | += operator |
| IF/ELSE | IfStatement | if/else |
| PERFORM UNTIL | PerformStatement | while loop |
| PERFORM paragraph | PerformStatement | method call |
| UNSTRING DELIMITED BY | UnstringStatement | String.split() |
| STRING INTO | StringStatement | String.format() |
| DISPLAY UPON STDERR | DisplayStatement | System.err.printf() |
| GO TO | GoToStatement | continue/break/label |
| STOP RUN | StopRunStatement | return |
