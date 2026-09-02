from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from contextlib import suppress

import httpx
import uvicorn

from lob_mcp.client import MCPClient
from lob_mcp.events import ProtocolEvent
from lob_mcp.examples.order import create_order_tool_registry
from lob_mcp.gateway import MultiServerGateway
from lob_mcp.governance import (
    CredentialStore,
    GovernedGateway,
    RiskLevel,
    ToolPolicy,
)
from lob_mcp.examples.knowledge import create_prompt_registry, create_resource_registry
from lob_mcp.server import MCPServer
from lob_mcp.http_server import create_http_app
from lob_mcp.management import create_management_app
from lob_mcp.transport import (
    StdioProcessTransport,
    StdioServerTransport,
    StreamableHTTPTransport,
    create_memory_transport_pair,
)


def print_event(event: ProtocolEvent) -> None:
    print(json.dumps(event.as_dict(), ensure_ascii=False))


async def run_demo() -> None:
    client_transport, server_transport = create_memory_transport_pair()
    client = MCPClient(client_transport, print_event)
    server = MCPServer(server_transport, print_event)
    server_task = asyncio.create_task(server.serve())

    try:
        await client.connect()
        ping_result = await client.ping()
        print(
            json.dumps(
                {
                    "demo": "completed",
                    "clientState": client.state,
                    "serverInfo": client.server_info,
                    "pingResult": ping_result,
                },
                ensure_ascii=False,
            )
        )
    finally:
        await client.close()
        await server.close()
        server_task.cancel()
        with suppress(asyncio.CancelledError):
            await server_task


def print_server_stderr(line: str) -> None:
    print(json.dumps({"actor": "server-process", "stream": "stderr", "line": line}))


async def run_stdio_demo() -> None:
    transport = await StdioProcessTransport.start(
        [sys.executable, "-m", "lob_mcp.cli", "serve-stdio"],
        stderr_sink=print_server_stderr,
    )
    client = MCPClient(transport, print_event)
    try:
        await client.connect()
        ping_result = await client.ping()
        print(
            json.dumps(
                {
                    "demo": "stdio-completed",
                    "childPid": transport.pid,
                    "clientState": client.state,
                    "serverInfo": client.server_info,
                    "pingResult": ping_result,
                },
                ensure_ascii=False,
            )
        )
    finally:
        await client.close()


async def run_tools_demo() -> None:
    transport = await StdioProcessTransport.start(
        [sys.executable, "-m", "lob_mcp.cli", "serve-stdio"],
        stderr_sink=print_server_stderr,
    )
    client = MCPClient(transport, print_event)
    try:
        await client.connect()
        tools = await client.list_tools()
        result = await client.call_tool(
            "order.query",
            {"order_id": "ORD-20250902-001"},
        )
        print(
            json.dumps(
                {
                    "demo": "tools-completed",
                    "discoveredTools": [tool["name"] for tool in tools],
                    "callResult": result,
                },
                ensure_ascii=False,
            )
        )
    finally:
        await client.close()


async def run_content_demo() -> None:
    transport = await StdioProcessTransport.start(
        [sys.executable, "-m", "lob_mcp.cli", "serve-stdio"],
        stderr_sink=print_server_stderr,
    )
    client = MCPClient(transport, print_event)
    try:
        await client.connect()
        resources = await client.list_resources()
        contents = await client.read_resource("docs://orders/status-guide")
        templates = await client.list_resource_templates()
        prompts = await client.list_prompts()
        prompt = await client.get_prompt(
            "order.assistant", {"order_id": "ORD-20250902-001"}
        )
        print(json.dumps({
            "demo": "content-completed",
            "resources": resources,
            "contents": contents,
            "resourceTemplates": templates,
            "prompts": prompts,
            "renderedPrompt": prompt,
        }, ensure_ascii=False))
    finally:
        await client.close()


async def run_http_demo() -> None:
    port = 8765
    token = "lob-mcp-demo-token"
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "lob_mcp.cli",
        "serve-http",
        "--port",
        str(port),
        "--session-ttl",
        "0.3",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    stderr_task = asyncio.create_task(_drain_process_stderr(process))
    try:
        await _wait_for_http_server(f"http://127.0.0.1:{port}/health")
        transport = StreamableHTTPTransport(
            f"http://127.0.0.1:{port}/mcp", token=token
        )
        client = MCPClient(transport, print_event)
        try:
            await client.connect()
            tools = await client.list_tools()
            await asyncio.sleep(0.4)
            result = await client.call_tool(
                "order.query", {"order_id": "ORD-20250902-002"}
            )
            print(json.dumps({
                "demo": "http-completed",
                "sessionId": transport.session_id,
                "reconnectCount": transport.reconnect_count,
                "serverInfo": client.server_info,
                "discoveredTools": [tool["name"] for tool in tools],
                "callResult": result,
            }, ensure_ascii=False))
        finally:
            await client.close()
    finally:
        if process.returncode is None:
            process.terminate()
        await process.wait()
        await stderr_task


async def run_multi_server_demo() -> None:
    gateway = MultiServerGateway()
    servers: list[tuple[MCPServer, asyncio.Task[None]]] = []

    def add_server(name: str, *, with_order_tool: bool) -> None:
        client_transport, server_transport = create_memory_transport_pair()
        server = MCPServer(
            server_transport,
            name=f"{name}-server",
            tool_registry=create_order_tool_registry() if with_order_tool else None,
            resource_registry=create_resource_registry(),
            prompt_registry=create_prompt_registry(),
        )
        servers.append((server, asyncio.create_task(server.serve())))
        gateway.register(name, MCPClient(client_transport, print_event))

    add_server("orders", with_order_tool=True)
    add_server("backup", with_order_tool=True)
    add_server("knowledge", with_order_tool=False)
    offline_transport, offline_peer = create_memory_transport_pair()
    await offline_peer.close()
    gateway.register("offline", MCPClient(offline_transport, print_event))
    try:
        await gateway.connect_all()
        tools = await gateway.list_tools()
        result = await gateway.call_tool(
            "orders::order.query", {"order_id": "ORD-20250902-001"}
        )
        print(json.dumps({
            "demo": "multi-server-completed",
            "health": gateway.health(),
            "aggregatedTools": [tool["name"] for tool in tools],
            "routedResult": result,
        }, ensure_ascii=False))
    finally:
        await gateway.close()
        for server, task in servers:
            await server.close()
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


