# workload-record-sequential

Phase 3 coverage application: a nightly extract step on fixed-length
record SEQUENTIAL files — the batch default.  `EXTRACT.DAT` has no
ORGANIZATION clause; `SUMMARY.DAT` says `ORGANIZATION IS SEQUENTIAL`.
The program writes records field by field, appends one with OPEN EXTEND
and `WRITE … FROM` a working-storage group, reads the file back with
AT END / FILE STATUS, totals it, and writes a summary record `FROM` a
group with FILLER literals.

GnuCOBOL 3.1.2 writes both files as bare record areas (no terminator,
trailing spaces kept); the run is certified byte-exactly on both files
plus stdout and exit status.

No `workload.py`: it runs under the default certification contract
(stdout, stderr when written, exit status, every generated file).
