from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import settings


@dataclass(frozen=True)
class Computer:
    agent_slug: str
    backend: str
    status: str
    workspace: str
    container: str | None = None


def inspect(agent_slug: str) -> Computer:
    cfg = settings()
    workspace = cfg.fastbot_workspace_root / agent_slug
    Path(workspace).mkdir(parents=True, exist_ok=True)
    container = f"fastbot-computer-{agent_slug}"
    status = "not started"
    if cfg.fastbot_computer_backend == "docker":
        try:
            result = subprocess.run(["docker", "inspect", "-f", "{{.State.Status}}", container],
                                    capture_output=True, text=True, timeout=3, check=False)
            if result.returncode == 0:
                status = result.stdout.strip()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            status = "docker unavailable"
    return Computer(agent_slug, cfg.fastbot_computer_backend, status, str(workspace), container)
