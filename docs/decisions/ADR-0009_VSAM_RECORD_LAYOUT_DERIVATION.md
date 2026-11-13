# ADR-0009 — Record layout derivation for dataset migration

**Status:** **PROPOSED** (engineering proposal; the platform owner has not confirmed it - see "Owner questions")

**Date:** 2026-11-13 · **Related:** [Stage 1 plan](../roadmap/STAGE_1_VSAM_IMPLEMENTATION_PLAN.md), `engine/vsam/convert.py`, gap register G-09

## Context

`engine/vsam/convert.py` converts a fixed-length dataset between ASCII and EBCDIC, but the caller supplies the field layout
by hand. A migration that depends on a hand-typed layout cannot be trusted: a wrong offset translates a packed field or
leaves text untranslated. The COBOL record description already exists in the IR (`FileDefinition.record_groups`, a `DataItem`
tree). Three facts about that IR decide the design:

1. No byte-size calculator exists. `DataItem.pic_length` is the digit or character count (it includes the `V` decimals), and the
   comments in the IR and in `tests/test_binary_usage_values.py` state that the *byte encoding* of non-DISPLAY usages is not
   certified - only their values are.
2. The IR carries `usage`, `occurs`, `occurs_depending_on` and `redefines`, but **drops the `SIGN` (LEADING/TRAILING, SEPARATE),
   `SYNCHRONIZED` and `JUSTIFIED` clauses**. A layout derived from today's IR would silently mis-size a `SIGN IS SEPARATE` field (one
   extra byte) or a `SYNC` item (alignment padding).
3. COMP / BINARY width depends on the dialect: IBM allocates 2, 4 or 8 bytes (1-4, 5-9, 10-18 digits); GnuCOBOL's default
   allocates 1, 2, 4 or 8 (1-2, 3-4, 5-9, 10-18).

## Decision

1. Add `engine/vsam/layout.py`: a pure function from a `FileDefinition` (or any `DataItem` tree) and explicit options to a
   `RecordLayout` - record length, ordered fields (`convert.FieldSpec` plus provenance: the dotted COBOL path, level, source item),
   diagnostics, and a SHA-256 layout identity over its canonical form.
2. Extend the IR backward-compatibly: `DataItem` gains `sign_position` (`""`, `"LEADING"`, `"TRAILING"`), `sign_separate`,
   `synchronized` and `justified` (defaults reproduce current behaviour), recorded by the parser and otherwise unused by lowering.
3. The binary width model is a **required, explicit option** (`IBM_2_4_8` or `GNUCOBOL_1_2_4_8`); there is no default, because the
   right answer depends on where the data was produced.
4. Byte sizes follow the documented storage rules (DISPLAY = digits or characters; sign leading/trailing inline = no extra byte;
   `SIGN SEPARATE` = +1; COMP-3 = digits // 2 + 1; COMP/COMP-5 per the width model). They are tested as `DOCUMENTED_SEMANTICS`: no
   GnuCOBOL or IBM run proves a byte layout in this repository.
5. Refused with a named diagnostic, never approximated: `OCCURS DEPENDING ON`, `SYNCHRONIZED`, `COMP-1` / `COMP-2`, `PIC N`,
   `POINTER` / `INDEX` usage, a `REDEFINES` with no explicit selection, and any item whose size the rules above do not cover.
6. `REDEFINES`: an overlay is derived only when the caller names the active alternative for it; the others occupy the same bytes
   and are not translated. Without a selection the layout is refused (never the first alternative by declaration order).
7. Fixed `OCCURS` (also nested) is expanded element by element (`NAME(1)`, `NAME(2)` ...) from exact element sizes.
8. A `USAGE`, `SIGN` or `SYNCHRONIZED` clause on a **group** is refused (`GROUP_CLAUSE_INHERITED` / `SYNCHRONIZED`): children would inherit it
   and the IR cannot tell a child's own `DISPLAY` from an inherited usage.
9. Hard limits, checked by arithmetic before any field exists (a hostile or accidental `OCCURS 99999999` must not be expanded):
   `MAX_LAYOUT_FIELDS = 100,000` fields after `OCCURS` expansion (`OCCURS_TOO_LARGE`) and `MAX_RECORD_BYTES = 1,048,576` (`RECORD_TOO_LARGE`).
10. Field paths are unique: a repeated sibling name (typically `FILLER`) becomes `FILLER`, `FILLER#2`, ...; each refusal is reported once.
11. Each field records its `USAGE`, because byte order is part of the meaning: COMP is big-endian, COMP-5 is native order. Binary bytes are copied, never
    reordered (gap G-27). A `REDEFINES` selection is keyed by the redefined item's name, so two same-named targets in different groups share one selection.
12. The layout must cover the record exactly, with `FILLER` as an explicit DISPLAY field; the conversion's existing coverage
   validation stays the second check.

## Alternatives considered

- **Hand-written layouts (status quo):** simplest, but the layout is exactly what a migration must not guess. Rejected.
- **Guess the active REDEFINES alternative, or default the COMP width:** produces a plausible layout that is wrong for some datasets.
  Rejected: the project rule is to refuse what it cannot prove.
- **Read the layout from the generated Java instead of the IR:** the Java lowering stores numbers, not record bytes, so the byte
  layout is not there. Rejected.
- **Copy PIC sizing from GnuCOBOL's cobc:** would tie the migration to one dialect and add a runtime dependency. Rejected.

## Consequences

- Positive: the migration is driven by the same COBOL source as the program; every field has provenance; unsupported layouts fail by
  name; the layout has an identity that goes into the migration report.
- Negative: byte sizes are checked against GnuCOBOL (default and `-std=ibm` dialects, `tests/integration/test_vsam_layout_oracle.py`) but not against IBM
  Enterprise COBOL; the IR change touches the parser (new
  fields, no behaviour change).
- Risk: a dialect or compiler option the model does not know (for example `TRUNC(BIN)` effects on storage, `ARITH(EXTEND)`, a site
  `SIGN` default) yields a wrong layout. Mitigation: the binary model is explicit, every refusal is named, and the `reconcile_migration`
  check compares the converted data back against the source.

## Owner questions (`OWNER_DECISION_REQUIRED`)

Which dialect(s) the customer data was produced by, so the supported width models can be limited to those; whether `SYNCHRONIZED`
and `SIGN SEPARATE` data occur in the pilot's datasets; access to a real record sample to validate the derived layout against.
