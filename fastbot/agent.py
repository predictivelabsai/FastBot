from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent

from . import db
from .agui import EventType, event, generative_ui
from .config import settings
from .tools import tools_for


@lru_cache
def model() -> ChatOpenAI:
    cfg = settings()
    if not cfg.xai_api_key:
        raise RuntimeError("XAI_API_KEY is not configured")
    return ChatOpenAI(model=cfg.model_name, api_key=cfg.xai_api_key, base_url=cfg.xai_base_url,
                      streaming=True, temperature=0.2, timeout=90)


def graph(prompt: str, agent: dict, channel_id: int):
    return create_react_agent(model(), tools=tools_for(agent, channel_id), prompt=prompt,
                              checkpointer=MemorySaver())


def history(channel_id: int) -> list[Any]:
    result = []
    for item in db.rows("SELECT role,content FROM messages WHERE channel_id=? ORDER BY id", (channel_id,))[-30:]:
        cls = HumanMessage if item["role"] == "user" else AIMessage
        result.append(cls(content=item["content"]))
    return result


def audit_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: ({"redacted": True, "length": len(str(item))} if key.lower() in {"text","content","password","secret","authorization","api_key"} else audit_safe(item)) for key,item in value.items()}
    if isinstance(value, list): return [audit_safe(item) for item in value[:20]]
    text=str(value)
    return text[:500] + ("…" if len(text)>500 else "")


def audit_result(value: Any) -> Any:
    if isinstance(value,str): return {"type":"text","length":len(value)}
    return audit_safe(value)


async def stream_turn(*, channel_id: int, agent: dict[str, Any], message: str,
                      thread_id: str | None = None, run_id: str | None = None) -> AsyncIterator[str]:
    thread_id = thread_id or f"channel-{channel_id}"
    run_id = run_id or uuid.uuid4().hex
    message_id = uuid.uuid4().hex
    db.audit("run.started", channel_id=channel_id, agent_id=agent["id"], detail={"run_id": run_id})
    yield event(EventType.RUN_STARTED, threadId=thread_id, runId=run_id)
    yield event(EventType.STATE_SNAPSHOT, snapshot={"channelId": channel_id, "agent": agent["slug"], "status": "thinking"})
    yield event(EventType.TEXT_MESSAGE_START, messageId=message_id, role="assistant")

    accumulated: list[str] = []
    tool_names: dict[str, str] = {}
    try:
        if not settings().xai_api_key:
            fallback = ("FastBot is ready, but `XAI_API_KEY` is not available in this process. "
                        "Add it to `.env` and restart; AG-UI, channels, policies, and audit remain usable.")
            accumulated.append(fallback)
            yield event(EventType.TEXT_MESSAGE_CONTENT, messageId=message_id, delta=fallback)
        else:
            inputs = {"messages": history(channel_id) + [HumanMessage(content=message)]}
            config = {"configurable": {"thread_id": thread_id}}
            skills = db.rows("SELECT s.instructions FROM skills s JOIN agent_skill_grants g ON g.skill_id=s.id WHERE g.agent_id=? AND s.enabled=1", (agent["id"],))
            prompt = agent["system_prompt"] + "".join(f"\n\nSkill instructions:\n{s['instructions']}" for s in skills)
            async for item in graph(prompt, agent, channel_id).astream_events(inputs, config=config, version="v2"):
                kind = item.get("event")
                data = item.get("data", {})
                if kind == "on_chat_model_stream":
                    chunk = data.get("chunk")
                    text = getattr(chunk, "content", "")
                    if isinstance(text, str) and text and not getattr(chunk, "tool_call_chunks", None):
                        accumulated.append(text)
                        yield event(EventType.TEXT_MESSAGE_CONTENT, messageId=message_id, delta=text)
                elif kind == "on_tool_start":
                    call_id = item.get("run_id", uuid.uuid4().hex)
                    name = item.get("name", "tool")
                    tool_names[call_id] = name
                    yield event(EventType.TOOL_CALL_START, toolCallId=call_id, toolCallName=name, parentMessageId=message_id)
                    yield event(EventType.TOOL_CALL_ARGS, toolCallId=call_id, delta=json.dumps(data.get("input", {}), default=str))
                    db.audit("tool.started", channel_id=channel_id, agent_id=agent["id"], action=name, detail=audit_safe(data.get("input", {})))
                elif kind == "on_tool_end":
                    call_id = item.get("run_id", "")
                    output = data.get("output")
                    content = getattr(output, "content", output)
                    yield event(EventType.TOOL_CALL_END, toolCallId=call_id)
                    yield event(EventType.TOOL_CALL_RESULT, messageId=uuid.uuid4().hex, toolCallId=call_id,
                                content=json.dumps(content, default=str))
                    db.audit("tool.finished", channel_id=channel_id, agent_id=agent["id"], action=tool_names.get(call_id), detail={"result": audit_result(content)})
                    if tool_names.get(call_id) == "ask_human":
                        yield event(EventType.CUSTOM, name="human_interrupt", value={"agentId": agent["id"], "message": str(content)})
                        yield event(EventType.STATE_SNAPSHOT, snapshot={"channelId": channel_id, "agent": agent["slug"], "status": "interrupted", "control": "waiting"})
                    if isinstance(content, str):
                        try:
                            parsed = json.loads(content)
                        except json.JSONDecodeError:
                            parsed = None
                        if isinstance(parsed, dict) and parsed.get("kind"):
                            component = db.one("SELECT id,template FROM components WHERE name=? AND published=1 AND id NOT IN (SELECT component_id FROM component_withholds WHERE agent_id=?)", (parsed["kind"], agent["id"]))
                            if component: yield generative_ui(f"{parsed['kind']}.created", component["template"], parsed)
        final = "".join(accumulated) or "Done."
        db.execute("INSERT INTO messages(channel_id,role,content,created_at) VALUES(?,?,?,?)", (channel_id, "assistant", final, db.now()))
        yield event(EventType.TEXT_MESSAGE_END, messageId=message_id)
        yield event(EventType.STATE_SNAPSHOT, snapshot={"channelId": channel_id, "agent": agent["slug"], "status": "idle"})
        yield event(EventType.RUN_FINISHED, threadId=thread_id, runId=run_id)
        db.audit("run.finished", channel_id=channel_id, agent_id=agent["id"], detail={"run_id": run_id})
    except Exception as exc:
        yield event(EventType.TEXT_MESSAGE_END, messageId=message_id)
        yield event(EventType.RUN_ERROR, message=str(exc), code="AGENT_RUN_FAILED")
        db.audit("run.failed", channel_id=channel_id, agent_id=agent["id"], decision="failed", detail={"error": str(exc)})
