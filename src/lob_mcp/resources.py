from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class TextResource:
    uri: str
    name: str
    description: str
    text: str
    mime_type: str = "text/plain"

    def definition(self) -> dict[str, Any]:
        return {
            "uri": self.uri,
            "name": self.name,
            "description": self.description,
            "mimeType": self.mime_type,
        }

    def content(self) -> dict[str, Any]:
        return {"uri": self.uri, "mimeType": self.mime_type, "text": self.text}


class ResourceRegistry:
    def __init__(self) -> None:
        self._resources: dict[str, TextResource] = {}
        self._templates: list[dict[str, Any]] = []

    def register(self, resource: TextResource) -> None:
        if resource.uri in self._resources:
            raise ValueError(f"resource already registered: {resource.uri}")
        self._resources[resource.uri] = resource

    def register_template(
        self,
        *,
        uri_template: str,
        name: str,
        description: str,
        mime_type: str = "text/plain",
    ) -> None:
        self._templates.append(
            {
                "uriTemplate": uri_template,
                "name": name,
                "description": description,
                "mimeType": mime_type,
            }
        )

    def list_resources(self) -> list[dict[str, Any]]:
        return [resource.definition() for resource in self._resources.values()]

    def list_templates(self) -> list[dict[str, Any]]:
        return list(self._templates)

    def read(self, uri: str) -> dict[str, Any]:
        resource = self._resources.get(uri)
        if resource is None:
            raise ValueError(f"unknown resource: {uri}")
        return {"contents": [resource.content()]}

