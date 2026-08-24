import json

from fastbot.agui import EventType, event, generative_ui


def payload(frame: str) -> dict:
    return json.loads(frame.removeprefix("data: ").strip())


def test_canonical_event_frame():
    value = payload(event(EventType.RUN_STARTED, threadId="thread-1", runId="run-1"))
    assert value == {"type": "RUN_STARTED", "threadId": "thread-1", "runId": "run-1"}


def test_generative_ui_is_custom_agui_event():
    value = payload(generative_ui("checklist.created", "checklist", {"items": ["Review"]}))
    assert value["type"] == "CUSTOM"
    assert value["value"]["component"] == "checklist"
