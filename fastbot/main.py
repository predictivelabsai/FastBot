from __future__ import annotations

import asyncio
import json
import re

import httpx
import uvicorn
from fasthtml.common import *
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response, StreamingResponse
from starlette.staticfiles import StaticFiles

from . import auth, credentials, db, ui
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from web.landing import landing_page
from .agent import stream_turn
from .computers import (
    human_action,
    release_control,
    request_help,
    screenshot,
    start,
    stop,
    take_control,
)
from .config import settings
from .endpoints import validate_remote_url
from .remote import proxy as remote_proxy

db.init_db()
app, rt = fast_app(hdrs=(Link(rel="stylesheet", href="/static/app.css"),),
                   secret_key=settings().fastbot_session_secret)
app.mount("/static", StaticFiles(directory="static"), name="static")


async def identity_gate(request: Request, call_next):
    public = request.url.path == "/login" or request.url.path.startswith("/static/")
    if not public and not settings().fastbot_single_user and not auth.actor(request):
        if request.url.path.startswith("/api/"):
            return JSONResponse({"error": "authentication required"}, status_code=401)
        return RedirectResponse("/login", status_code=303)
    return await call_next(request)


app.add_middleware(BaseHTTPMiddleware, dispatch=identity_gate)
# FastHTML installs SessionMiddleware first. Keep it outside the identity gate so
# signed session data is available to the authorization check.
app.user_middleware = app.user_middleware[1:] + app.user_middleware[:1]


@rt("/")
def get(request: Request):
    actor = auth.actor(request)
    return ui.home_page(actor) if actor else landing_page()


@rt("/agents")
def get(request: Request):
    return ui.agents_page(auth.actor(request))


@rt("/agents/{agent_id}/launch")
def get(request: Request, agent_id: int):
    agent = db.one("SELECT * FROM agents WHERE id=?", (agent_id,))
    if not agent:
        return JSONResponse({"error": "agent not found"}, status_code=404)
    current=auth.actor(request)
    if not current or (not current.can("admin") and agent["visibility"]!="public" and agent.get("owner_id")!=current.id): return Response("Forbidden",status_code=403)
    channel_id = db.execute("INSERT INTO channels(agent_id,title,owner_id,created_at,updated_at) VALUES(?,?,?,?,?)",
                            (agent_id, f"New channel with {agent['name']}", current.id, db.now(), db.now()))
    db.audit("channel.created", channel_id=channel_id, agent_id=agent_id)
    return RedirectResponse(f"/channel/{channel_id}", status_code=303)


@rt("/channel/{channel_id}")
def get(request: Request, channel_id: int):
    channel = db.one("SELECT * FROM channels WHERE id=?", (channel_id,))
    if not channel:
        return JSONResponse({"error": "channel not found"}, status_code=404)
    agent = db.one("SELECT * FROM agents WHERE id=?", (channel["agent_id"],))
    current=auth.actor(request)
    if not current or (not current.can("admin") and channel.get("owner_id")!=current.id): return Response("Forbidden",status_code=403)
    if not current or (not current.can("admin") and agent["visibility"]!="public" and agent.get("owner_id")!=current.id): return Response("Forbidden",status_code=403)
    messages = db.rows("SELECT * FROM messages WHERE channel_id=? ORDER BY id", (channel_id,))
    return ui.channel_page(channel, agent, messages)


