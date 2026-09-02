from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

ToolHandler = Any


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    input_model: type[BaseModel]
    handler: ToolHandler

    def protocol_definition(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_model.model_json_schema(),
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(
        self,
        *,
        name: str,
        description: str,
        input_model: type[BaseModel],
        handler: ToolHandler,
    ) -> None:
        if name in self._tools:
            raise ValueError(f"tool already registered: {name}")
        self._tools[name] = ToolDefinition(name, description, input_model, handler)

    def list_tools(self) -> list[dict[str, Any]]:
        return [tool.protocol_definition() for tool in self._tools.values()]

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        tool = self._tools.get(name)
        if tool is None:
            return self._error_result(f"unknown tool: {name}")

        try:
            validated = tool.input_model.model_validate(arguments)
        except ValidationError as exc:
            return self._error_result(
                "invalid tool arguments",
                {"validationErrors": exc.errors(include_url=False)},
            )

        try:
            result = tool.handler(validated)
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:
            return self._error_result(f"tool execution failed: {exc}")

        structured = result.model_dump(mode="json") if isinstance(result, BaseModel) else result
        return {
            "content": [{"type": "text", "text": self._text(result)}],
            "structuredContent": structured,
            "isError": False,
        }

    @staticmethod
    def _error_result(message: str, structured: Any = None) -> dict[str, Any]:
        result: dict[str, Any] = {
            "content": [{"type": "text", "text": message}],
            "isError": True,
        }
        if structured is not None:
            result["structuredContent"] = structured
        return result

    @staticmethod
    def _text(result: Any) -> str:
        if isinstance(result, BaseModel):
            return result.model_dump_json()
        if isinstance(result, str):
            return result
        import json

        return json.dumps(result, ensure_ascii=False)
