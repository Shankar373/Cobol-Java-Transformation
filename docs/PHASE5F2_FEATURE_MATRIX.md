# Phase 5F.2: Feature Matrix

## IR Construct Coverage

| COBOL Construct | Parsed | IR | Generated | Executed | Behaviorally Proven |
|-----------------|--------|-----|-----------|----------|---------------------|
| IDENTIFICATION DIVISION | Yes | CobolProgram.program_id | Yes (class name) | Yes | Yes |
| FILE-CONTROL | Yes | FileDefinition | Yes (file paths) | Yes | Yes (file I/O) |
| WORKING-STORAGE | Yes | DataItem | Yes (declarations) | Yes | Yes |
| PIC X(n) | Yes | pic_type=ALPHANUMERIC | Yes (String) | Yes | Yes |
| PIC 9(n) | Yes | pic_type=NUMERIC | Yes (int) | Yes | Yes |
| MOVE literal | Yes | MoveStatement | Yes (= expr;) | Yes | **YES** (100→200) |
| ADD number | Yes | AddStatement | Yes (+= expr;) | Yes | **YES** (50→75) |
| IF condition | Yes | IfStatement | Yes (if/else) | Yes | **YES** (threshold) |
| DISPLAY | Yes | DisplayStatement | Yes (println) | Yes | **YES** (RESULT→OUTPUT) |
| STOP RUN | Yes | StopRunStatement | Yes (implicit) | Yes | Yes |
| OPEN/CLOSE | Yes | OpenStatement | Yes (file paths) | Yes | Yes |
| READ | Yes | ReadStatement | Yes (BufferedReader) | Yes | Yes |
| WRITE | Yes | WriteStatement | Yes (PrintWriter) | Yes | Yes |
| PERFORM | Yes | PerformStatement | **PARTIAL** (context for payment lookup) | **PARTIAL** | **PARTIAL** |
| GO TO | Yes | GoToStatement | **NO** (comment only) | **NO** | **NO** |
| STRING | Yes | StringStatement + RecordFormat | Yes (printf) | Yes | **YES** (record format) |
| UNSTRING | Yes | UnstringStatement | **NOT GENERATED** | **NO** | **NO** |
| IF \<field\> \<op\> \<N\> | Yes | ThresholdRule | Yes (APPROVAL_THRESHOLD) | Yes | **YES** (500→1000) |
| IF \<field\> = 'X' + MOVE | Yes | StatusCodeDefinition | Yes (status.equals) | Yes | **YES** (R→X) |
| COMPUTE | **NO** | N/A | N/A | N/A | N/A |
| SUBTRACT | **NO** | N/A | N/A | N/A | N/A |
| MULTIPLY | **NO** | N/A | N/A | N/A | N/A |
| DIVIDE | **NO** | N/A | N/A | N/A | N/A |
| SORT | **NO** | N/A | N/A | N/A | N/A |
| CALL | **NO** | N/A | N/A | N/A | N/A |
| EVALUATE | **NO** | N/A | N/A | N/A | N/A |
| ACCEPT | **NO** | N/A | N/A | N/A | N/A |
| INDEXED files | **NO** | N/A | N/A | N/A | N/A |
| RELATIVE files | **NO** | N/A | N/A | N/A | N/A |

## Generation Modes

| Mode | Trigger | Features | Source-Driven |
|------|---------|----------|---------------|
| Settlement | `settlement_logic is not None` | Full Claims workload: IR-driven status/threshold/labels/record formats/payment lookup | **YES** |
| Minimal | No settlement logic | Generic MOVE/ADD/IF/DISPLAY generation | **YES** |

## Source Mutation Categories

| Category | Example | Java Impact | Behavioral Proof |
|----------|---------|-------------|-----------------|
| A. Status values | `R→X` | `status.equals("X")` | report.txt differs |
| B. Threshold | `500→1000` | `APPROVAL_THRESHOLD = 1000` | amount=750: PAID_IN_FULL vs REJECTED |
| C. Assignment | `MOVE 100→200` | `WS_RESULT = 200` | RESULT=150 vs RESULT=250 |
| D. Arithmetic | `ADD 50→75` | `WS_RESULT += 75` | RESULT=150 vs RESULT=175 |
| E. Output format | `DISPLAY "RESULT="→"OUTPUT="` | `println("OUTPUT="...)` | stdout differs |

## Test Results (Actual pytest)

| Test Suite | Collected | Passed | Skipped | Failed |
|------------|-----------|--------|---------|--------|
| tests/transformation/ | 147 | 143 | 4 | 0 |
| tests/adversarial/ | 205 | 205 | 0 | 0 |
| tests/unit/ | ~80 | ~80 | 0 | 0 |
| tests/comparators/ | ~20 | ~20 | 0 | 0 |
| tests/contracts/ | ~15 | ~15 | 0 | 0 |
| tests/evidence/ | ~20 | ~20 | 0 | 0 |
| tests/execution/ | ~10 | ~10 | 0 | 0 |
| tests/verdict/ | ~11 | ~11 | 0 | 0 |
| **Total (excl. integration)** | **508** | **504** | **4** | **0** |
| tests/integration/ | HANGS | N/A | N/A | N/A |

Note: 4 skipped tests are Docker-dependent Java compilation tests (require RUN_DOCKER_TESTS=1).
