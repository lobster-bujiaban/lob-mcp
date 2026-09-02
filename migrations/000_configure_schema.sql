-- 创建数据库后，把 GUI 当前数据库切换为 lob_mcp，再使用管理员账号执行。

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO lob_mcp;
ALTER SCHEMA public OWNER TO lob_mcp;
