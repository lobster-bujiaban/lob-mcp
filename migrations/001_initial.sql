CREATE TABLE IF NOT EXISTS mcp_servers (
    id UUID PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    transport TEXT NOT NULL,
    endpoint TEXT,
    command JSONB,
    credential_reference TEXT,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    deleted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS mcp_capability_snapshots (
    id UUID PRIMARY KEY,
    server_id UUID NOT NULL REFERENCES mcp_servers(id),
    protocol_version TEXT NOT NULL,
    server_info JSONB NOT NULL,
    capabilities JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS mcp_invocations (
    id UUID PRIMARY KEY,
    server_id UUID REFERENCES mcp_servers(id),
    capability_name TEXT NOT NULL,
    arguments JSONB NOT NULL,
    result JSONB,
    status TEXT NOT NULL,
    error_type TEXT,
    error_message TEXT,
    trace_id TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    duration_ms DOUBLE PRECISION
);

CREATE TABLE IF NOT EXISTS mcp_approvals (
    id UUID PRIMARY KEY,
    invocation_id UUID REFERENCES mcp_invocations(id),
    risk_level TEXT NOT NULL,
    requested_arguments JSONB NOT NULL,
    final_arguments JSONB,
    decision TEXT,
    operator TEXT,
    decided_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS mcp_events (
    id BIGSERIAL PRIMARY KEY,
    invocation_id UUID NOT NULL REFERENCES mcp_invocations(id),
    event_type TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mcp_invocations_started_at
    ON mcp_invocations(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_mcp_events_invocation_id
    ON mcp_events(invocation_id, created_at);

