from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import settings

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS agents (
 id INTEGER PRIMARY KEY, slug TEXT NOT NULL UNIQUE, name TEXT NOT NULL, title TEXT NOT NULL,
 description TEXT NOT NULL, system_prompt TEXT NOT NULL, icon TEXT NOT NULL DEFAULT '✦',
 visibility TEXT NOT NULL DEFAULT 'private', endpoint TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS channels (
 id INTEGER PRIMARY KEY, agent_id INTEGER NOT NULL REFERENCES agents(id), title TEXT NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
 id INTEGER PRIMARY KEY, channel_id INTEGER NOT NULL REFERENCES channels(id), role TEXT NOT NULL,
 content TEXT NOT NULL DEFAULT '', payload TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS policies (
 id INTEGER PRIMARY KEY, action TEXT NOT NULL, effect TEXT NOT NULL, pattern TEXT NOT NULL,
 note TEXT NOT NULL DEFAULT '', enabled INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_events (
 id INTEGER PRIMARY KEY, channel_id INTEGER, agent_id INTEGER, event_type TEXT NOT NULL,
 action TEXT, decision TEXT, detail TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS skills (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, description TEXT NOT NULL,
 instructions TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    path = settings().fastbot_database
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        yield db
        db.commit()
    finally:
        db.close()


def init_db() -> None:
    with connect() as db:
        db.executescript(SCHEMA)
        if not db.execute("SELECT 1 FROM agents").fetchone():
            created = now()
            agents = [
                ("general", "General Assistant", "Everyday AI coworker", "Research, draft, plan, and get work done.",
                 "You are a capable, concise AI coworker. Explain tool use and respect all policy decisions.", "✦"),
                ("knowledge", "Knowledge", "Company knowledge guide", "Find and synthesize trusted internal knowledge.",
                 "You are a careful knowledge assistant. Separate known facts from inference and cite supplied context.", "◇"),
                ("risk", "Risk Analyst", "Risk and compliance", "Review decisions, controls, and operational risk.",
                 "You are a pragmatic risk analyst. Identify risks, controls, owners, and residual uncertainty.", "△"),
            ]
            db.executemany("INSERT INTO agents(slug,name,title,description,system_prompt,icon,created_at) VALUES(?,?,?,?,?,?,?)", [(*a, created) for a in agents])
            db.executemany("INSERT INTO policies(action,effect,pattern,note,created_at) VALUES(?,?,?,?,?)", [
                ("browser.navigate", "allow", "https://*", "Allow public HTTPS navigation", created),
                ("browser.navigate", "deny", "http://127.0.0.1*", "Protect loopback services", created),
                ("workspace.read", "allow", "*", "Read the coworker's own workspace", created),
                ("workspace.write", "allow", "*", "Write the coworker's own workspace", created),
                ("shell.run", "deny", "*", "Shell disabled until explicitly granted", created),
            ])


def rows(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with connect() as db:
        return [dict(row) for row in db.execute(sql, params).fetchall()]


def one(sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute(sql, params).fetchone()
        return dict(row) if row else None


def execute(sql: str, params: tuple[Any, ...] = ()) -> int:
    with connect() as db:
        cur = db.execute(sql, params)
        return int(cur.lastrowid)


def audit(event_type: str, *, channel_id: int | None = None, agent_id: int | None = None,
          action: str | None = None, decision: str | None = None, detail: Any = None) -> None:
    execute("INSERT INTO audit_events(channel_id,agent_id,event_type,action,decision,detail,created_at) VALUES(?,?,?,?,?,?,?)",
            (channel_id, agent_id, event_type, action, decision, json.dumps(detail or {}, default=str), now()))