async def _run(channel_id: int, message: str, thread_id: str | None = None, run_id: str | None = None,
               current=None):
    channel = db.one("SELECT * FROM channels WHERE id=?", (channel_id,))
    if not channel:
        async def missing():
            yield 'data: {"type":"RUN_ERROR","message":"Channel not found"}\n\n'
        return StreamingResponse(missing(), media_type="text/event-stream", status_code=404)
    if not current or (not current.can("admin") and channel.get("owner_id")!=current.id):
        return JSONResponse({"error":"channel access denied"},status_code=403)
    agent = db.one("SELECT * FROM agents WHERE id=?", (channel["agent_id"],))
    db.execute("INSERT INTO messages(channel_id,role,content,created_at) VALUES(?,?,?,?)", (channel_id, "user", message, db.now()))
    db.execute("UPDATE channels SET updated_at=?,title=CASE WHEN title LIKE 'New channel%' THEN ? ELSE title END WHERE id=?",
               (db.now(), message[:64], channel_id))
    if agent.get("endpoint"):
        body = {"threadId": thread_id or f"channel-{channel_id}", "runId": run_id,
                "messages": [{"id": f"user-{db.now()}", "role": "user", "content": message}],
                "forwardedProps": {"channelId": channel_id},
                "state": {"standingRole": agent["system_prompt"]}}
        return StreamingResponse(remote_proxy(agent, body), media_type="text/event-stream")
    return StreamingResponse(stream_turn(channel_id=channel_id, agent=agent, message=message, thread_id=thread_id, run_id=run_id),
                             media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@rt("/api/chat", methods=["POST"])
async def post(request: Request):
    form = await request.form()
    message = str(form.get("message") or "").strip()
    if not message:
        return JSONResponse({"error": "message is required"}, status_code=400)
    return await _run(int(form.get("channel_id") or 0), message, current=auth.actor(request))


@rt("/api/agui", methods=["POST"])
async def post(request: Request):
    """Canonical AG-UI endpoint for local and remote clients."""
    body = await request.json()
    forwarded = body.get("forwardedProps") or {}
    channel_id = int(forwarded.get("channelId") or body.get("channelId") or 0)
    messages = body.get("messages") or []
    content = messages[-1].get("content", "") if messages else body.get("message", "")
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    if not channel_id or not str(content).strip():
        return JSONResponse({"error": "channelId and a user message are required"}, status_code=400)
    return await _run(channel_id, str(content).strip(), body.get("threadId"), body.get("runId"), auth.actor(request))


@rt("/skills")
def get(request: Request):
    return ui.skills_page(auth.actor(request))


def _admin(request: Request):
    current = auth.actor(request)
    return current if current and current.can("admin") else None


@rt("/agents", methods=["POST"])
async def post(request: Request):
    current = auth.actor(request)
    if not current: return Response("Sign in required", status_code=401)
    form = await request.form()
    name = str(form.get("name") or "").strip()
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    endpoint = str(form.get("endpoint") or "").strip() or None
    if endpoint: validate_remote_url(endpoint, allow_private=settings().fastbot_single_user)
    credential_id = None
    header = str(form.get("authorization") or "").strip()
    if header: credential_id = credentials.store(f"agent-{slug}-authorization", "authorization", header, current.id)
    agent_id = db.execute("INSERT INTO agents(slug,name,title,description,system_prompt,icon,visibility,endpoint,auth_credential_id,owner_id,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                          (slug, name, str(form.get("title") or "AI coworker"), str(form.get("description") or ""), str(form.get("system_prompt") or "You are a helpful coworker."), str(form.get("icon") or "✦"), str(form.get("visibility") or "private"), endpoint, credential_id, current.id, db.now()))
    db.audit("agent.created", agent_id=agent_id, detail={"name": name, "remote": bool(endpoint)})
    return RedirectResponse("/agents", status_code=303)


@rt("/agents/{agent_id}/delete", methods=["POST"])
def post(request: Request, agent_id: int):
    if not _admin(request): return Response("Administrator required", status_code=403)
    db.execute("UPDATE agents SET deleted_at=? WHERE id=?", (db.now(), agent_id)); db.audit("agent.deleted", agent_id=agent_id)
    return RedirectResponse("/agents", status_code=303)


@rt("/agents/{agent_id}", methods=["POST"])
async def post(request: Request, agent_id: int):
    current = auth.actor(request); agent = db.one("SELECT * FROM agents WHERE id=?", (agent_id,))
    if not current or not agent or (not current.can("admin") and agent.get("owner_id") != current.id): return Response("Forbidden",status_code=403)
    form=await request.form(); endpoint=str(form.get("endpoint") or "").strip() or None
    if endpoint: validate_remote_url(endpoint,allow_private=settings().fastbot_single_user)
    db.execute("UPDATE agents SET name=?,title=?,description=?,system_prompt=?,visibility=?,endpoint=? WHERE id=?",
               (str(form.get("name")),str(form.get("title")),str(form.get("description")),str(form.get("system_prompt")),str(form.get("visibility")),endpoint,agent_id))
    db.audit("agent.updated",agent_id=agent_id); return RedirectResponse("/agents",status_code=303)


@rt("/skills", methods=["POST"])
async def post(request: Request):
    current = auth.actor(request)
    if not current: return Response("Sign in required", status_code=401)
    form = await request.form()
    db.execute("INSERT INTO skills(name,description,instructions,owner_id,scope,created_at) VALUES(?,?,?,?,?,?)",
               (str(form.get("name")), str(form.get("description")), str(form.get("instructions")), current.id, str(form.get("scope") or "personal"), db.now()))
    return RedirectResponse("/skills", status_code=303)


@rt("/skills/{skill_id}/grant/{agent_id}", methods=["POST"])
def post(request: Request, skill_id: int, agent_id: int):
    if not _admin(request): return Response("Administrator required", status_code=403)
    if db.one("SELECT 1 FROM agent_skill_grants WHERE agent_id=? AND skill_id=?",(agent_id,skill_id)):
        db.execute("DELETE FROM agent_skill_grants WHERE agent_id=? AND skill_id=?",(agent_id,skill_id))
    else: db.execute("INSERT INTO agent_skill_grants(agent_id,skill_id) VALUES(?,?)", (agent_id, skill_id))
    return RedirectResponse("/skills", status_code=303)


@rt("/skills/{skill_id}", methods=["POST"])
async def post(request: Request, skill_id: int):
    current=auth.actor(request); skill=db.one("SELECT * FROM skills WHERE id=?",(skill_id,))
    if not current or not skill or (not current.can("admin") and skill.get("owner_id") != current.id): return Response("Forbidden",status_code=403)
    form=await request.form(); db.execute("UPDATE skills SET name=?,description=?,instructions=? WHERE id=?",(str(form.get("name")),str(form.get("description")),str(form.get("instructions")),skill_id))
    return RedirectResponse("/skills",status_code=303)


@rt("/admin/audit")
def get():
    return ui.audit_page()


@rt("/admin/boundaries")
def get():
    return ui.boundaries_page()


@rt("/admin/boundaries", methods=["POST"])
async def post(request: Request):
    if not _admin(request): return Response("Administrator required", status_code=403)
    form = await request.form()
    db.execute("INSERT INTO policies(action,effect,pattern,note,created_at) VALUES(?,?,?,?,?)",
               (str(form.get("action")), str(form.get("effect")), str(form.get("pattern")), str(form.get("note") or ""), db.now()))
    db.audit("policy.created", detail={"action": form.get("action"), "effect": form.get("effect")})
    return RedirectResponse("/admin/boundaries", status_code=303)


@rt("/admin/boundaries/{rule_id}/toggle", methods=["POST"])
def post(request: Request, rule_id: int):
    if not _admin(request): return Response("Administrator required",status_code=403)
    db.execute("UPDATE policies SET enabled=CASE enabled WHEN 1 THEN 0 ELSE 1 END WHERE id=?",(rule_id,)); db.audit("policy.toggled",detail={"rule_id":rule_id})
    return RedirectResponse("/admin/boundaries",status_code=303)


@rt("/admin/computers")
def get(): return ui.computers_page()


def _computer_agent(agent_id: int): return db.one("SELECT * FROM agents WHERE id=?", (agent_id,))


@rt("/admin/computers/{agent_id}/{action}", methods=["POST"])
async def post(request: Request, agent_id: int, action: str):
    if not _admin(request): return Response("Administrator required", status_code=403)
    agent = _computer_agent(agent_id)
    if not agent: return Response("Coworker not found", status_code=404)
    if action == "start": await start(agent)
    elif action == "stop": await stop(agent)
    elif action == "take": take_control(agent)
    elif action == "release": release_control(agent)
    elif action == "help": request_help(agent, "Administrator requested intervention")
    else: return Response("Unknown action", status_code=400)
    return RedirectResponse("/admin/computers", status_code=303)


@rt("/api/computers/{agent_id}/screenshot")
async def get(request: Request, agent_id: int):
    if not auth.actor(request): return Response("Sign in required", status_code=401)
    agent = _computer_agent(agent_id)
    if not agent: return Response("Coworker not found", status_code=404)
    try: return Response(await screenshot(agent), media_type="image/png", headers={"Cache-Control": "no-store"})
    except Exception as exc: return Response(str(exc), status_code=503)


@rt("/api/computers/{agent_id}/screen")
async def get(request: Request, agent_id: int):
    if not auth.actor(request): return Response("Sign in required", status_code=401)
    agent = _computer_agent(agent_id)
    if not agent: return Response("Coworker not found", status_code=404)
    async def frames():
        while True:
            try:
                png = await screenshot(agent)
                yield b"--frame\r\nContent-Type: image/png\r\nContent-Length: " + str(len(png)).encode() + b"\r\n\r\n" + png + b"\r\n"
            except Exception:
                return
            await asyncio.sleep(1)
    return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=frame")


@rt("/api/computers/{agent_id}/action", methods=["POST"])
async def post(request: Request, agent_id: int):
    if not auth.actor(request): return Response("Sign in required",status_code=401)
    agent=_computer_agent(agent_id)
    if not agent: return Response("Coworker not found",status_code=404)
    body=await request.json()
    try: return JSONResponse(await human_action(agent,str(body.pop("action","")),**body))
    except PermissionError as exc: return JSONResponse({"error":str(exc)},status_code=409)
    except (ValueError,KeyError) as exc: return JSONResponse({"error":str(exc)},status_code=400)


@rt("/admin/credentials")
def get(request: Request):
    if not _admin(request): return Response("Administrator required", status_code=403)
    return ui.credentials_page(credentials.metadata())


@rt("/admin/credentials", methods=["POST"])
async def post(request: Request):
    current = _admin(request)
    if not current: return Response("Administrator required", status_code=403)
    form = await request.form(); credentials.store(str(form.get("name")), str(form.get("kind")), str(form.get("value")), current.id)
    return RedirectResponse("/admin/credentials", status_code=303)


@rt("/admin/components")
def get(request: Request):
    if not _admin(request): return Response("Administrator required", status_code=403)
    return ui.components_page()


@rt("/admin/components", methods=["POST"])
async def post(request: Request):
    current = _admin(request)
    if not current: return Response("Administrator required", status_code=403)
    form = await request.form(); name = re.sub(r"[^a-z0-9_-]+", "-", str(form.get("name")).lower())
    template = str(form.get("template") or name)
    if template not in {"checklist", "notice", "metric", "table"}: return Response("Unknown renderer", status_code=400)
    try: json.loads(str(form.get("schema_json") or "{}"))
    except json.JSONDecodeError: return Response("Invalid component schema JSON", status_code=400)
    db.execute("INSERT INTO components(name,title,schema_json,template,published,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
               (name, str(form.get("title")), str(form.get("schema_json") or "{}"), template, int(bool(form.get("published"))), current.id, db.now(), db.now()))
    return RedirectResponse("/admin/components", status_code=303)


@rt("/admin/components/{component_id}/withhold/{agent_id}", methods=["POST"])
def post(request: Request, component_id: int, agent_id: int):
    if not _admin(request): return Response("Administrator required", status_code=403)
    if db.one("SELECT 1 FROM component_withholds WHERE component_id=? AND agent_id=?",(component_id,agent_id)):
        db.execute("DELETE FROM component_withholds WHERE component_id=? AND agent_id=?",(component_id,agent_id)); event="component.restored"
    else:
        db.execute("INSERT INTO component_withholds(component_id,agent_id) VALUES(?,?)", (component_id, agent_id)); event="component.withheld"
    db.audit(event, agent_id=agent_id, detail={"component_id": component_id})
    return RedirectResponse("/admin/components", status_code=303)


@rt("/admin/components/{component_id}/publish", methods=["POST"])
def post(request: Request, component_id: int):
    if not _admin(request): return Response("Administrator required",status_code=403)
    db.execute("UPDATE components SET published=CASE published WHEN 1 THEN 0 ELSE 1 END,updated_at=? WHERE id=?",(db.now(),component_id))
    return RedirectResponse("/admin/components",status_code=303)


@rt("/admin/plugins")
def get(request: Request):
    if not _admin(request): return Response("Administrator required", status_code=403)
    return ui.plugins_page()


@rt("/admin/plugins", methods=["POST"])
async def post(request: Request):
    if not _admin(request): return Response("Administrator required", status_code=403)
    form = await request.form(); endpoint = validate_remote_url(str(form.get("endpoint")), allow_private=settings().fastbot_single_user)
    credential_id=int(form.get("auth_credential_id") or 0) or None
    db.execute("INSERT INTO plugins(name,transport,endpoint,auth_credential_id,created_at,updated_at) VALUES(?,?,?,?,?,?)",
               (str(form.get("name")), "http", endpoint, credential_id, db.now(), db.now()))
    return RedirectResponse("/admin/plugins", status_code=303)


@rt("/api/plugins/{plugin_id}/discover", methods=["POST"])
async def post(request: Request, plugin_id: int):
    if not _admin(request): return Response("Administrator required", status_code=403)
    plugin = db.one("SELECT * FROM plugins WHERE id=?", (plugin_id,))
    if not plugin: return Response("Plugin not found", status_code=404)
    headers = {"Accept": "application/json, text/event-stream"}
    if plugin.get("auth_credential_id"): headers["Authorization"] = credentials.reveal(plugin["auth_credential_id"])
    payload = {"jsonrpc": "2.0", "id": "fastbot-discovery", "method": "tools/list", "params": {}}
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(plugin["endpoint"], json=payload, headers=headers)
        response.raise_for_status(); data = response.json()
    tools = data.get("result", {}).get("tools", [])
    for tool in tools:
        db.execute("INSERT INTO plugin_tools(plugin_id,name,description,input_schema,risk) VALUES(?,?,?,?,?) ON CONFLICT(plugin_id,name) DO UPDATE SET description=excluded.description,input_schema=excluded.input_schema",
                   (plugin_id, tool["name"], tool.get("description", ""), json.dumps(tool.get("inputSchema", {})), "write"))
    return JSONResponse({"ok": True, "tools": len(tools)})


@rt("/api/agents/test-connection", methods=["POST"])
async def post(request: Request):
    if not _admin(request): return Response("Administrator required", status_code=403)
    body = await request.json()
    endpoint = validate_remote_url(str(body.get("endpoint")), allow_private=settings().fastbot_single_user)
    run = {"threadId": "connection-test", "runId": "connection-test", "messages": [{"id":"test","role":"user","content":"Reply with OK"}], "forwardedProps": {}}
    async with httpx.AsyncClient(timeout=15) as client:
        async with client.stream("POST", endpoint, json=run, headers={"Accept":"text/event-stream"}) as response:
            chunk = await anext(response.aiter_text(), "")
            content_type = response.headers.get("content-type", "")
            return JSONResponse({"ok": response.status_code < 400 and "text/event-stream" in content_type and "data:" in chunk, "status": response.status_code})


@rt("/admin/plugins/{plugin_id}/tools", methods=["POST"])
async def post(request: Request, plugin_id: int):
    if not _admin(request): return Response("Administrator required", status_code=403)
    form = await request.form()
    db.execute("INSERT INTO plugin_tools(plugin_id,name,description,input_schema,risk) VALUES(?,?,?,?,?)",
               (plugin_id, str(form.get("name")), str(form.get("description") or ""), str(form.get("input_schema") or "{}"), str(form.get("risk") or "write")))
    return RedirectResponse("/admin/plugins", status_code=303)


@rt("/admin/plugins/tools/{tool_id}/grant/{agent_id}", methods=["POST"])
def post(request: Request, tool_id: int, agent_id: int):
    if not _admin(request): return Response("Administrator required", status_code=403)
    if db.one("SELECT 1 FROM agent_tool_grants WHERE agent_id=? AND tool_id=?",(agent_id,tool_id)):
        db.execute("DELETE FROM agent_tool_grants WHERE agent_id=? AND tool_id=?",(agent_id,tool_id))
    else: db.execute("INSERT INTO agent_tool_grants(agent_id,tool_id) VALUES(?,?)", (agent_id, tool_id))
    return RedirectResponse("/admin/plugins", status_code=303)


@rt("/admin/people")
def get(request: Request):
    if not _admin(request): return Response("Administrator required", status_code=403)
    return ui.people_page()


@rt("/admin/people", methods=["POST"])
async def post(request: Request):
    if not _admin(request): return Response("Administrator required", status_code=403)
    form = await request.form(); password = str(form.get("password") or "")
    db.execute("INSERT INTO users(email,name,role,password_hash,created_at) VALUES(?,?,?,?,?)",
               (str(form.get("email")).lower(), str(form.get("name")), str(form.get("role") or "member"), auth.hash_password(password) if password else None, db.now()))
    return RedirectResponse("/admin/people", status_code=303)


@rt("/admin/people/{user_id}/role", methods=["POST"])
async def post(request: Request, user_id: int):
    if not _admin(request): return Response("Administrator required", status_code=403)
    form = await request.form(); role = str(form.get("role"))
    if role not in {"member", "admin"}: return Response("Invalid role", status_code=400)
    db.execute("UPDATE users SET role=? WHERE id=?", (role, user_id))
    db.audit("person.role_changed", detail={"user_id": user_id, "role": role})
    return RedirectResponse("/admin/people", status_code=303)


@rt("/login")
def get(): return ui.login_page()


@rt("/login", methods=["POST"])
async def post(request: Request):
    form = await request.form(); current = auth.authenticate(str(form.get("email")), str(form.get("password")))
    if not current: return Response("Invalid credentials", status_code=401)
    request.session["user_id"] = current.id
    return RedirectResponse("/", status_code=303)


@rt("/logout", methods=["POST"])
def post(request: Request):
    request.session.clear(); return RedirectResponse("/login", status_code=303)


def run() -> None:
    cfg = settings()
    uvicorn.run("fastbot.main:app", host=cfg.fastbot_host, port=cfg.fastbot_port, reload=False)


if __name__ == "__main__":
    run()
