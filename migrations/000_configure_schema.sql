-- 创建数据库后，把 GUI 当前数据库切换为 lob_mcp，再使用管理员账号执行。

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO lob_mcp;
ALTER SCHEMA public OWNER TO lob_mcp;

ALTER TABLE IF EXISTS mcp_servers OWNER TO lob_mcp;
ALTER TABLE IF EXISTS mcp_capability_snapshots OWNER TO lob_mcp;
ALTER TABLE IF EXISTS mcp_invocations OWNER TO lob_mcp;
ALTER TABLE IF EXISTS mcp_approvals OWNER TO lob_mcp;
ALTER TABLE IF EXISTS mcp_events OWNER TO lob_mcp;
ALTER SEQUENCE IF EXISTS mcp_events_id_seq OWNER TO lob_mcp;

GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO lob_mcp;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO lob_mcp;
