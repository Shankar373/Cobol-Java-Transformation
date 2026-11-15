# IBM evidence request pack

Purpose: the capabilities marked BLOCKED in `docs/roadmap/STAGE_1_REMAINING_GAPS_DISPOSITION.md` cannot be verified with
GnuCOBOL. They need output captured from a real IBM z/OS system running IBM Enterprise COBOL, VSAM and IDCAMS.
Nothing here has been run by us. The programs and jobs below are templates written without access to z/OS; they will need
the usual site adjustments (job card, dataset names, compiler and runtime library names) and may need small syntax fixes.
A capability becomes `IBM_RUNTIME_VERIFIED` only after captured output from a real system is committed and a test compares
our behaviour with it. Emulation (Hercules, QEMU s390x Linux) is not z/OS and does not count.

## Where free access exists

- **IBM Z Xplore** (IBM's free learning platform) gives a no-cost IBM Z ID with a real z/OS system; its advanced content lists
  COBOL, VSAM and JCL labs. We could not confirm from public pages that IDCAMS, `DEFINE CLUSTER` or compiler listing options
  are available to learner IDs, or that its terms allow using output as certification evidence. Check the platform's terms and
  the account's permissions first. Registering needs a person's identity, so this has to be done by the project owner.
- **IBM Z software trials** and **BMC AMI Test Drive** offer short hosted trials (days). Check each for cost and terms before
  any sign-up, because this project allows no spend and no trial that can turn into a subscription.
- Hercules with MVS 3.8j is free but runs an old operating system and OS/VS COBOL, not Enterprise COBOL; its output may be
  useful as background but is not evidence for this project.

## What to capture for each experiment

Record: z/OS and Enterprise COBOL version, the compiler options in effect (at least `ARITH`, `TRUNC`, `NUMPROC`, `LIST` or
`MAP`, `OPT`), the full job output (`SYSPRINT`, `SYSOUT`, return codes) and, for datasets, an IDCAMS `PRINT ... HEX` listing.
Save as plain text under `docs/reports/evidence/ibm/<experiment>/` with the job log and a `README.md` naming the system.

## Experiment A: RRDS slot semantics (blocks RRDS equivalence)

Define a numbered cluster, then run a program that writes relative records 1, 2, 5 and 9, then in this order: reads slot 3
(empty), reads 2, deletes 2, reads 2, writes 2 again, rewrites slot 7 (empty), writes slot 5 again, reads slot 1000000.
Capture the FILE STATUS after every statement and the record contents. Needed because our relative-file behaviour is the
GnuCOBOL one.

```jcl
//RRDSDEF  EXEC PGM=IDCAMS
//SYSPRINT DD SYSOUT=*
//SYSIN    DD *
  DELETE (USER.RRDS.TEST) CLUSTER PURGE
  SET MAXCC = 0
  DEFINE CLUSTER (NAME(USER.RRDS.TEST) NUMBERED RECORDSIZE(10 10) -
         RECORDS(20 5) VOLUMES(VOL001))
/*
```

## Experiment B: ESDS and RBA (blocks ESDS RBA preservation)

Define a non-indexed cluster, write 5 fixed records and one record of a different length (variable case), then run
`PRINT INDATASET(USER.ESDS.TEST) CHARACTER` and `PRINT ... HEX`. The IDCAMS listing shows each record's RBA, which is the
reference for any RBA preservation rule. Also capture the same after a REWRITE of the same length and after an attempted
DELETE (VSAM ESDS refuses it).

```jcl
//ESDSDEF  EXEC PGM=IDCAMS
//SYSPRINT DD SYSOUT=*
//SYSIN    DD *
  DELETE (USER.ESDS.TEST) CLUSTER PURGE
  SET MAXCC = 0
  DEFINE CLUSTER (NAME(USER.ESDS.TEST) NONINDEXED RECORDSIZE(10 20) -
         RECORDS(20 5) VOLUMES(VOL001))
  PRINT INDATASET(USER.ESDS.TEST) CHARACTER
/*
```

## Experiment C: alternate index and IDCAMS catalog output (blocks BLDINDEX, LISTCAT, DEFINE CLUSTER, ALTER)

Define a KSDS with the primary key at offset 0, load it with REPRO, then `DEFINE ALTERNATEINDEX` with and without
`NONUNIQUEKEY`, `DEFINE PATH`, `BLDINDEX`, and run `LISTCAT ENTRIES(...) ALL`. Capture every `SYSPRINT`, the condition codes
and the PRINT of the alternate index with `HEX`. Include a load with a duplicate unique alternate value to capture the
failure messages and condition code, and a repeat run of each command to capture the already-exists behaviour.

## Experiment D: floating-point and layout (blocks COMP-1/COMP-2, SYNCHRONIZED, OCCURS DEPENDING ON)

Compile with `LIST` or `MAP` so the data map shows each item's offset and length. Use a record with COMP-1, COMP-2,
SYNCHRONIZED COMP and COMP-5 items next to PIC X items, and another with an `OCCURS 1 TO 5 DEPENDING ON` table. Write
records with known values to a sequential dataset and capture `PRINT ... HEX`. This gives the IBM hexadecimal floating-point
bytes and the real offsets to compare with `engine/vsam/layout.py`.

## How a capture becomes a test

1. Commit the captured text and the exact source and JCL used.
2. Write a test that parses the capture and asserts our engine reproduces the same offsets, bytes or statuses.
3. Only then change the capability from BLOCKED and record the system and options in the evidence README.
Until then every item above stays BLOCKED and no `IBM_RUNTIME_VERIFIED` claim is made.
