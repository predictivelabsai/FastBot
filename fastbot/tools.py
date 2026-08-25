from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, create_model

from . import db
from .computers import (
    agent_action,
    aread_file,
    arun_shell,
    awrite_file,
    navigate,
    request_help,
    snapshot,
)
from .credentials import reveal


class Empty(BaseModel): pass
class ChecklistInput(BaseModel):
    title: str
    items: list[str]
class NavigateInput(BaseModel): url: str
class FileReadInput(BaseModel): path: str
class FileWriteInput(BaseModel):
    path: str
    content: str
class ShellInput(BaseModel): command: str
class HelpInput(BaseModel): reason: str
class ClickInput(BaseModel): selector: str
class TypeInput(BaseModel):
    selector: str
    text: str
class RenderInput(BaseModel):
    component: str
    props: dict

def tools_for(agent: dict, channel_id: int) -> list[StructuredTool]:
    async def current_time() -> str: return datetime.now(UTC).isoformat(timespec="seconds")
    async def create_checklist(title: str, items: list[str]) -> dict: return {"kind": "checklist", "title": title, "items": items[:12]}
    async def browser_navigate(url: str) -> dict:
        result = await navigate(agent, url, channel_id); result["page"] = await snapshot(agent); return result
    async def browser_click(selector: str) -> dict: return await agent_action(agent,"click",channel_id,selector=selector)
    async def browser_type(selector: str,text: str) -> dict: return await agent_action(agent,"type",channel_id,selector=selector,text=text)
    async def workspace_read(path: str) -> str: return await aread_file(agent, path, channel_id)
    async def workspace_write(path: str, content: str) -> str: return await awrite_file(agent, path, content, channel_id)
    async def shell_run(command: str) -> dict: return await arun_shell(agent, command, channel_id)
    async def ask_human(reason: str) -> str:
        request_help(agent, reason); return "Human help requested; execution is paused until control is released."
    async def render_component(component: str, props: dict) -> dict:
        allowed = db.one("SELECT name FROM components WHERE name=? AND published=1 AND id NOT IN (SELECT component_id FROM component_withholds WHERE agent_id=?)", (component, agent["id"]))
        if not allowed: raise PermissionError("Component is not published or is withheld from this coworker")
        return {"kind": component, **props}
    result = [
        StructuredTool.from_function(coroutine=current_time, name="current_time", description="Current UTC time", args_schema=Empty),
        StructuredTool.from_function(coroutine=create_checklist, name="create_checklist", description="Render an interactive checklist", args_schema=ChecklistInput),
        StructuredTool.from_function(coroutine=browser_navigate, name="browser_navigate", description="Open an allowed public HTTPS page in this coworker's isolated browser", args_schema=NavigateInput),
        StructuredTool.from_function(coroutine=browser_click,name="browser_click",description="Click the first element matching a CSS selector",args_schema=ClickInput),
        StructuredTool.from_function(coroutine=browser_type,name="browser_type",description="Fill the first element matching a CSS selector",args_schema=TypeInput),
        StructuredTool.from_function(coroutine=workspace_read, name="workspace_read", description="Read a UTF-8 file from this coworker's workspace", args_schema=FileReadInput),
        StructuredTool.from_function(coroutine=workspace_write, name="workspace_write", description="Write a UTF-8 file inside this coworker's workspace", args_schema=FileWriteInput),
        StructuredTool.from_function(coroutine=shell_run, name="shell_run", description="Run an explicitly policy-allowed command in the coworker workspace", args_schema=ShellInput),
        StructuredTool.from_function(coroutine=ask_human, name="ask_human", description="Pause and request human help", args_schema=HelpInput),
        StructuredTool.from_function(coroutine=render_component, name="render_component", description="Render a published generative UI component with structured props", args_schema=RenderInput),
    ]
    query = "SELECT t.*,p.endpoint,p.auth_credential_id,p.name plugin_name FROM plugin_tools t JOIN plugins p ON p.id=t.plugin_id JOIN agent_tool_grants g ON g.tool_id=t.id WHERE g.agent_id=? AND p.enabled=1"
    result.extend(_mcp_tool(spec, channel_id, agent["id"]) for spec in db.rows(query, (agent["id"],)))
    return result

def _mcp_tool(spec: dict, channel_id: int, agent_id: int) -> StructuredTool:
    schema = json.loads(spec["input_schema"] or "{}")
    fields = {name: (object, Field(default=None, description=value.get("description", ""))) for name, value in schema.get("properties", {}).items()}
    input_model = create_model(f"MCP_{spec['id']}", **fields)
    async def call(**kwargs):
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if spec.get("auth_credential_id"): headers["Authorization"] = reveal(spec["auth_credential_id"])
        payload = {"jsonrpc": "2.0", "id": f"fastbot-{datetime.now(UTC).timestamp()}", "method": "tools/call", "params": {"name": spec["name"], "arguments": kwargs}}
        db.audit("mcp.tool.started", channel_id=channel_id, agent_id=agent_id, action=spec["name"], detail={"plugin": spec["plugin_name"]})
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(spec["endpoint"], json=payload, headers=headers); response.raise_for_status(); data = response.json()
        if "error" in data: raise RuntimeError(data["error"].get("message", "MCP tool failed"))
        return data.get("result")
    return StructuredTool.from_function(coroutine=call, name=f"mcp_{spec['plugin_name']}_{spec['name']}", description=spec["description"] or f"MCP tool {spec['name']}", args_schema=input_model)
