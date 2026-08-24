from fastbot import db
from fastbot.policy import authorize, decide


def test_deny_wins_over_allow():
    decision = decide("browser.navigate", "http://127.0.0.1/private")
    assert decision.allowed is False
    assert "loopback" in decision.reason.lower()


def test_unknown_action_fails_closed_and_is_audited():
    decision = authorize("shell.run", "ls", agent_id=1)
    assert decision.allowed is False
    audit = db.one("SELECT * FROM audit_events ORDER BY id DESC LIMIT 1")
    assert audit["decision"] == "refused"
