# workload-balance-check

Phase 3 coverage application: an account balance review.  Six balances
(credit, overdrawn, flat, over limit, at limit, one cent) are classified by
`EVALUATE TRUE` over sign conditions (`IS ZERO`, `IS NEGATIVE`) and a signed
limit (`< WS-LIMIT`, `-250.00`), watched with a compound condition
(`IS NOT POSITIVE AND > -100.00`), counted down with
`PERFORM UNTIL … IS ZERO`, and a PIC X status is compared with
`ZERO`/`ZEROS` (every character '0').

No `workload.py`: it runs under the default certification contract
(stdout, stderr when written, exit status, every generated file).