async def run_governance_demo() -> None:
    client_transport, server_transport = create_memory_transport_pair()
    server = MCPServer(
        server_transport,
        name="governed-order-server",
        tool_registry=create_order_tool_registry(),
    )
    server_task = asyncio.create_task(server.serve())
    gateway = MultiServerGateway()
    gateway.register("orders", MCPClient(client_transport, print_event))
    governed = GovernedGateway(gateway)
    governed.register_policy(
        "orders::order.query", ToolPolicy(RiskLevel.READ, rate_limit=30)
    )
    governed.register_policy(
        "orders::order.cancel",
        ToolPolicy(RiskLevel.HIGH, requires_approval=True, rate_limit=5),
    )
    credentials = CredentialStore()
    credential_reference = credentials.put("server-only-demo-secret")
    try:
        await gateway.connect_all()
        pending = await governed.call_tool(
            "orders::order.cancel",
            {"order_id": "ORD-20250902-002", "reason": "用户申请取消", "token": "hidden"},
        )
        executed = await governed.decide(
            pending["approvalId"],
            approved=True,
            revised_arguments={
                "order_id": "ORD-20250902-002",
                "reason": "用户确认取消",
            },
        )
        print(json.dumps({
            "demo": "governance-completed",
            "credentialReference": credential_reference,
            "secretStayedOnServer": credentials.resolve(credential_reference)
            == "server-only-demo-secret",
            "approval": pending,
            "execution": executed,
            "audit": governed.audit_records(),
        }, ensure_ascii=False))
    finally:
        await gateway.close()
        await server.close()
        server_task.cancel()
        with suppress(asyncio.CancelledError):
            await server_task


async def _wait_for_http_server(url: str) -> None:
    async with httpx.AsyncClient(trust_env=False) as client:
        for _ in range(40):
            try:
                response = await client.get(url, timeout=0.25)
                if response.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.05)
    raise RuntimeError("HTTP MCP Server failed to start")


async def _drain_process_stderr(process: asyncio.subprocess.Process) -> None:
    if process.stderr is None:
        return
    while line := await process.stderr.readline():
        print_server_stderr(line.decode(errors="replace").rstrip())


def serve_http(port: int, session_ttl: float) -> None:
    app = create_http_app(token="lob-mcp-demo-token", session_ttl=session_ttl)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


def serve_admin(port: int, database_url: str) -> None:
    master_key = os.getenv("LOB_MCP_MASTER_KEY")
    if not master_key:
        raise RuntimeError("LOB_MCP_MASTER_KEY is required; use ./start.sh to generate it")
    app = create_management_app(database_url, master_key=master_key)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")


def print_stdio_server_event(event: ProtocolEvent) -> None:
    print(json.dumps(event.as_dict(), ensure_ascii=False), file=sys.stderr, flush=True)


async def serve_stdio() -> None:
    server = MCPServer(
        StdioServerTransport(),
        print_stdio_server_event,
        name="lob-mcp-stdio-server",
        tool_registry=create_order_tool_registry(),
        resource_registry=create_resource_registry(),
        prompt_registry=create_prompt_registry(),
    )
    await server.serve()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lob-mcp")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("demo", help="run the offline in-memory protocol demo")
    subparsers.add_parser("stdio-demo", help="run the protocol demo against a child process")
    subparsers.add_parser("tools-demo", help="discover and call the example order tool")
    subparsers.add_parser("content-demo", help="read resources and render a prompt")
    subparsers.add_parser("http-demo", help="run tools over Streamable HTTP")
    subparsers.add_parser("multi-server-demo", help="aggregate and route multiple servers")
    subparsers.add_parser("governance-demo", help="approve and audit a high-risk tool")
    subparsers.add_parser("serve-stdio", help=argparse.SUPPRESS)
    http_server = subparsers.add_parser("serve-http", help=argparse.SUPPRESS)
    http_server.add_argument("--port", type=int, default=8765)
    http_server.add_argument("--session-ttl", type=float, default=30)
    admin_server = subparsers.add_parser("serve-admin", help="run management API and UI")
    admin_server.add_argument("--port", type=int, default=8080)
    admin_server.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL", "postgresql://localhost/lob_mcp"),
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "demo":
        asyncio.run(run_demo())
    elif args.command == "stdio-demo":
        asyncio.run(run_stdio_demo())
    elif args.command == "tools-demo":
        asyncio.run(run_tools_demo())
    elif args.command == "content-demo":
        asyncio.run(run_content_demo())
    elif args.command == "http-demo":
        asyncio.run(run_http_demo())
    elif args.command == "multi-server-demo":
        asyncio.run(run_multi_server_demo())
    elif args.command == "governance-demo":
        asyncio.run(run_governance_demo())
    elif args.command == "serve-stdio":
        asyncio.run(serve_stdio())
    elif args.command == "serve-http":
        serve_http(args.port, args.session_ttl)
    elif args.command == "serve-admin":
        serve_admin(args.port, args.database_url)


if __name__ == "__main__":
    main()
