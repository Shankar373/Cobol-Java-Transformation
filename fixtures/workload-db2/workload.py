"""DB2 embedded-SQL workload declaration.

Declares the ACCOUNT-DB2 workload for the DB2 modernization lane.

This workload drives a *controlled test database* (SQLite-backed, see
``engine/sql/execution``).  It exercises the supported subset:

- singleton SELECT INTO with SQLCODE 100 / 0 / -811 outcomes
- INSERT / UPDATE / DELETE DML with unique-key (-803) status
- DECLARE / OPEN / FETCH / CLOSE cursor lifecycle
- COMMIT / ROLLBACK transaction boundaries

Compatibility discipline: this workload validates behavior of the
translated subset on the controlled database.  It is NOT DB2 runtime
verification; see ``engine/sql/dialect`` for the classification model.
"""

from __future__ import annotations

from engine.contracts.models import FailurePolicy, NormalizationPolicy, OrderingPolicy
from engine.workload import WorkloadArtifact, WorkloadDefinition, WorkloadInput


def db2_workload() -> WorkloadDefinition:
    """Return the workload definition for the ACCOUNT-DB2 program."""
    return WorkloadDefinition(
        workload_id="workload-db2",
        description=(
            "ACCOUNT-DB2 embedded SQL: SELECT INTO, INSERT, UPDATE, "
            "DELETE, cursor lifecycle, COMMIT/ROLLBACK on ACCOUNT."
        ),
        inputs=(
            WorkloadInput(
                logical_name="ddl",
                source_path="schema/account.sql",
                container_path="/workspace/schema/account.sql",
            ),
            WorkloadInput(
                logical_name="seed-sql",
                source_path="data/account_seed.sql",
                container_path="/workspace/data/account_seed.sql",
            ),
            WorkloadInput(
                logical_name="seed-csv",
                source_path="data/account_seed.csv",
                container_path="/workspace/data/account_seed.csv",
            ),
            WorkloadInput(
                logical_name="source",
                source_path="cobol/ACCOUNT-DB2.cob",
                container_path="/workspace/cobol/ACCOUNT-DB2.cob",
            ),
        ),
        artifacts=(
            WorkloadArtifact(
                logical_name="db2-execution-trace",
                artifact_type="TEXT_FILE",
                comparator_id="text-file-exact",
                output_path="db2_execution.trace",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
                failure=FailurePolicy(on_missing="FAILED", on_malformed="MISMATCH", on_extra="MISMATCH"),
            ),
            WorkloadArtifact(
                logical_name="db2-exit-status",
                artifact_type="EXIT_STATUS",
                comparator_id="exit-status-exact",
            ),
        ),
    )