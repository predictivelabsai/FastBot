from __future__ import annotations

import asyncio
import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx
from playwright.async_api import BrowserContext, Playwright, async_playwright

from . import db
from .config import settings
from .endpoints import validate_remote_url
from .policy import authorize


@dataclass(frozen=True)
class Computer:
    agent_id: int
    agent_slug: str
    backend: str
    status: str
    control: str
    workspace: str
    current_url: str = ""
    help_reason: str = ""


class LocalComputerRuntime:
    def __init__(self):
        self.playwright: Playwright | None = None
        self.contexts: dict[int, BrowserContext] = {}

    async def start(self, agent: dict) -> None:
        if agent["id"] in self.contexts:
            return
        if self.playwright is None:
            self.playwright = await async_playwright().start()
        profile = settings().fastbot_workspace_root / agent["slug"] / ".browser"
        profile.mkdir(parents=True, exist_ok=True)
        context = await self.playwright.chromium.launch_persistent_context(
            str(profile), headless=True, viewport={"width": 1280, "height": 800},
            args=["--disable-dev-shm-usage"],
        )
        async def guard(route):
            target=route.request.url
            if urlparse(target).scheme in {"data","blob","about"}: return await route.continue_()
            try: validate_remote_url(target,allow_private=False)
            except ValueError: return await route.abort("blockedbyclient")
            return await route.continue_()
        await context.route("**/*",guard)
        self.contexts[agent["id"]] = context
        _state(agent["id"], status="running")

    async def stop(self, agent: dict) -> None:
        context = self.contexts.pop(agent["id"], None)
        if context:
            await context.close()
        if not self.contexts and self.playwright:
            await self.playwright.stop()
            self.playwright = None
        _state(agent["id"], status="stopped", current_url="")

    async def navigate(self, agent: dict, url: str) -> dict:
        await self.start(agent)
        context = self.contexts[agent["id"]]
        page = context.pages[0] if context.pages else await context.new_page()
        response = await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        _state(agent["id"], status="running", current_url=page.url)
        return {"url": page.url, "title": await page.title(),
                "status": response.status if response else None}

    async def screenshot(self, agent: dict) -> bytes:
        await self.start(agent)
        context = self.contexts[agent["id"]]
        page = context.pages[0] if context.pages else await context.new_page()
        return await page.screenshot(type="png")

    async def snapshot(self, agent: dict) -> dict:
        await self.start(agent)
        context = self.contexts[agent["id"]]
        page = context.pages[0] if context.pages else await context.new_page()
        return {"url": page.url, "title": await page.title(),
                "text": (await page.locator("body").inner_text())[:12_000]}

    async def act(self, agent: dict, action: str, **params) -> dict:
        await self.start(agent)
        context=self.contexts[agent["id"]]
        page=context.pages[0] if context.pages else await context.new_page()
        if action == "click":
            if params.get("selector"): await page.locator(params["selector"]).first.click(timeout=10_000)
            else: await page.mouse.click(float(params["x"]),float(params["y"]))
        elif action == "type":
            if params.get("selector"): await page.locator(params["selector"]).first.fill(str(params.get("text","")),timeout=10_000)
            else: await page.keyboard.type(str(params.get("text","")))
        elif action == "key": await page.keyboard.press(str(params["key"]))
        else: raise ValueError("Unknown browser action")
        return {"ok":True,"url":page.url,"title":await page.title()}


runtime = LocalComputerRuntime()


def _state(agent_id: int, **values) -> None:
    current = db.one("SELECT * FROM computer_states WHERE agent_id=?", (agent_id,)) or {}
    merged = {"status": "stopped", "control": "agent", "help_reason": None,
              "current_url": None, "screenshot_path": None, **current, **values}
    db.execute(
        "INSERT INTO computer_states(agent_id,status,control,help_reason,current_url,screenshot_path,updated_at) "
        "VALUES(?,?,?,?,?,?,?) ON CONFLICT(agent_id) DO UPDATE SET status=excluded.status,"
        "control=excluded.control,help_reason=excluded.help_reason,current_url=excluded.current_url,"
        "screenshot_path=excluded.screenshot_path,updated_at=excluded.updated_at",
        (agent_id, merged["status"], merged["control"], merged["help_reason"],
         merged["current_url"], merged["screenshot_path"], db.now()),
    )


