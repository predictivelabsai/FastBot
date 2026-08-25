from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

BLOCKED_HOSTS = {"metadata.google.internal", "169.254.169.254", "169.254.170.2", "100.100.100.200"}


def validate_remote_url(value: str, *, allow_private: bool = False) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Endpoint must be an HTTP(S) URL")
    host = parsed.hostname.lower()
    if host in BLOCKED_HOSTS:
        raise ValueError("Cloud metadata endpoints are always refused")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, parsed.port or 443)}
    except socket.gaierror as exc:
        raise ValueError("Endpoint hostname cannot be resolved") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if ip.is_link_local or ip.is_unspecified or ip.is_multicast:
            raise ValueError("Cloud metadata and non-routable endpoints are always refused")
        if not ip.is_global and not allow_private:
            raise ValueError("Private agent endpoints are not allowed")
    return value
