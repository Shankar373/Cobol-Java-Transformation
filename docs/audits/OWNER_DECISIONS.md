# Owner decisions and blockers

Items the implementation cannot decide or perform because they need the owner's credentials,
authorization, keys, purchases or an IBM environment. Each states what is **already done**, what is
**blocked**, and what the owner must provide. Nothing here is faked: where a capability is missing, the
product says so (`docs/CAPABILITY_MATRIX.md`, `docs/audits/EXECUTION_LEDGER.md`).

| # | Decision / blocker | Done without it | Blocked until the owner provides | Related unit |
|---|---|---|---|---|
| 1 | **Identity provider (OIDC/SSO)** for who a caller is | Role model and enforcement (`api/rbac.py`): `viewer` / `operator` / `approver` on bearer tokens, 403 audit events, fail-closed configuration. The identity source is a seam: an OIDC mapping only has to resolve a role and call `rbac.allows` | The IdP (issuer, client, audience), the group/claim-to-role mapping, and a token-validation library decision | 19 |
| 2 | **Artifact signing keys and retention** | Evidence hashing and integrity checks exist; SBOM and vulnerability scans run in supply-chain CI | A signing identity (Sigstore keyless policy or a KMS/HSM key), the retention period for evidence, and who may rotate keys. No signature is produced or claimed today | 19 |
| 3 | **Docker socket isolation** (a socket proxy or rootless runner for the control plane) | Every container the engine starts goes through the shared hardening helper: non-root, all capabilities dropped, no new privileges, no network for oracle and simulator runs | The deployment target (host, orchestrator) and approval to change how the control plane reaches the daemon | 19 |
| 4 | **Target databases beyond DB2 (source) and PostgreSQL** and hosting for them | `DatabaseDialect` registry (a new dialect is a subclass plus `register_dialect`); PostgreSQL target proven against OCESQL + PostgreSQL 14 | Which databases to support, their versions, and a place to run an oracle for each | 11, 12, 13 |
| 5 | **A real DB2 subsystem** | DB2 semantics are modelled and documented; nothing is claimed `DB2_RUNTIME_VERIFIED` | Access to DB2 (LUW or z/OS) or a licensed container, and its licence acceptance | 10-13 |
| 6 | **IBM CICS and IMS entitlement** (BL-132), or acceptance that equivalence stays `SIMULATOR_VERIFIED` | SIMCICS-1 and SIMDLI-1 specifications, Java twins and conformance suites | Entitlement to IBM CICS TS / IMS images, or the decision to ship with the simulator-only label | 15, 16 |
| 7 | **IBM MQ Developer** (BL-131) | SIMMQ-1 specification, Java twin and conformance suite | Acceptance of IBM's licence for the MQ Developer image (the container requires `LICENSE=accept`); without it no reason code is checked against a real queue manager | 14 |
| 8 | **Runtime pin moves** (Python, Java, Ubuntu base images, GnuCOBOL 3.1.2) | Pins are digests or exact versions; Dependabot PRs #10-#27 are reviewed individually, not merged blindly | Approval to move a pin, because a moved pin can change the oracle and invalidates the certified corpus | 3 |
| 9 | **Merge of the numeric-edited PIC work** (uncommitted on `feat/phase3-coverage`) | The work is kept safe and uncommitted; unit 9 delivered INSPECT only | Authorization to commit and merge it, then its four-runtime fuzz and corpus app | 9 |
| 10 | **Closing the superseded Dependabot PRs** | Reviewed; the policy and a reviewed upgrade set are in `main`'s successor branch | Authorization to close or merge each after the integration branch reaches `main` | 3 |
| 11 | **Hosting for decomposed services** (Kubernetes, compose, registry) | The decomposition planner proposes boundaries for review (`/applications/{id}/decomposition`) | Where the services run and how they are deployed; no container or manifest is generated today | 18 |
| 12 | **Merging `impl/enterprise-platform` into `main`** | Every unit is gated by CI, supply chain and four-runtime certification on its own commit | Authorization to merge (history is preserved, no force-push) | all |

## Evaluated and decided without the owner

* **Interrupted-run recovery** stays fail-closed (runs fail with their last stage preserved and can be validated again); re-queueing was rejected because the stages are not idempotent. Reasons: `CAPABILITY_STATUS.md`.
* **Simulator integration** (MQ / IMS / CICS into generated code) is not safely actionable yet; the prerequisites are listed in `CAPABILITY_STATUS.md`. It also stays blocked on rows 6 and 7 above for any IBM equivalence claim.

## Not blocked, not done

Independent of the owner, and still open: JCL `SORT`/`IEBCOPY`/`IF` blocks, `SEARCH`/`SORT`/`MERGE` statements,
a CICS/IMS/MQ lowering to the simulators' Java libraries (the specifications and conformance exist; the
generated-code integration does not), WHENEVER/indicator/dynamic SQL, type checking and a coverage gate in CI,
a Windows CI lane, and artifact signing's non-key parts. The execution ledger names each of them on its row.
