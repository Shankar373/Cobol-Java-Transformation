# workload-batch-rc

Phase 3 coverage application: a nightly validation job step that writes a
transaction extract (LINE SEQUENTIAL, single-quoted ASSIGN), reads it back,
classifies each record through PERFORMed paragraphs and nested IF, and ends
with the job-step return code a scheduler acts on: `EVALUATE TRUE` sets
RETURN-CODE to 0 (clean), 4 (warnings) or 8 (errors).

GnuCOBOL 3.1.2 exits with status 4 for this data.  The run is certified
through EXIT_STATUS like any other behaviour: the oracle records the exit
as the program's own return code (`return_code`), not as a failed
reference.

No `workload.py`: it runs under the default certification contract
(stdout, stderr when written, exit status, every generated file).
