from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class ProtocolEvent:
    timestamp: str
    actor: str
    direction: str
    message_type: str
    method: str | None = None
    request_id: int | str | None = None

    @classmethod
    def create(
        cls,
        *,
        actor: str,
        direction: str,
        message_type: str,
        method: str | None = None,
        request_id: int | str | None = None,
    ) -> ProtocolEvent:
        return cls(
            timestamp=datetime.now(UTC).isoformat(),
            actor=actor,
            direction=direction,
            message_type=message_type,
            method=method,
            request_id=request_id,
        )

    def as_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}


class EventSink(Protocol):
    def __call__(self, event: ProtocolEvent) -> None: ...


def discard_event(event: ProtocolEvent) -> None:
    del event

