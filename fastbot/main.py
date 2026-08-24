from __future__ import annotations

import uvicorn
from fasthtml.common import Link, fast_app
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, StreamingResponse
from starlette.staticfiles import StaticFiles

from . import db, ui
from .agent import stream_turn
from .computers import inspect
from .config import settings

db.init_db()
app, rt = fast_app(hdrs=(Link(rel="stylesheet", href="/static/app.css"),),
                   secret_key=settings().fastbot_session_secret)
app.mount("/static", StaticFiles(directory="static"), name="static")


@rt("/")
def get():
    return ui.home_page()


@rt("/agents")
def get():
    return ui.agents_page()


@rt("/agents/{agent_id}/launch")
def get(agent_id: int):
    agent = db.one("SELECT * FROM agents WHERE id=?", (agent_id,))
    if not agent:
        return JSONResponse({"error": "agent not found"}, status_code=404)
    channel_id = db.execute("INSERT INTO channels(agent_id,title,created_at,updated_at) VALUES(?,?,?,?)",
                            (agent_id, f"New channel with {agent['name']}", db.now(), db.now()))
    db.audit("channel.created", channel_id=channel_id, agent_id=agent_id)
    return RedirectResponse(f"/channel/{channel_id}", status_code=303)


@rt("/channel/{channel_id}")
def get(channel_id: int):
    channel = db.one("SELECT * FROM channels WHERE id=?", (channel_id,))
    if not channel:
        return JSONResponse({"error": "channel not found"}, status_code=404)
    agent = db.one("SELECT * FROM agents WHERE id=?", (channel["agent_id"],))
    messages = db.rows("SELECT * FROM messages WHERE channel_id=? ORDER BY id", (channel_id,))
    return ui.channel_page(channel, agent, messages)


async def _run(channel_id: int, message: str, thread_id: str | None = None, run_id: str | None = None):
    channel = db.one("SELECT * FROM channels WHERE id=?", (channel_id,))
    if not channel:
        async def missing():
            yield 'data: {"type":"RUN_ERROR","message":"Channel not found"}\n\n'
        return StreamingResponse(missing(), media_type="text/event-stream", status_code=404)
    agent = db.one("SELECT * FROM agents WHERE id=?", (channel["agent_id"],))
    db.execute("INSERT INTO messages(channel_id,role,content,created_at) VALUES(?,?,?,?)", (channel_id, "user", message, db.now()))
    db.execute("UPDATE channels SET updated_at=?,title=CASE WHEN title LIKE 'New channel%' THEN ? ELSE title END WHERE id=?",
               (db.now(), message[:64], channel_id))
    return StreamingResponse(stream_turn(channel_id=channel_id, agent=agent, message=message, thread_id=thread_id, run_id=run_id),
                             media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@rt("/api/chat", methods=["POST"])
async def post(request: Request):
    form = await request.form()
    message = str(form.get("message") or "").strip()
    if not message:
        return JSONResponse({"error": "message is required"}, status_code=400)
    return await _run(int(form.get("channel_id") or 0), message)


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
    return await _run(channel_id, str(content).strip(), body.get("threadId"), body.get("runId"))


@rt("/skills")
def get():
    return ui.skills_page()


@rt("/admin/audit")
def get():
    return ui.audit_page()


@rt("/admin/boundaries")
def get():
    return ui.boundaries_page()


@rt("/admin/computers")
def get():
    agents = db.rows("SELECT * FROM agents ORDER BY id")
    cards = []
    from fasthtml.common import H3, Div, P, Strong
    for agent in agents:
        computer = inspect(agent["slug"])
        cards.append(Div(H3(agent["name"]), P(Strong(computer.backend), " · ", computer.status), P(computer.workspace, cls="muted"), cls="panel"))
    return ui.shell("/admin/computers", ui.topbar("RUNTIME", "Coworker computers", "Each coworker receives an isolated Docker computer and workspace."), Div(*cards, cls="agent-grid"))


def run() -> None:
    cfg = settings()
    uvicorn.run("fastbot.main:app", host=cfg.fastbot_host, port=cfg.fastbot_port, reload=False)


if __name__ == "__main__":
    run()
