from __future__ import annotations

import json
from typing import Any, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, ValidationError

JSONRPCId: TypeAlias = int | str


class JSONRPCModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    jsonrpc: str = Field(default="2.0", pattern=r"^2\.0$")


class JSONRPCRequest(JSONRPCModel):
    id: JSONRPCId
    method: str = Field(min_length=1)
    params: dict[str, Any] | list[Any] | None = None


class JSONRPCNotification(JSONRPCModel):
    method: str = Field(min_length=1)
    params: dict[str, Any] | list[Any] | None = None


class JSONRPCResponse(JSONRPCModel):
    id: JSONRPCId
    result: Any = None


class JSONRPCError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: int
    message: str
    data: Any = None


class JSONRPCErrorResponse(JSONRPCModel):
    id: JSONRPCId | None
    error: JSONRPCError


JSONRPCMessage: TypeAlias = (
    JSONRPCRequest | JSONRPCNotification | JSONRPCResponse | JSONRPCErrorResponse
)


def encode_message(message: JSONRPCMessage) -> bytes:
    return message.model_dump_json(exclude_none=True).encode("utf-8")


def decode_message(payload: bytes) -> JSONRPCMessage:
    try:
        raw = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid JSON-RPC JSON") from exc

    if not isinstance(raw, dict):
        raise ValueError("JSON-RPC message must be an object")

    try:
        if "method" in raw:
            model = JSONRPCRequest if "id" in raw else JSONRPCNotification
        elif "error" in raw:
            model = JSONRPCErrorResponse
        elif "result" in raw:
            model = JSONRPCResponse
        else:
            raise ValueError("unknown JSON-RPC message shape")
        return model.model_validate(raw)
    except ValidationError as exc:
        raise ValueError("invalid JSON-RPC message") from exc

