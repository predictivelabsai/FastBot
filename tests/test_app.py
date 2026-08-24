from starlette.testclient import TestClient

from fastbot import db
from fastbot.main import app


def test_workspace_and_admin_surfaces_render():
    client = TestClient(app)
    for path, expected in [("/", "Your coworkers"), ("/agents", "Your AI team"),
                           ("/admin/boundaries", "fails closed"), ("/admin/audit", "Audit trail")]:
        response = client.get(path)
        assert response.status_code == 200
        assert expected in response.text


def test_agui_endpoint_streams_lifecycle_without_key(monkeypatch):
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    from fastbot.config import settings
    settings.cache_clear()
    agent = db.one("SELECT * FROM agents ORDER BY id LIMIT 1")
    channel = db.execute("INSERT INTO channels(agent_id,title,created_at,updated_at) VALUES(?,?,?,?)",
                         (agent["id"], "Protocol test", db.now(), db.now()))
    client = TestClient(app)
    response = client.post("/api/agui", json={
        "threadId": "thread-test", "runId": "run-test",
        "messages": [{"id": "m1", "role": "user", "content": "Hello"}],
        "forwardedProps": {"channelId": channel},
    })
    assert response.status_code == 200
    assert '"type":"RUN_STARTED"' in response.text
    assert '"type":"TEXT_MESSAGE_CONTENT"' in response.text
    assert '"type":"RUN_FINISHED"' in response.text
