from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class EventType(StrEnum):
    RUN_STARTED = "RUN_STARTED"
    RUN_FINISHED = "RUN_FINISHED"
    RUN_ERROR = "RUN_ERROR"
    TEXT_MESSAGE_START = "TEXT_MESSAGE_START"
    TEXT_MESSAGE_CONTENT = "TEXT_MESSAGE_CONTENT"
    TEXT_MESSAGE_END = "TEXT_MESSAGE_END"
    TOOL_CALL_START = "TOOL_CALL_START"
    TOOL_CALL_ARGS = "TOOL_CALL_ARGS"
    TOOL_CALL_END = "TOOL_CALL_END"
    TOOL_CALL_RESULT = "TOOL_CALL_RESULT"
    STATE_SNAPSHOT = "STATE_SNAPSHOT"
    CUSTOM = "CUSTOM"


@dataclass
class Event:
    type: EventType
    data: dict[str, Any]

    def wire(self) -> str:
        payload = {"type": self.type.value, **self.data}
        return f"data: {json.dumps(payload, default=str, separators=(',', ':'))}\n\n"


def event(kind: EventType, **data: Any) -> str:
    return Event(kind, data).wire()


def generative_ui(name: str, component: str, props: dict[str, Any]) -> str:
    return event(EventType.CUSTOM, name=name, value={"component": component, "props": props})
