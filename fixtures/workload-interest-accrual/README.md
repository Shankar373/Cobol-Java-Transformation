# workload-interest-accrual

Phase 3 coverage application: interest accrual guarded by ON SIZE ERROR.
Five accounts accrue `COMPUTE … ROUNDED` interest; one result does not fit
its field (the receiver keeps its previous value, the SIZE ERROR body
counts it), one account has zero terms (`DIVIDE … BY 0` raises the size
error), the others take the NOT ON SIZE ERROR branch.  A period-terminated
`ADD … ON SIZE ERROR` saturates the total and a `MULTIPLY … NOT ON SIZE
ERROR` doubles a counter.

No `workload.py`: it runs under the default certification contract
(stdout, stderr when written, exit status, every generated file).
