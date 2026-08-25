from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from .computers import LocalComputerRuntime

runtime = LocalComputerRuntime()
agent = {"id": 1, "slug": "container"}
def authorised(request):
    token=os.environ.get("COMPUTER_TOKEN","")
    return bool(token) and request.headers.get("authorization") == f"Bearer {token}"
async def navigate(request: Request):
    if not authorised(request): return JSONResponse({"error": "unauthorized"}, status_code=401)
    return JSONResponse(await runtime.navigate(agent, (await request.json())["url"]))
async def screenshot(request: Request):
    if not authorised(request): return JSONResponse({"error": "unauthorized"}, status_code=401)
    return Response(await runtime.screenshot(agent), media_type="image/png")
async def snapshot(request: Request):
    if not authorised(request): return JSONResponse({"error": "unauthorized"}, status_code=401)
    return JSONResponse(await runtime.snapshot(agent))
async def action(request: Request):
    if not authorised(request): return JSONResponse({"error":"unauthorized"},status_code=401)
    body=await request.json(); kind=body.pop("action","")
    try: return JSONResponse(await runtime.act(agent,kind,**body))
    except Exception as exc: return JSONResponse({"error":str(exc)},status_code=400)
def safe_path(relative: str) -> Path:
    root=Path("/workspace").resolve(); target=(root/relative.lstrip("/")).resolve()
    if target != root and root not in target.parents: raise ValueError("Path escapes workspace")
    return target
async def file_read(request: Request):
    if not authorised(request): return JSONResponse({"error":"unauthorized"},status_code=401)
    try: return JSONResponse({"content":safe_path((await request.json())["path"]).read_text(encoding="utf-8")})
    except (ValueError,OSError) as exc: return JSONResponse({"error":str(exc)},status_code=400)
async def file_write(request: Request):
    if not authorised(request): return JSONResponse({"error":"unauthorized"},status_code=401)
    body=await request.json()
    try:
        target=safe_path(body["path"]); target.parent.mkdir(parents=True,exist_ok=True); target.write_text(body["content"],encoding="utf-8")
        return JSONResponse({"path":str(target.relative_to("/workspace"))})
    except (ValueError,OSError) as exc: return JSONResponse({"error":str(exc)},status_code=400)
async def shell(request: Request):
    if not authorised(request): return JSONResponse({"error":"unauthorized"},status_code=401)
    try:
        result=subprocess.run(shlex.split((await request.json())["command"]),cwd="/workspace",capture_output=True,text=True,timeout=30,env={"PATH":os.environ.get("PATH","")})
        return JSONResponse({"exit_code":result.returncode,"stdout":result.stdout[-12000:],"stderr":result.stderr[-12000:]})
    except (ValueError,subprocess.TimeoutExpired,OSError) as exc: return JSONResponse({"error":str(exc)},status_code=400)
app = Starlette(routes=[Route("/navigate", navigate, methods=["POST"]), Route("/screenshot", screenshot, methods=["POST"]), Route("/snapshot", snapshot, methods=["POST"]), Route("/action",action,methods=["POST"]), Route("/file/read",file_read,methods=["POST"]), Route("/file/write",file_write,methods=["POST"]), Route("/shell",shell,methods=["POST"])])
