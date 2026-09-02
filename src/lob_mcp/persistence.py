from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool


class MCPRepository:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    async def migrate(self, migration_file: Path) -> None:
        sql = migration_file.read_text(encoding="utf-8")
        async with self._pool.connection() as connection:
            for statement in sql.split(";"):
                if statement.strip():
                    await connection.execute(statement)

    async def list_servers(self) -> list[dict[str, Any]]:
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                """SELECT id, name, transport, endpoint, command, headers,
                          credential_reference, enabled, runtime_status, last_error,
                          created_at, updated_at
                   FROM mcp_servers WHERE deleted_at IS NULL ORDER BY created_at"""
            )
            return [self._json_row(row) async for row in cursor]

    async def create_server(self, data: dict[str, Any]) -> dict[str, Any]:
        server_id = uuid.uuid4()
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                """INSERT INTO mcp_servers
                   (id, name, transport, endpoint, command, headers, credential_reference, enabled)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                   RETURNING id, name, transport, endpoint, command, headers,
                             credential_reference, enabled, runtime_status, last_error,
                             created_at, updated_at""",
                (
                    server_id,
                    data["name"],
                    data["transport"],
                    data.get("endpoint"),
                    Jsonb(data["command"]) if data.get("command") else None,
                    Jsonb(data.get("headers", {})),
                    data.get("credential_reference"),
                    data.get("enabled", True),
                ),
            )
            row = await cursor.fetchone()
            if row is None:
                raise RuntimeError("server insert returned no row")
            return self._json_row(row)

    async def get_server(self, server_id: uuid.UUID) -> dict[str, Any] | None:
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                """SELECT id, name, transport, endpoint, command, headers,
                          credential_reference, enabled, runtime_status, last_error,
                          created_at, updated_at
                   FROM mcp_servers WHERE id = %s AND deleted_at IS NULL""",
                (server_id,),
            )
            row = await cursor.fetchone()
            return self._json_row(row) if row else None

    async def update_server(self, server_id: uuid.UUID, data: dict[str, Any]) -> dict[str, Any] | None:
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                """UPDATE mcp_servers SET name=%s, transport=%s, endpoint=%s, command=%s,
                          headers=%s, credential_reference=%s, enabled=%s, updated_at=NOW()
                   WHERE id=%s AND deleted_at IS NULL
                   RETURNING id, name, transport, endpoint, command, headers,
                             credential_reference, enabled, runtime_status, last_error,
                             created_at, updated_at""",
                (
                    data["name"], data["transport"], data.get("endpoint"),
                    Jsonb(data["command"]) if data.get("command") else None,
                    Jsonb(data.get("headers", {})), data.get("credential_reference"),
                    data.get("enabled", True), server_id,
                ),
            )
            row = await cursor.fetchone()
            return self._json_row(row) if row else None

    async def set_server_enabled(self, server_id: uuid.UUID, enabled: bool) -> bool:
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                """UPDATE mcp_servers SET enabled=%s, updated_at=NOW()
                   WHERE id=%s AND deleted_at IS NULL""", (enabled, server_id)
            )
            return cursor.rowcount > 0

    async def set_server_runtime(self, server_id: uuid.UUID, status: str, error: str | None = None) -> None:
        async with self._pool.connection() as connection:
            await connection.execute(
                """UPDATE mcp_servers SET runtime_status=%s, last_error=%s, updated_at=NOW()
                   WHERE id=%s""", (status, error, server_id)
            )

    async def save_capability_snapshot(
        self, server_id: uuid.UUID, *, protocol_version: str, server_info: dict[str, Any],
        capabilities: dict[str, Any], tools: list[Any], resources: list[Any], prompts: list[Any],
    ) -> None:
        async with self._pool.connection() as connection:
            await connection.execute(
                """INSERT INTO mcp_capability_snapshots
                       (id, server_id, protocol_version, server_info, capabilities, tools, resources, prompts)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                (uuid.uuid4(), server_id, protocol_version, Jsonb(server_info), Jsonb(capabilities),
                 Jsonb(tools), Jsonb(resources), Jsonb(prompts)),
            )

    async def latest_capability_snapshot(self, server_id: uuid.UUID) -> dict[str, Any] | None:
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                """SELECT id, protocol_version, server_info, capabilities, tools, resources,
                          prompts, created_at FROM mcp_capability_snapshots
                   WHERE server_id=%s ORDER BY created_at DESC LIMIT 1""", (server_id,)
            )
            row = await cursor.fetchone()
            return self._json_row(row) if row else None

    async def soft_delete_server(self, server_id: uuid.UUID) -> bool:
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                """UPDATE mcp_servers SET enabled = FALSE, deleted_at = NOW(), updated_at = NOW()
                   WHERE id = %s AND deleted_at IS NULL""",
                (server_id,),
            )
            return cursor.rowcount > 0

    async def start_invocation(
        self,
        *,
        capability_name: str,
        arguments: dict[str, Any],
        trace_id: str,
        server_id: uuid.UUID | None = None,
    ) -> uuid.UUID:
        invocation_id = uuid.uuid4()
        async with self._pool.connection() as connection:
            await connection.execute(
                """INSERT INTO mcp_invocations
                       (id, server_id, capability_name, arguments, status, trace_id)
                   VALUES (%s, %s, %s, %s, 'running', %s)""",
                (invocation_id, server_id, capability_name, Jsonb(arguments), trace_id),
            )
            await connection.execute(
                """INSERT INTO mcp_events (invocation_id, event_type, payload)
                   VALUES (%s, 'started', '{}'::jsonb)""",
                (invocation_id,),
            )
        return invocation_id

    async def complete_invocation(
        self,
        invocation_id: uuid.UUID,
        *,
        status: str,
        result: dict[str, Any] | None,
        duration_ms: float,
        error: str | None = None,
    ) -> None:
        async with self._pool.connection() as connection:
            await connection.execute(
                """UPDATE mcp_invocations
                   SET result = %s, status = %s, error_message = %s,
                       completed_at = NOW(), duration_ms = %s
                   WHERE id = %s""",
                (
                    Jsonb(result) if result is not None else None,
                    status,
                    error,
                    duration_ms,
                    invocation_id,
                ),
            )
            await connection.execute(
                """INSERT INTO mcp_events (invocation_id, event_type, payload)
                   VALUES (%s, %s, %s)""",
                (
                    invocation_id,
                    status,
                    Jsonb({"error": error} if error else {}),
                ),
            )

    async def list_invocations(
        self, limit: int = 100, offset: int = 0, status: str | None = None,
        capability: str | None = None,
    ) -> list[dict[str, Any]]:
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                """SELECT id, server_id, capability_name, arguments, result, status,
                          error_type, error_message, trace_id, started_at,
                          completed_at, duration_ms, cancel_requested
                   FROM mcp_invocations
                   WHERE (CAST(%s AS TEXT) IS NULL OR status=%s)
                     AND (CAST(%s AS TEXT) IS NULL OR capability_name ILIKE %s)
                   ORDER BY started_at DESC LIMIT %s OFFSET %s""",
                (status, status, capability, f"%{capability}%" if capability else None, limit, offset),
            )
            return [self._json_row(row) async for row in cursor]

    async def get_invocation(self, invocation_id: uuid.UUID) -> dict[str, Any] | None:
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                "SELECT * FROM mcp_invocations WHERE id=%s", (invocation_id,)
            )
            row = await cursor.fetchone()
            return self._json_row(row) if row else None

    async def request_cancellation(self, invocation_id: uuid.UUID) -> bool:
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                """UPDATE mcp_invocations SET cancel_requested=TRUE
                   WHERE id=%s AND status IN ('pending','running')""", (invocation_id,)
            )
            return cursor.rowcount > 0

    async def mark_cancelled(self, invocation_id: uuid.UUID) -> None:
        async with self._pool.connection() as connection:
            await connection.execute(
                """UPDATE mcp_invocations SET status='cancelled', completed_at=NOW()
                   WHERE id=%s""", (invocation_id,)
            )
            await connection.execute(
                "INSERT INTO mcp_events (invocation_id,event_type,payload) VALUES (%s,'cancelled','{}')",
                (invocation_id,),
            )

    async def invocation_events(self, invocation_id: uuid.UUID) -> list[dict[str, Any]]:
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                """SELECT id, event_type, payload, created_at FROM mcp_events
                   WHERE invocation_id = %s ORDER BY created_at""",
                (invocation_id,),
            )
            return [self._json_row(row) async for row in cursor]

    async def create_approval(
        self, invocation_id: uuid.UUID, tool_name: str, risk_level: str,
        arguments: dict[str, Any],
    ) -> uuid.UUID:
        approval_id = uuid.uuid4()
        async with self._pool.connection() as connection:
            await connection.execute(
                """INSERT INTO mcp_approvals
                       (id, invocation_id, tool_name, risk_level, requested_arguments, status)
                   VALUES (%s,%s,%s,%s,%s,'pending')""",
                (approval_id, invocation_id, tool_name, risk_level, Jsonb(arguments)),
            )
            await connection.execute(
                "UPDATE mcp_invocations SET status='awaiting_approval' WHERE id=%s", (invocation_id,)
            )
        return approval_id

    async def list_approvals(self, status: str | None = None) -> list[dict[str, Any]]:
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                """SELECT * FROM mcp_approvals WHERE (CAST(%s AS TEXT) IS NULL OR status=%s)
                   ORDER BY created_at DESC""", (status, status)
            )
            return [self._json_row(row) async for row in cursor]

    async def decide_approval(
        self, approval_id: uuid.UUID, decision: str, final_arguments: dict[str, Any], operator: str,
    ) -> dict[str, Any] | None:
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                """UPDATE mcp_approvals SET status=%s, decision=%s, final_arguments=%s,
                          operator=%s, decided_at=NOW()
                   WHERE id=%s AND status='pending' RETURNING *""",
                (decision, decision, Jsonb(final_arguments), operator, approval_id),
            )
            row = await cursor.fetchone()
            return self._json_row(row) if row else None

    async def put_credential(self, reference: str, ciphertext: bytes) -> None:
        async with self._pool.connection() as connection:
            await connection.execute(
                """INSERT INTO mcp_credentials(reference,ciphertext) VALUES (%s,%s)
                   ON CONFLICT(reference) DO UPDATE SET ciphertext=EXCLUDED.ciphertext,updated_at=NOW()""",
                (reference, ciphertext),
            )

    async def get_credential(self, reference: str) -> bytes | None:
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                "SELECT ciphertext FROM mcp_credentials WHERE reference=%s", (reference,)
            )
            row = await cursor.fetchone()
            return bytes(row["ciphertext"]) if row else None

    @staticmethod
    def _json_row(row: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value.isoformat() if hasattr(value, "isoformat") else str(value)
            if isinstance(value, uuid.UUID)
            else value
            for key, value in row.items()
        }


def create_pool(database_url: str) -> AsyncConnectionPool:
    return AsyncConnectionPool(
        database_url,
        kwargs={"autocommit": True, "row_factory": dict_row},
        open=False,
    )
