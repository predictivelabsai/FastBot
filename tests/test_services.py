from starlette.testclient import TestClient

from fastbot.computer_service import app as computer_app
from fastbot.supervisor_service import app as supervisor_app


def test_computer_service_fails_closed_without_token(monkeypatch):
    monkeypatch.delenv("COMPUTER_TOKEN", raising=False)
    response = TestClient(computer_app).post("/snapshot")
    assert response.status_code == 401


def test_supervisor_requires_token_and_validates_slug(monkeypatch):
    monkeypatch.setenv("SUPERVISOR_TOKEN", "supervisor-secret")
    client = TestClient(supervisor_app)
    assert client.post("/start", json={"slug":"valid"}).status_code == 401
    response = client.post("/start", json={"slug":"../../host"},
                           headers={"Authorization":"Bearer supervisor-secret"})
    assert response.status_code == 400
