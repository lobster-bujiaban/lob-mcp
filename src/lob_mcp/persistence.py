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
                """SELECT id, name, transport, endpoint, command,
                          credential_reference, enabled, created_at, updated_at
                   FROM mcp_servers WHERE deleted_at IS NULL ORDER BY created_at"""
            )
            return [self._json_row(row) async for row in cursor]

    async def create_server(self, data: dict[str, Any]) -> dict[str, Any]:
        server_id = uuid.uuid4()
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                """INSERT INTO mcp_servers
                       (id, name, transport, endpoint, command, credential_reference, enabled)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)
                   RETURNING id, name, transport, endpoint, command,
                             credential_reference, enabled, created_at, updated_at""",
                (
                    server_id,
                    data["name"],
                    data["transport"],
                    data.get("endpoint"),
                    Jsonb(data["command"]) if data.get("command") else None,
                    data.get("credential_reference"),
                    data.get("enabled", True),
                ),
            )
            row = await cursor.fetchone()
            if row is None:
                raise RuntimeError("server insert returned no row")
            return self._json_row(row)

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

    async def list_invocations(self, limit: int = 100) -> list[dict[str, Any]]:
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                """SELECT id, server_id, capability_name, arguments, result, status,
                          error_type, error_message, trace_id, started_at,
                          completed_at, duration_ms
                   FROM mcp_invocations ORDER BY started_at DESC LIMIT %s""",
                (limit,),
            )
            return [self._json_row(row) async for row in cursor]

    async def invocation_events(self, invocation_id: uuid.UUID) -> list[dict[str, Any]]:
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                """SELECT id, event_type, payload, created_at FROM mcp_events
                   WHERE invocation_id = %s ORDER BY created_at""",
                (invocation_id,),
            )
            return [self._json_row(row) async for row in cursor]

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
