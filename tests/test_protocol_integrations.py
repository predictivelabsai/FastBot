import socket
import threading
import time

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from fastbot import db
from fastbot.main import app


async def agui(request: Request):
    await request.json()
    async def frames():
        yield 'data: {"type":"RUN_STARTED","threadId":"remote","runId":"remote"}\n\n'
        yield 'data: {"type":"TEXT_MESSAGE_CONTENT","messageId":"m","delta":"Remote OK"}\n\n'
        yield 'data: {"type":"RUN_FINISHED","threadId":"remote","runId":"remote"}\n\n'
    return StreamingResponse(frames(), media_type="text/event-stream")


async def mcp(request: Request):
    body = await request.json()
    if body["method"] == "tools/list":
        return JSONResponse({"jsonrpc":"2.0","id":body["id"],"result":{"tools":[{
            "name":"search","description":"Search records","inputSchema":{"type":"object","properties":{"query":{"type":"string"}}}
        }]}})
    return JSONResponse({"jsonrpc":"2.0","id":body["id"],"result":{"content":[{"type":"text","text":"found"}]}})


mock_app = Starlette(routes=[Route("/agui", agui, methods=["POST"]), Route("/mcp", mcp, methods=["POST"])])


def serve_mock():
    sock = socket.socket(); sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]; sock.close()
    server = uvicorn.Server(uvicorn.Config(mock_app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True); thread.start()
    for _ in range(100):
        if server.started: break
        time.sleep(.01)
    return server, thread, port


def test_remote_agui_coworker_is_proxied():
    server, thread, port = serve_mock()
    try:
        agent_id = db.execute("INSERT INTO agents(slug,name,title,description,system_prompt,icon,visibility,endpoint,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                              ("remote","Remote","Remote agent","","Standing role","R","private",f"http://127.0.0.1:{port}/agui",db.now()))
        channel_id = db.execute("INSERT INTO channels(agent_id,title,created_at,updated_at) VALUES(?,?,?,?)",
                                (agent_id,"Remote channel",db.now(),db.now()))
        response = TestClient(app).post("/api/agui", json={"threadId":"t","runId":"r","messages":[{"role":"user","content":"hello"}],"forwardedProps":{"channelId":channel_id}})
        assert response.status_code == 200
        assert "Remote OK" in response.text
        assert '"type":"RUN_FINISHED"' in response.text
    finally:
        server.should_exit = True; thread.join(timeout=3)


def test_mcp_discovery_and_per_agent_grant():
    server, thread, port = serve_mock()
    try:
        plugin_id = db.execute("INSERT INTO plugins(name,transport,endpoint,created_at,updated_at) VALUES(?,?,?,?,?)",
                               ("Records","http",f"http://127.0.0.1:{port}/mcp",db.now(),db.now()))
        client = TestClient(app)
        response = client.post(f"/api/plugins/{plugin_id}/discover")
        assert response.json() == {"ok": True, "tools": 1}
        tool = db.one("SELECT * FROM plugin_tools WHERE plugin_id=?",(plugin_id,))
        agent = db.one("SELECT * FROM agents ORDER BY id LIMIT 1")
        client.post(f"/admin/plugins/tools/{tool['id']}/grant/{agent['id']}")
        assert db.one("SELECT * FROM agent_tool_grants WHERE agent_id=? AND tool_id=?",(agent["id"],tool["id"]))
    finally:
        server.should_exit = True; thread.join(timeout=3)
