# workload-notices

Phase 3 coverage application: a customer-notice batch job that combines the
source forms real fixed-format code uses and no earlier fixture exercised:

- `SELECT ... ASSIGN TO 'NOTICES.TXT'` with the ASSIGN on its own line
  (single-quoted literal);
- continued alphanumeric literal (`-` in column 7; the literal runs through
  column 72, so the header reads `BAT CH` exactly as GnuCOBOL stores it);
- continued numeric literal (`12` / `345` → 12345) and a continued data
  name (`WS-BALAN` / `CE-DUE`);
- doubled-quote escapes in both quote styles (`BRANCH''S`,
  `""BANKING""`, `' ''DONE'''`), and a single quote inside a
  double-quoted literal (`"O'BRIEN"`);
- LINE SEQUENTIAL WRITE then READ-back with FILE STATUS, STRING
  DELIMITED BY SPACE, PERFORM UNTIL.

No `workload.py`: it runs under the default certification contract
(stdout, stderr when written, exit status, every generated file).
