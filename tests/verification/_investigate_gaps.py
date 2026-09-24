"""Investigate multi-source SUBTRACT and DIVIDE INTO."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import re
from engine.transformation.cobol_parser import CobolParser
from engine.transformation.ir import SubtractStatement, DivideStatement

parser = CobolParser()

print("=== MULTI-SOURCE SUBTRACT ===")
line = "SUBTRACT WS-A WS-B FROM WS-C GIVING WS-D."
match = re.search(
    r"SUBTRACT\s+(.+?)\s+FROM\s+(\S+)(?:\s+GIVING\s+(\S+))?",
    line, re.IGNORECASE,
)
if match:
    print(f"  Regex: source={match.group(1)!r} from={match.group(2)!r} giving={match.group(3)!r}")
    print(f"  source captures entire 'WS-A WS-B' as single string")
    print(f"  => Parser cannot separate individual subtrahends")

# Test what happens when parsed through the pipeline
cobol = """\
>>SOURCE FORMAT FREE
IDENTIFICATION DIVISION.
PROGRAM-ID. TEST.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-A PIC 9(5) VALUE 10.
01 WS-B PIC 9(5) VALUE 5.
01 WS-C PIC 9(5) VALUE 100.
01 WS-D PIC 9(5) VALUE 0.
PROCEDURE DIVISION.
MAIN.
    SUBTRACT WS-A WS-B FROM WS-C GIVING WS-D.
    DISPLAY WS-D.
    STOP RUN.
"""
program = parser.parse(cobol)
main = next(p for p in program.paragraphs if p.name == "MAIN")
stmts = [s for s in main.statements if isinstance(s, SubtractStatement)]
if stmts:
    s = stmts[0]
    print(f"  IR: source={s.source!r} from_field={s.from_field!r} to_field={s.to_field!r}")

print()
print("=== DIVIDE INTO FORMS ===")
# Test the three INTO forms
into_forms = [
    ("DIVIDE WS-A INTO WS-B.", "INTO (no GIVING)"),
    ("DIVIDE WS-A INTO WS-B GIVING WS-C.", "INTO GIVING"),
    ("DIVIDE WS-A INTO WS-B GIVING WS-C REMAINDER WS-D.", "INTO GIVING REMAINDER"),
]
for line, label in into_forms:
    match_by = re.search(
        r"DIVIDE\s+(\S+)\s+BY\s+(\S+)\s+GIVING\s+(\S+)(?:\s+REMAINDER\s+(\S+))?",
        line, re.IGNORECASE,
    )
    match_into = re.search(
        r"DIVIDE\s+(\S+)\s+INTO\s+(\S+)(?:\s+GIVING\s+(\S+))?(?:\s+REMAINDER\s+(\S+))?",
        line, re.IGNORECASE,
    )
    print(f"  {label}:")
    print(f"    BY regex match: {match_by is not None}")
    print(f"    INTO regex match: {match_into is not None}")
    if match_into:
        print(f"    source={match_into.group(1)!r} into_divisor={match_into.group(2)!r} giving={match_into.group(3)!r} remainder={match_into.group(4)!r}")

print()
print("=== DIVIDE INTO COBOL SEMANTICS ===")
print("  DIVIDE A INTO B           => B = B / A")
print("  DIVIDE A INTO B GIVING C  => C = B / A")
print("  DIVIDE A INTO B GIVING C REMAINDER D  => C = B / A, D = B mod A")
print()
print("  DIVIDE A BY B             => A = A / B")
print("  DIVIDE A BY B GIVING C    => C = A / B")
print("  DIVIDE A BY B GIVING C REMAINDER D  => C = A / B, D = A mod B")
print()
print("  KEY DIFFERENCE: INTO reverses the operand roles")
print("  DIVIDE A INTO B GIVING C  means  C = B / A (not A / B)")
