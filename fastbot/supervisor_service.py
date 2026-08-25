from __future__ import annotations

import os
import re
import subprocess

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route


def authorized(request):
    token=os.environ.get("SUPERVISOR_TOKEN","")
    return bool(token) and request.headers.get("authorization")==f"Bearer {token}"
async def payload(request):
    if not authorized(request): raise PermissionError
    slug=str((await request.json()).get("slug", ""))
    if not re.fullmatch(r"[a-z0-9-]{1,64}",slug): raise ValueError("Invalid coworker slug")
    return slug
def address(name):
    return subprocess.run(["docker","inspect","-f",'{{(index .NetworkSettings.Networks "fastbot-computers").IPAddress}}',name],capture_output=True,text=True,check=True).stdout.strip()
async def start(request: Request):
    try: slug=await payload(request)
    except PermissionError: return JSONResponse({"error":"unauthorized"},status_code=401)
    except ValueError as exc: return JSONResponse({"error":str(exc)},status_code=400)
    name=f"fastbot-computer-{slug}"; volume=f"fastbot-workspace-{slug}"
    if subprocess.run(["docker","inspect",name],capture_output=True).returncode != 0:
        subprocess.run(["docker","volume","create",volume],capture_output=True,check=True)
        subprocess.run(["docker","run","-d","--name",name,"--network","fastbot-computers","--security-opt","no-new-privileges","--cap-drop","ALL","--memory","1g","--cpus","1.0","-e",f"COMPUTER_TOKEN={os.environ.get('COMPUTER_TOKEN','')}","-v",f"{volume}:/workspace","fastbot-computer:local"],check=True)
        subprocess.run(["docker","network","connect","bridge",name],check=True)
    return JSONResponse({"status":"running","address":address(name)})
async def stop(request: Request):
    try: slug=await payload(request)
    except PermissionError: return JSONResponse({"error":"unauthorized"},status_code=401)
    subprocess.run(["docker","rm","-f",f"fastbot-computer-{slug}"],capture_output=True,check=False)
    return JSONResponse({"status":"stopped"})
async def inspect(request: Request):
    try: slug=await payload(request)
    except PermissionError: return JSONResponse({"error":"unauthorized"},status_code=401)
    name=f"fastbot-computer-{slug}"
    try: return JSONResponse({"status":"running","address":address(name)})
    except subprocess.CalledProcessError: return JSONResponse({"status":"stopped","address":""},status_code=404)
app=Starlette(routes=[Route("/start",start,methods=["POST"]),Route("/stop",stop,methods=["POST"]),Route("/inspect",inspect,methods=["POST"])])
