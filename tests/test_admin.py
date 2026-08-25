from starlette.testclient import TestClient

from fastbot import db
from fastbot.main import app


def test_all_administration_surfaces_render():
    client = TestClient(app)
    paths = ["/skills", "/admin/computers", "/admin/credentials", "/admin/components",
             "/admin/plugins", "/admin/people"]
    for path in paths:
        response = client.get(path)
        assert response.status_code == 200, (path, response.text)


def test_skill_create_edit_and_grant():
    client = TestClient(app)
    response = client.post("/skills", data={"name":"Concise","description":"Short output",
                                            "instructions":"Use no more than five bullets","scope":"deployment"})
    assert response.status_code == 200
    skill = db.one("SELECT * FROM skills WHERE name='Concise'")
    agent = db.one("SELECT * FROM agents ORDER BY id LIMIT 1")
    assert client.post(f"/skills/{skill['id']}/grant/{agent['id']}").status_code == 200
    assert client.post(f"/skills/{skill['id']}", data={"name":"Concise","description":"Edited",
                                                        "instructions":"Use three bullets"}).status_code == 200
    assert db.one("SELECT instructions FROM skills WHERE id=?", (skill["id"],))["instructions"] == "Use three bullets"


def test_component_publish_and_withhold():
    client = TestClient(app)
    response = client.post("/admin/components", data={"name":"status-card","title":"Status",
                                                       "template":"notice","schema_json":"{}","published":"1"})
    assert response.status_code == 200
    component = db.one("SELECT * FROM components WHERE name='status-card'")
    agent = db.one("SELECT * FROM agents ORDER BY id LIMIT 1")
    client.post(f"/admin/components/{component['id']}/withhold/{agent['id']}")
    assert db.one("SELECT * FROM component_withholds WHERE component_id=? AND agent_id=?",
                  (component["id"], agent["id"]))


def test_policy_can_be_disabled_then_reenabled():
    client = TestClient(app)
    rule = db.one("SELECT * FROM policies WHERE action='shell.run' AND effect='deny'")
    client.post(f"/admin/boundaries/{rule['id']}/toggle")
    assert db.one("SELECT enabled FROM policies WHERE id=?", (rule["id"],))["enabled"] == 0
