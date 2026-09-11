from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError


@dataclass(frozen=True, slots=True)
class PromptDefinition:
    name: str
    description: str
    arguments_model: type[BaseModel]
    renderer: Any

    def definition(self) -> dict[str, Any]:
        schema = self.arguments_model.model_json_schema()
        required = set(schema.get("required", []))
        arguments = []
        for name, field in schema.get("properties", {}).items():
            arguments.append(
                {
                    "name": name,
                    "description": field.get("description", ""),
                    "required": name in required,
                }
            )
        return {"name": self.name, "description": self.description, "arguments": arguments}


class PromptRegistry:
    def __init__(self) -> None:
        self._prompts: dict[str, PromptDefinition] = {}

    def register(
        self,
        *,
        name: str,
        description: str,
        arguments_model: type[BaseModel],
        renderer: Any,
    ) -> None:
        if name in self._prompts:
            raise ValueError(f"prompt already registered: {name}")
        self._prompts[name] = PromptDefinition(
            name, description, arguments_model, renderer
        )

    def list_prompts(self) -> list[dict[str, Any]]:
        return [prompt.definition() for prompt in self._prompts.values()]

    def get(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        prompt = self._prompts.get(name)
        if prompt is None:
            raise ValueError(f"unknown prompt: {name}")
        try:
            validated = prompt.arguments_model.model_validate(arguments)
        except ValidationError as exc:
            raise ValueError(
                f"invalid prompt arguments: {exc.errors(include_url=False)}"
            ) from exc
        text = prompt.renderer(validated)
        return {
            "description": prompt.description,
            "messages": [{"role": "user", "content": {"type": "text", "text": text}}],
        }

