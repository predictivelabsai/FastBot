
import pytest

from fastbot import auth, credentials, db
from fastbot.endpoints import validate_remote_url


def test_credentials_are_encrypted_and_write_only():
    credential_id = credentials.store("test-token", "bearer", "super-secret-value", 1)
    with db.connect() as connection:
        row = connection.execute("SELECT ciphertext FROM credentials WHERE id=?", (credential_id,)).fetchone()
    assert b"super-secret-value" not in row[0]
    assert credentials.reveal(credential_id) == "super-secret-value"
    assert "ciphertext" not in credentials.metadata()[0]


def test_password_hash_round_trip_and_wrong_password():
    encoded = auth.hash_password("correct horse")
    assert "correct horse" not in encoded
    assert auth.verify_password("correct horse", encoded)
    assert not auth.verify_password("wrong", encoded)


def test_remote_endpoint_blocks_private_and_metadata(monkeypatch):
    monkeypatch.setattr("socket.getaddrinfo", lambda *args: [(None, None, None, None, ("127.0.0.1", 80))])
    with pytest.raises(ValueError, match="Private"):
        validate_remote_url("http://internal.example/ag-ui")
    with pytest.raises(ValueError, match="metadata"):
        validate_remote_url("http://169.254.169.254/latest")


def test_database_migrations_create_all_governance_tables():
    expected = {"credentials", "users", "components", "plugins", "plugin_tools",
                "agent_tool_grants", "computer_states", "component_withholds"}
    with db.connect() as connection:
        actual = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert expected <= actual


def test_authentication_gate_when_single_user_is_disabled(monkeypatch):
    from starlette.testclient import TestClient

    from fastbot.config import settings
    from fastbot.main import app
    encoded = auth.hash_password("password123")
    db.execute("INSERT INTO users(email,name,role,password_hash,created_at) VALUES(?,?,?,?,?)",
               ("member@example.com","Member","member",encoded,db.now()))
    monkeypatch.setenv("FASTBOT_SINGLE_USER","false"); settings.cache_clear()
    client = TestClient(app)
    assert client.get("/",follow_redirects=False).headers["location"] == "/login"
    response = client.post("/login",data={"email":"member@example.com","password":"password123"},follow_redirects=False)
    assert response.status_code == 303
    assert client.get("/").status_code == 200
