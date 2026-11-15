CREATE TABLE IF NOT EXISTS vsam_jobs (
    job_id TEXT PRIMARY KEY,
    application_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    manifest_json TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    runtime_path TEXT NOT NULL,
    state TEXT NOT NULL,
    error_code TEXT NOT NULL DEFAULT '',
    error_message TEXT NOT NULL DEFAULT '',
    records BIGINT NOT NULL DEFAULT 0,
    bytes_processed BIGINT NOT NULL DEFAULT 0,
    output_name TEXT NOT NULL DEFAULT '',
    output_sha256 TEXT NOT NULL DEFAULT '',
    output_bytes BIGINT NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (application_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS vsam_jobs_state ON vsam_jobs (state)
