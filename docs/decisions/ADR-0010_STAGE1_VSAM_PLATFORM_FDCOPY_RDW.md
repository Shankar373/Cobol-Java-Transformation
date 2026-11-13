# ADR-0010: Stage 1 VSAM decisions: explicit binary platforms, FD COPY expansion, bounded RDW scope

**Date**: 2026-11-13
**Status**: proposed (no owner review yet; ADR-0009 is also proposed)
**Deciders**: engineering (autonomous Stage 1 execution); owner review pending

## Context

Stage 1 had three open design questions: binary fields were copied as bytes although COMP is big-endian, COMP-5 is
native-order and widths differ between IBM and GnuCOBOL; a COPY inside an FD left the FD without a record; variable-length
datasets were refused. Each must stay deterministic and fail closed, and none may claim IBM equivalence without IBM evidence.

## Decision

1. **Binary representation is explicit.** `engine/vsam/platform.py` defines named representations (IBM_ZOS, two GnuCOBOL x86
   presets). A layout with binary fields migrates only when source platform, target platform and target layout are given;
   otherwise it is refused. A key over a binary field whose width or byte order changes is refused.
2. **COPY inside an FD is expanded textually in place** during discovery (`fd_copybooks.py`), before parsing, so the parser
   sees an inline FD. Unresolvable members are ERROR diagnostics; expansion is bounded (32 levels, about 244 member reads).
3. **RDW migration is bounded**: IBM framing (length includes the 4-byte descriptor), sequential and ESDS only, layouts
   selected by exact payload length (unique lengths, no discriminator guessed), no binary fields, ASCII<->EBCDIC cp037.

## Alternatives Considered

- **Infer the platform from the data**: rejected, it is a guess and the repository forbids silent guessing.
- **Merge FD copybooks into the FD record in the IR instead of expanding text**: rejected, it needs a second path for
  ownership, layout and Java generation that the inline FD already has.
- **Pick the first record or a discriminator for multi-layout RDW files**: rejected, nothing in the data identifies the layout.

## Consequences

Positive: refusal is explicit and reasons are in reports; the inline-FD equivalence is proven; GnuCOBOL differential tests
back the width and byte-order claims for its presets.

Negative: IBM_ZOS is documented only; variable KSDS and binary variable layouts stay unsupported; textual expansion cannot
tell a COPY in a comment from one in code except through the existing masking.

Risks: a wrong IBM_ZOS assumption would corrupt migrated binary data. Mitigation: it is labelled documented-only everywhere and
needs an IBM sample before it is relied on.
