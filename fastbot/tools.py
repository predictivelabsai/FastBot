from __future__ import annotations

from datetime import UTC, datetime

from langchain_core.tools import tool


@tool
def current_time() -> str:
    """Return the current UTC date and time."""
    return datetime.now(UTC).isoformat(timespec="seconds")


@tool
def create_checklist(title: str, items: list[str]) -> dict:
    """Create a structured checklist for the user interface."""
    return {"kind": "checklist", "title": title, "items": items[:12]}


TOOLS = [current_time, create_checklist]
