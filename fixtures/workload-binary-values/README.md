# workload-binary-values

Phase 3 coverage application: binary and packed-decimal working storage
(`COMP`, `BINARY`, `COMP-4`, `COMPUTATIONAL`, `COMP-3`, `PACKED-DECIMAL`)
used the way batch programs use counters, amounts and indexes — MOVE with
truncation at both ends, negative values into unsigned items, ROUNDED and
truncated COMPUTE, wrap on overflow, wide intermediate results, MOVE to and
from `PIC X`, DIVIDE with REMAINDER, PERFORM VARYING, compound conditions
over a scaled item, INITIALIZE.

GnuCOBOL 3.1.2 prints identical output for this program with and without
its USAGE clauses (`tests/test_binary_usage_values.py` checks it in the
Docker lane), which is what makes these items certifiable by value.

No `workload.py`: it runs under the default certification contract
(stdout, stderr when written, exit status, every generated file).
