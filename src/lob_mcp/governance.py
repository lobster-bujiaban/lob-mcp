from __future__ import annotations

import time
import uuid
from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any
from urllib.parse import urlparse

from cryptography.fernet import Fernet

from lob_mcp.gateway import MultiServerGateway


class RiskLevel(StrEnum):
    READ = "read"
    WRITE = "write"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class ToolPolicy:
    risk_level: RiskLevel
    requires_approval: bool = False
    rate_limit: int = 20
    max_result_chars: int = 10_000
    allowed_domains: tuple[str, ...] = ()


@dataclass(slots=True)
class PendingApproval:
    approval_id: str
    tool_name: str
    arguments: dict[str, Any]
    created_at: float


@dataclass(frozen=True, slots=True)
class AuditRecord:
    trace_id: str
    tool_name: str
    risk_level: str
    arguments: dict[str, Any]
    status: str
    duration_ms: float
    approval_id: str | None = None
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}


class CredentialStore:
    """Keeps encrypted credentials behind opaque references."""

    def __init__(self, key: bytes | None = None) -> None:
        self._cipher = Fernet(key or Fernet.generate_key())
        self._encrypted: dict[str, bytes] = {}

    def put(self, secret: str) -> str:
        reference = f"cred_{uuid.uuid4().hex}"
        self._encrypted[reference] = self._cipher.encrypt(secret.encode())
        return reference

    def resolve(self, reference: str) -> str:
        encrypted = self._encrypted.get(reference)
        if encrypted is None:
            raise KeyError("credential reference not found")
        return self._cipher.decrypt(encrypted).decode()


class GovernedGateway:
    SENSITIVE_KEYS = {"password", "token", "secret", "api_key", "authorization"}

    def __init__(self, gateway: MultiServerGateway) -> None:
        self._gateway = gateway
        self._policies: dict[str, ToolPolicy] = {}
        self._pending: dict[str, PendingApproval] = {}
        self._calls: dict[str, deque[float]] = defaultdict(deque)
        self._audit: list[AuditRecord] = []

    def register_policy(self, tool_name: str, policy: ToolPolicy) -> None:
        self._policies[tool_name] = policy

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        policy = self._require_policy(tool_name)
        self._check_rate_limit(tool_name, policy)
        self._validate_domains(arguments, policy.allowed_domains)
        if policy.requires_approval:
            approval_id = uuid.uuid4().hex
            self._pending[approval_id] = PendingApproval(
                approval_id, tool_name, dict(arguments), time.time()
            )
            self._record(
                tool_name,
                policy,
                arguments,
                "awaiting_approval",
                0,
                approval_id=approval_id,
            )
            return {
                "status": "awaiting_approval",
                "approvalId": approval_id,
                "tool": tool_name,
                "arguments": self._redact(arguments),
            }
        return await self._execute(tool_name, arguments, policy)

    async def decide(
        self,
        approval_id: str,
        *,
        approved: bool,
        revised_arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        pending = self._pending.pop(approval_id, None)
        if pending is None:
            raise ValueError("unknown or completed approval")
        policy = self._require_policy(pending.tool_name)
        arguments = revised_arguments if revised_arguments is not None else pending.arguments
        self._validate_domains(arguments, policy.allowed_domains)
        if not approved:
            self._record(
                pending.tool_name,
                policy,
                arguments,
                "rejected",
                0,
                approval_id=approval_id,
            )
            return {"status": "rejected", "approvalId": approval_id}
        return await self._execute(
            pending.tool_name, arguments, policy, approval_id=approval_id
        )

    def audit_records(self) -> list[dict[str, Any]]:
        return [record.as_dict() for record in self._audit]

    async def _execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        policy: ToolPolicy,
        approval_id: str | None = None,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            result = await self._gateway.call_tool(tool_name, arguments)
            result = self._trim_result(result, policy.max_result_chars)
            status = "failed" if result.get("isError") else "succeeded"
            error = result["content"][0]["text"] if status == "failed" else None
        except Exception as exc:
            result = {"status": "failed", "error": str(exc)}
            status = "failed"
            error = str(exc)
        duration_ms = (time.perf_counter() - started) * 1000
        self._record(
            tool_name,
            policy,
            arguments,
            status,
            duration_ms,
            approval_id=approval_id,
            error=error,
        )
        return {"status": status, "result": result, "approvalId": approval_id}

    def _check_rate_limit(self, tool_name: str, policy: ToolPolicy) -> None:
        now = time.monotonic()
        calls = self._calls[tool_name]
        while calls and now - calls[0] >= 60:
            calls.popleft()
        if len(calls) >= policy.rate_limit:
            raise RuntimeError(f"rate limit exceeded for {tool_name}")
        calls.append(now)

    def _record(
        self,
        tool_name: str,
        policy: ToolPolicy,
        arguments: dict[str, Any],
        status: str,
        duration_ms: float,
        *,
        approval_id: str | None = None,
        error: str | None = None,
    ) -> None:
        self._audit.append(
            AuditRecord(
                trace_id=uuid.uuid4().hex,
                tool_name=tool_name,
                risk_level=policy.risk_level,
                arguments=self._redact(arguments),
                status=status,
                duration_ms=round(duration_ms, 3),
                approval_id=approval_id,
                error=error,
            )
        )

    def _require_policy(self, tool_name: str) -> ToolPolicy:
        policy = self._policies.get(tool_name)
        if policy is None:
            raise PermissionError(f"tool has no governance policy: {tool_name}")
        return policy

    @classmethod
    def _validate_domains(cls, value: Any, allowed_domains: tuple[str, ...]) -> None:
        if not allowed_domains:
            return
        if isinstance(value, dict):
            for item in value.values():
                cls._validate_domains(item, allowed_domains)
        elif isinstance(value, list):
            for item in value:
                cls._validate_domains(item, allowed_domains)
        elif isinstance(value, str) and value.startswith(("http://", "https://")):
            hostname = urlparse(value).hostname
            if hostname not in allowed_domains:
                raise PermissionError(f"domain is not allowed: {hostname}")

    @classmethod
    def _redact(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: "***" if key.lower() in cls.SENSITIVE_KEYS else cls._redact(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [cls._redact(item) for item in value]
        return value

    @staticmethod
    def _trim_result(result: dict[str, Any], limit: int) -> dict[str, Any]:
        content = result.get("content")
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    text = item["text"]
                    if len(text) > limit:
                        item["text"] = text[:limit] + "…[truncated]"
        return result
