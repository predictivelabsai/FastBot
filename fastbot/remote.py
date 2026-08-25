from __future__ import annotations

from collections.abc import AsyncIterator

import httpx

from .credentials import reveal


async def proxy(agent: dict, body: dict) -> AsyncIterator[bytes]:
    headers = {"Accept": "text/event-stream", "Content-Type": "application/json"}
    if agent.get("auth_credential_id"):
        headers["Authorization"] = reveal(agent["auth_credential_id"])
    timeout = httpx.Timeout(90, connect=10)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        async with client.stream("POST", agent["endpoint"], json=body, headers=headers) as response:
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if "text/event-stream" not in content_type:
                raise RuntimeError("Remote coworker did not return an AG-UI event stream")
            async for chunk in response.aiter_bytes():
                yield chunk
