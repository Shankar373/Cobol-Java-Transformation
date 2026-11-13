# Stage 3 - CICS, IMS and MQ: plan (2026-11-13)

Nothing here was implemented in this change. In the product, `EXEC CICS`, DL/I and MQI programs are classified UNSUPPORTED
and refused (`engine/transformation/semantic_capability.py`). The simulators prove conformance to their own specifications
only and keep the label `SIMULATOR_VERIFIED`. No IBM equivalence is claimed or possible without an authorised environment.
External facts: [research report](../research/REAL_ENTERPRISE_COBOL_TO_JAVA_REQUIREMENTS.md).

## 1. CICS

### Current state (`OBSERVED_REPOSITORY`)
`engine/cics/` (model, subset, mapper, generator, `SPEC.md`, `INTEGRATION_CONTRACT.md`) and `engine/simulators/cics.py`,
`cics_java.py` (SIMCICS-1 with a Java twin and conformance suites). The integration contract states: no CICS Transaction
Server equivalence; runtime status `NOT_RUNTIME_VERIFIED`. Fixture `workload-cics` is refused by the capability gate.
Parser caveat: the file-verb parser reads the inner `READ DATASET(...)` of an `EXEC CICS` block as a COBOL READ (gap G-22).

### Documented behaviour to cover (VERIFIED_EXTERNAL_SOURCE unless noted)
`EXEC CICS` from COBOL; JCICS (most of the EXEC CICS API) and JCICSX (fewer functions, for local development and
testing); channels and containers as the recommended data passing, COMMAREA limited to 32 KB. Not on the page read:
command semantics, RESP codes, `SYNCPOINT`, `START`/`RETURN`, `LINK`/`XCTL`, EIB, BMS, task lifecycle - these need the
CICS reference, not an inference.

### Plan
1. Fix G-22 so `EXEC CICS` blocks are consumed as one statement, then classify each command (supported by simulator,
   refused by name).
2. Replace simulator-only claims with explicit evidence labels in the capability matrix per command.
3. Define a `CicsRuntime` interface (link, start, return, file control, syncpoint, container get/put) with the simulator as
   one implementation and a JCICS-backed implementation as another that is `EXTERNAL_DEPENDENCY` (CICS region, IBM
   libraries and licence).
4. Transaction boundary model: unit of work, syncpoint, rollback; tests against the simulator are labelled
   `SIMULATOR_VERIFIED`.
5. BMS: map parsing to a screen model is a separate unit; terminal behaviour needs a customer decision (web UI, API).

Exit: every command has a status; no `EXEC CICS` program is accepted without every command in it classified; real-region
results exist before any `IBM_RUNTIME_VERIFIED` label.

## 2. IMS (TM and DB are separate capabilities)

Current: `engine/simulators/dli.py`, `dli_java.py` (SIMDLI-1), `SIMULATOR_VERIFIED`; DL/I calls refused in the product.
To research from IBM documentation before implementing: PSB/PCB structure, segment hierarchy and qualification, `GU` /
`GN` / `GNP` / `ISRT` / `DLET` / `REPL`, status codes, IO areas, `CHKP`/`XRST` checkpoint-restart, commit and rollback,
IMS TM message queues and transaction scheduling.

Plan: IMS DB first (database calls against a segment model with a deterministic store, simulator-labelled), IMS TM as a
separate unit (transaction queue, program scheduling) after the CICS transaction model exists. Real IMS access is
`EXTERNAL_DEPENDENCY`.

## 3. IBM MQ

Current: `engine/simulators/mq.py`, `mq_java.py` (SIMMQ-1), `SIMULATOR_VERIFIED`; MQI calls refused in the product.
COBOL MQI surface to cover: `MQCONN`, `MQOPEN`, `MQPUT`, `MQGET`, `MQCLOSE`, `MQDISC`, `MQCMIT`, `MQBACK`, with completion
and reason codes, syncpoint participation and wait/no-wait options.

Plan: `MqRuntime` interface; simulator implementation labelled; an IBM MQ classes for Java implementation behind the same
interface, excluded from the build until licensing is reviewed and a queue manager is available
(`EXTERNAL_DEPENDENCY`, `OWNER_DECISION_REQUIRED` for the licence). Do not claim IBM equivalence from the simulator.

## 4. Exit criteria for the stage

For each of CICS, IMS TM, IMS DB and MQ: every command or call has a status; the runtime interface exists with the
simulator and an external implementation stub that fails closed without its dependency; every claim is labelled with the
environment that produced it; the product gate stops refusing a construct only when its row is
`IMPLEMENTED_AND_VERIFIED` against a real reference or is explicitly labelled `SIMULATOR_VERIFIED` in every report it
appears in.
