ALTER TABLE mcp_servers ADD COLUMN IF NOT EXISTS headers JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE mcp_servers ADD COLUMN IF NOT EXISTS runtime_status TEXT NOT NULL DEFAULT 'closed';
ALTER TABLE mcp_servers ADD COLUMN IF NOT EXISTS last_error TEXT;

ALTER TABLE mcp_capability_snapshots ADD COLUMN IF NOT EXISTS tools JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE mcp_capability_snapshots ADD COLUMN IF NOT EXISTS resources JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE mcp_capability_snapshots ADD COLUMN IF NOT EXISTS prompts JSONB NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE mcp_invocations ADD COLUMN IF NOT EXISTS cancel_requested BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE mcp_approvals ADD COLUMN IF NOT EXISTS tool_name TEXT;
ALTER TABLE mcp_approvals ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'pending';

CREATE TABLE IF NOT EXISTS mcp_credentials (
    reference TEXT PRIMARY KEY,
    ciphertext BYTEA NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mcp_invocations_status_started
    ON mcp_invocations(status, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_mcp_approvals_status_created
    ON mcp_approvals(status, created_at DESC);
