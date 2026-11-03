# workload-dynamic-call-valid

Corrected copy of `fixtures/workload-dynamic-call`, which places LINKAGE SECTION
before WORKING-STORAGE SECTION. GnuCOBOL 3.1.2 rejects that order, and the
parser now refuses it (`UNSUPPORTED_CONSTRUCT`: "WORKING-STORAGE SECTION is
out of order"), so the original stays as a fail-closed fixture.

The only change here is the section order of the called program. No
`workload.py`: an application built from this directory runs under the
default certification contract (stdout, exit status, generated files).
