"""Forensic search for domain coupling in generator and mapping."""
import re
import sys

files = [
    "engine/transformation/java_generator.py",
    "engine/transformation/cobol_to_java_mapping.py",
    "engine/transformation/java_ir.py",
]

# Patterns that indicate domain coupling in executable code
patterns = [
    (r'(?<![A-Za-z])AMT(?![A-Za-z])', "AMT field-name heuristic"),
    (r'(?<![A-Za-z])STATUS(?![A-Za-z])', "STATUS field-name heuristic"),
    (r'(?<![A-Za-z])CATEGORY(?![A-Za-z])', "CATEGORY field-name heuristic"),
    (r'/input/', "path-based input inference"),
    (r'/output/', "path-based output inference"),
    (r'input[12]\.dat', "fallback filename"),
    (r'output[12]\.(dat|txt)', "fallback filename"),
    (r'input\.dat', "fallback filename"),
    (r'claims\.dat', "Claims filename"),
    (r'settlement\.dat', "Settlement filename"),
    (r'payments\.dat', "Payments filename"),
]

found = False
for f in files:
    try:
        lines = open(f).readlines()
    except FileNotFoundError:
        continue
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        for pat, desc in patterns:
            if re.search(pat, line):
                print(f"FOUND: {f}:{i}: [{desc}] {stripped[:120]}")
                found = True

if not found:
    print("CLEAN: No domain coupling found in executable code")
else:
    print("DOMAIN_COUPLING_FOUND")
    sys.exit(1)