def inspect(agent_slug: str) -> Computer:
    agent = db.one("SELECT * FROM agents WHERE slug=?", (agent_slug,))
    if not agent:
        raise KeyError("Coworker not found")
    workspace = settings().fastbot_workspace_root / agent_slug
    workspace.mkdir(parents=True, exist_ok=True)
    state = db.one("SELECT * FROM computer_states WHERE agent_id=?", (agent["id"],)) or {}
    return Computer(agent["id"], agent_slug, settings().fastbot_computer_backend,
                    state.get("status", "stopped"), state.get("control", "agent"), str(workspace),
                    state.get("current_url") or "", state.get("help_reason") or "")


def _agent_controlled(agent_id: int) -> bool:
    state = db.one("SELECT control FROM computer_states WHERE agent_id=?", (agent_id,))
    return not state or state["control"] == "agent"


def workspace_path(agent: dict, relative: str) -> Path:
    root = (settings().fastbot_workspace_root / agent["slug"]).resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = (root / relative.lstrip("/")).resolve()
    if target != root and root not in target.parents:
        raise ValueError("Path escapes the coworker workspace")
    return target


def read_file(agent: dict, relative: str, channel_id: int | None = None) -> str:
    decision = authorize("workspace.read", relative, channel_id=channel_id, agent_id=agent["id"])
    if not decision.allowed: raise PermissionError(decision.reason)
    return workspace_path(agent, relative).read_text(encoding="utf-8")


