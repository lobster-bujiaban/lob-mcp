from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable, Sequence
from contextlib import suppress

from lob_mcp.transport.base import TransportClosed

StderrSink = Callable[[str], None]


class StdioProcessTransport:
    """Client-side transport backed by a child process's stdin and stdout."""

    def __init__(
        self,
        process: asyncio.subprocess.Process,
        stderr_sink: StderrSink | None = None,
    ) -> None:
        if process.stdin is None or process.stdout is None or process.stderr is None:
            raise ValueError("child process must use pipes for stdin, stdout and stderr")
        self._process = process
        self._stdin = process.stdin
        self._stdout = process.stdout
        self._stderr = process.stderr
        self._stderr_sink = stderr_sink
        self._stderr_task = asyncio.create_task(self._drain_stderr())
        self._closed = False

    @classmethod
    async def start(
        cls,
        command: Sequence[str],
        stderr_sink: StderrSink | None = None,
    ) -> StdioProcessTransport:
        if not command:
            raise ValueError("stdio server command cannot be empty")
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        return cls(process, stderr_sink)

    @property
    def pid(self) -> int:
        return self._process.pid

    async def send(self, payload: bytes) -> None:
        if self._closed or self._process.returncode is not None:
            raise TransportClosed(self._exit_message())
        self._stdin.write(payload + b"\n")
        try:
            await self._stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as exc:
            raise TransportClosed(self._exit_message()) from exc

    async def receive(self) -> bytes:
        payload = await self._stdout.readline()
        if not payload:
            await self._process.wait()
            raise TransportClosed(self._exit_message())
        return payload.rstrip(b"\r\n")

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if not self._stdin.is_closing():
            self._stdin.close()
            with suppress(BrokenPipeError, ConnectionResetError):
                await self._stdin.wait_closed()
        try:
            await asyncio.wait_for(self._process.wait(), timeout=2)
        except TimeoutError:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=2)
            except TimeoutError:
                self._process.kill()
                await self._process.wait()
        await self._stderr_task

    async def _drain_stderr(self) -> None:
        while line := await self._stderr.readline():
            if self._stderr_sink is not None:
                self._stderr_sink(line.decode("utf-8", errors="replace").rstrip())

    def _exit_message(self) -> str:
        returncode = self._process.returncode
        if returncode is None:
            return "stdio transport is closed"
        return f"stdio server exited with code {returncode}"


class StdioServerTransport:
    """Server-side line-delimited transport over the current process stdio."""

    def __init__(self) -> None:
        self._closed = False

    async def send(self, payload: bytes) -> None:
        if self._closed:
            raise TransportClosed("stdio server transport is closed")

        def write() -> None:
            sys.stdout.buffer.write(payload + b"\n")
            sys.stdout.buffer.flush()

        await asyncio.to_thread(write)

    async def receive(self) -> bytes:
        if self._closed:
            raise TransportClosed("stdio server transport is closed")
        payload = await asyncio.to_thread(sys.stdin.buffer.readline)
        if not payload:
            raise TransportClosed("stdin was closed")
        return payload.rstrip(b"\r\n")

    async def close(self) -> None:
        self._closed = True

