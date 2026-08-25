
import pytest

from fastbot import db
from fastbot.computers import (
    release_control,
    request_help,
    run_shell,
    take_control,
    workspace_path,
    write_file,
)


def agent():
    return db.one("SELECT * FROM agents ORDER BY id LIMIT 1")


def test_workspace_is_confined_and_governed(tmp_path, monkeypatch):
    monkeypatch.setenv("FASTBOT_WORKSPACE_ROOT", str(tmp_path))
    from fastbot.config import settings
    settings.cache_clear()
    item = agent()
    assert write_file(item, "notes/plan.md", "safe") == "notes/plan.md"
    assert (tmp_path / item["slug"] / "notes/plan.md").read_text() == "safe"
    with pytest.raises(ValueError, match="escapes"):
        workspace_path(item, "../outside.txt")


def test_human_takeover_state_and_agent_refusal():
    item = agent()
    request_help(item, "Login required")
    state = db.one("SELECT * FROM computer_states WHERE agent_id=?", (item["id"],))
    assert state["control"] == "waiting"
    take_control(item)
    with pytest.raises(PermissionError, match="Human control"):
        run_shell(item, "pwd")
    release_control(item)
    assert db.one("SELECT control FROM computer_states WHERE agent_id=?", (item["id"],))["control"] == "agent"


def test_shell_fails_closed_by_default():
    with pytest.raises(PermissionError):
        run_shell(agent(), "pwd")


def test_shell_runs_after_explicit_grant():
    db.execute("UPDATE policies SET enabled=0 WHERE action='shell.run' AND effect='deny'")
    db.execute("INSERT INTO policies(action,effect,pattern,note,created_at) VALUES(?,?,?,?,?)",
               ("shell.run","allow","pwd","Test grant",db.now()))
    result = run_shell(agent(), "pwd")
    assert result["exit_code"] == 0
    assert agent()["slug"] in result["stdout"]


@pytest.mark.asyncio
async def test_human_browser_actions_require_takeover(monkeypatch):
    from fastbot.computers import human_action, runtime
    from fastbot.config import settings
    monkeypatch.setenv("FASTBOT_COMPUTER_BACKEND", "local")
    settings.cache_clear()
    item = agent()
    async def fake_act(agent_value, action, **params):
        return {"ok": True, "action": action}
    monkeypatch.setattr(runtime, "act", fake_act)
    with pytest.raises(PermissionError, match="Take control"):
        await human_action(item, "click", x=10, y=10)
    take_control(item)
    assert (await human_action(item, "click", x=10, y=10))["ok"]