def write_file(agent: dict, relative: str, content: str, channel_id: int | None = None) -> str:
    decision = authorize("workspace.write", relative, channel_id=channel_id, agent_id=agent["id"])
    if not decision.allowed: raise PermissionError(decision.reason)
    target = workspace_path(agent, relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return str(target.relative_to((settings().fastbot_workspace_root / agent["slug"]).resolve()))


def run_shell(agent: dict, command: str, channel_id: int | None = None) -> dict:
    if not _agent_controlled(agent["id"]): raise PermissionError("Human control is active")
    decision = authorize("shell.run", command, channel_id=channel_id, agent_id=agent["id"])
    if not decision.allowed: raise PermissionError(decision.reason)
    result = subprocess.run(shlex.split(command), cwd=workspace_path(agent, "."),
                            capture_output=True, text=True, timeout=30,
                            env={"PATH": os.environ.get("PATH", ""), "LANG": "C.UTF-8"})
    return {"exit_code": result.returncode, "stdout": result.stdout[-12_000:],
            "stderr": result.stderr[-12_000:]}


async def aread_file(agent: dict, relative: str, channel_id: int | None = None) -> str:
    decision = authorize("workspace.read", relative, channel_id=channel_id, agent_id=agent["id"])
    if not decision.allowed: raise PermissionError(decision.reason)
    if settings().fastbot_computer_backend == "docker":
        result = await _docker_request(agent, "file/read", {"path": relative})
        return result["content"]
    return read_file(agent, relative, channel_id)


async def awrite_file(agent: dict, relative: str, content: str, channel_id: int | None = None) -> str:
    decision = authorize("workspace.write", relative, channel_id=channel_id, agent_id=agent["id"])
    if not decision.allowed: raise PermissionError(decision.reason)
    if settings().fastbot_computer_backend == "docker":
        result = await _docker_request(agent, "file/write", {"path": relative, "content": content})
        return result["path"]
    return write_file(agent, relative, content, channel_id)


async def arun_shell(agent: dict, command: str, channel_id: int | None = None) -> dict:
    if not _agent_controlled(agent["id"]): raise PermissionError("Human control is active")
    decision = authorize("shell.run", command, channel_id=channel_id, agent_id=agent["id"])
    if not decision.allowed: raise PermissionError(decision.reason)
    if settings().fastbot_computer_backend == "docker":
        return await _docker_request(agent, "shell", {"command": command})
    return run_shell(agent, command, channel_id)


async def navigate(agent: dict, url: str, channel_id: int | None = None) -> dict:
    if not _agent_controlled(agent["id"]): raise PermissionError("Human control is active")
    if urlparse(url).scheme not in {"http", "https"}: raise ValueError("Only HTTP(S) navigation is supported")
    validate_remote_url(url, allow_private=False)
    decision = authorize("browser.navigate", url, channel_id=channel_id, agent_id=agent["id"])
    if not decision.allowed: raise PermissionError(decision.reason)
    if settings().fastbot_computer_backend == "docker":
        return await _docker_request(agent, "navigate", {"url": url})
    return await runtime.navigate(agent, url)


async def screenshot(agent: dict) -> bytes:
    if settings().fastbot_computer_backend == "docker": return await _docker_request(agent, "screenshot", raw=True)
    return await runtime.screenshot(agent)


async def snapshot(agent: dict) -> dict:
    if settings().fastbot_computer_backend == "docker": return await _docker_request(agent, "snapshot")
    return await runtime.snapshot(agent)


async def agent_action(agent: dict, action: str, channel_id: int | None = None, **params) -> dict:
    if not _agent_controlled(agent["id"]): raise PermissionError("Human control is active")
    target=str(params.get("selector") or params.get("key") or "page")
    policy_action="browser.type" if action in {"type","key"} else "browser.click"
    decision=authorize(policy_action,target,channel_id=channel_id,agent_id=agent["id"])
    if not decision.allowed: raise PermissionError(decision.reason)
    return await _browser_action(agent,action,params)


async def human_action(agent: dict, action: str, **params) -> dict:
    state=db.one("SELECT control FROM computer_states WHERE agent_id=?",(agent["id"],))
    if not state or state["control"] != "human": raise PermissionError("Take control before interacting")
    result=await _browser_action(agent,action,params)
    db.audit("computer.human_action",agent_id=agent["id"],action=action,
             detail={key:value for key,value in params.items() if key != "text"})
    return result


async def _browser_action(agent: dict, action: str, params: dict) -> dict:
    if settings().fastbot_computer_backend == "docker":
        return await _docker_request(agent,"action",{"action":action,**params})
    return await runtime.act(agent,action,**params)


async def start(agent: dict) -> None:
    if settings().fastbot_computer_backend == "docker":
        if settings().fastbot_supervisor_url: await _supervisor_request("start", agent)
        else: await asyncio.to_thread(_start_container, agent)
    else: await runtime.start(agent)


async def stop(agent: dict) -> None:
    if settings().fastbot_computer_backend == "docker":
        if settings().fastbot_supervisor_url: await _supervisor_request("stop", agent)
        else: subprocess.run(["docker", "rm", "-f", f"fastbot-computer-{agent['slug']}"], capture_output=True, check=False)
        _state(agent["id"], status="stopped")
    else: await runtime.stop(agent)


def request_help(agent: dict, reason: str) -> None:
    _state(agent["id"], control="waiting", help_reason=reason)
    db.audit("computer.help_requested", agent_id=agent["id"], detail={"reason": reason})


def take_control(agent: dict) -> None:
    _state(agent["id"], control="human")
    db.audit("computer.control_taken", agent_id=agent["id"])


def release_control(agent: dict) -> None:
    _state(agent["id"], control="agent", help_reason=None)
    db.audit("computer.control_released", agent_id=agent["id"])


def _start_container(agent: dict) -> None:
    name = f"fastbot-computer-{agent['slug']}"
    if subprocess.run(["docker", "inspect", name], capture_output=True).returncode != 0:
        volume = f"fastbot-workspace-{agent['slug']}"
        subprocess.run(["docker", "volume", "create", volume], capture_output=True, check=True)
        subprocess.run(["docker", "run", "-d", "--name", name, "--network", "bridge",
                        "-e", f"COMPUTER_TOKEN={settings().fastbot_session_secret}",
                        "-v", f"{volume}:/workspace", "fastbot-computer:local"], check=True)
    _state(agent["id"], status="running")


async def _docker_request(agent: dict, action: str, payload: dict | None = None, raw: bool = False):
    await start(agent)
    name = f"fastbot-computer-{agent['slug']}"
    if settings().fastbot_supervisor_url:
        info = await _supervisor_request("inspect", agent); address = info["address"]
    else:
        address = subprocess.run(["docker", "inspect", "-f", "{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}", name],
                                 capture_output=True, text=True, check=True).stdout.strip()
    async with httpx.AsyncClient(timeout=35) as client:
        response = await client.post(f"http://{address}:4100/{action}", json=payload or {},
                                     headers={"Authorization": f"Bearer {settings().fastbot_session_secret}"})
        response.raise_for_status()
        return response.content if raw else response.json()


async def _supervisor_request(action: str, agent: dict) -> dict:
    cfg=settings(); token=cfg.fastbot_supervisor_token or cfg.fastbot_session_secret
    async with httpx.AsyncClient(timeout=30) as client:
        response=await client.post(f"{cfg.fastbot_supervisor_url.rstrip('/')}/{action}",json={"slug":agent["slug"]},headers={"Authorization":f"Bearer {token}"})
        response.raise_for_status(); return response.json()
