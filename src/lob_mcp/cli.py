from __future__ import annotations

import argparse
import asyncio
import json
import sys
from contextlib import suppress

from lob_mcp.client import MCPClient
from lob_mcp.events import ProtocolEvent
from lob_mcp.examples.order import create_order_tool_registry
from lob_mcp.server import MCPServer
from lob_mcp.transport import (
    StdioProcessTransport,
    StdioServerTransport,
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


def print_stdio_server_event(event: ProtocolEvent) -> None:
    print(json.dumps(event.as_dict(), ensure_ascii=False), file=sys.stderr, flush=True)


async def serve_stdio() -> None:
    server = MCPServer(
        StdioServerTransport(),
        print_stdio_server_event,
        name="lob-mcp-stdio-server",
        tool_registry=create_order_tool_registry(),
    )
    await server.serve()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lob-mcp")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("demo", help="run the offline in-memory protocol demo")
    subparsers.add_parser("stdio-demo", help="run the protocol demo against a child process")
    subparsers.add_parser("tools-demo", help="discover and call the example order tool")
    subparsers.add_parser("serve-stdio", help=argparse.SUPPRESS)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "demo":
        asyncio.run(run_demo())
    elif args.command == "stdio-demo":
        asyncio.run(run_stdio_demo())
    elif args.command == "tools-demo":
        asyncio.run(run_tools_demo())
    elif args.command == "serve-stdio":
        asyncio.run(serve_stdio())


if __name__ == "__main__":
    main()
