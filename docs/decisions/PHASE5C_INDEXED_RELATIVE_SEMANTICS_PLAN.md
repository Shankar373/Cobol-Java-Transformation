# Phase 5C — Indexed/Relative Semantic Validation Plan

## 1. Predecessor Forensic Root Cause

The predecessor repository (`Cobol-to-java-test`) used substring containment as a
fallback when byte-exact comparison of indexed/relative files failed:

```python
all(rec in cobol_content for rec in lines)
```

This passed:
- Missing records (subset of oracle)
- Reordered records (containment is order-independent)
- Extra records (only checks candidate→oracle, not oracle→candidate)
- Substring matches (different content with matching prefix)

The root cause was comparing incompatible physical representations
(Berkeley DB B-tree vs flat records) and using containment as a
"logical equivalence" fallback.

## 2. Semantic Incompatibility Problem

COBOL indexed files are stored in Berkeley DB B-tree format. Java has no
native support for this format. Direct byte comparison always fails.
The predecessor's fallback to substring containment introduced the
false-PASS vulnerability.

## 3. Solution: Canonical Semantic Representation

Instead of comparing physical files, both programs independently produce
a canonical semantic dump of the file's logical state. The dump is a
deterministic text format that can be compared byte-exact.

```
COBOL physical file → operations → canonical dump (stdout)
Java logical state  → operations → canonical dump (stdout)
                                        ↓
                              TextFileComparator
                                        ↓
                                    verdict
```

## 4. Supported Subset

### INDEXED
- Single primary key (PIC X(4))
- Fixed-width record content (PIC X(16))
- DYNAMIC access mode
- OPEN OUTPUT (create)
- OPEN I-O (reopen for update)
- WRITE with key
- READ by key (NEXT)
- REWRITE
- DELETE
- START KEY >= (cursor positioning)
- Sequential scan via READ NEXT

### RELATIVE
- Relative record number (PIC 9(4) COMP)
- Fixed-width record content (PIC X(20))
- DYNAMIC access mode
- OPEN OUTPUT (create)
- OPEN I-O (reopen for update)
- WRITE by RRN
- READ by RRN
- REWRITE by RRN
- Sequential scan via RRN iteration

### Explicitly UNSUPPORTED
- Alternate keys
- Duplicate-key semantics
- Composite keys
- Variable-length records
- RANDOM access verification (beyond write/read)
- DELETE for relative files (not tested)
- z/OS equivalence

## 5. Canonical Dump Format

Pipe-delimited text, one record per line:

**INDEXED**: `KEY|DATA`
**RELATIVE**: `RRNN|DATA`

Terminal lines:
- `FILESTATUS=NN` — COBOL file status
- `END` — program completion

Both programs produce identical stdout when operations are correct.
The existing TextFileComparator compares byte-exact.

## 6. Artifact Treatment

Canonical dumps are compared as **STDOUT** artifacts. No new artifact
types are introduced. INDEXED and RELATIVE remain excluded from the
V1 physical artifact registry.

## 7. Oracle Modification

The oracle adapter's compile command was modified to `cd /workspace`
before executing the COBOL program. This ensures writable working
directory for indexed/relative file creation. The change is backward-
compatible: existing workloads that only write to stdout are unaffected.

## 8. Test Matrix

### INDEXED (13 tests)
- correct candidate → VERIFIED
- missing key → FAILED
- extra key → FAILED
- wrong key → FAILED
- changed content → FAILED
- wrong mapping → FAILED
- duplicate record → FAILED
- incorrect delete → FAILED
- incorrect rewrite → FAILED
- evidence verification (2 tests)
- determinism proof

### RELATIVE (10 tests)
- correct candidate → VERIFIED
- missing record → FAILED
- extra record → FAILED
- wrong RRN → FAILED
- changed content → FAILED
- shifted record → FAILED
- incorrect rewrite → FAILED
- evidence verification (2 tests)
- determinism proof

## 9. Security

No changes to Phase 4B sandbox:
- Docker-only execution preserved
- network none preserved
- memory 512m, CPU 1.0, PIDs 256 preserved
- timeout preserved
- explicit cleanup preserved
- no host fallback preserved
