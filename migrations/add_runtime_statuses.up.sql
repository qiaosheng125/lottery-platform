CREATE TABLE IF NOT EXISTS runtime_statuses (
    service_name VARCHAR(64) PRIMARY KEY,
    status VARCHAR(32) NOT NULL DEFAULT 'unknown',
    payload JSONB,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
