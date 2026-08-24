from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch

from . import db


@dataclass(frozen=True)
class Decision:
    allowed: bool
    rule_id: int | None
    reason: str


def decide(action: str, target: str) -> Decision:
    rules = db.rows("SELECT * FROM policies WHERE enabled=1 AND action=? ORDER BY CASE effect WHEN 'deny' THEN 0 ELSE 1 END, id", (action,))
    for rule in rules:
        if fnmatch(target, rule["pattern"]):
            allowed = rule["effect"] == "allow"
            return Decision(allowed, rule["id"], rule["note"] or f"Rule {rule['id']} {rule['effect']}ed the action")
    return Decision(False, None, "No policy explicitly allows this action")


def authorize(action: str, target: str, *, channel_id: int | None = None, agent_id: int | None = None) -> Decision:
    decision = decide(action, target)
    db.audit("policy.decision", channel_id=channel_id, agent_id=agent_id, action=action,
             decision="allowed" if decision.allowed else "refused",
             detail={"target": target, "rule_id": decision.rule_id, "reason": decision.reason})
    return decision
