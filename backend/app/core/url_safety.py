"""Outbound URL validation (SSRF protection) for workflow HTTP and KYC requests."""
import asyncio
import ipaddress
import socket
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

import httpx

from app.core.config import settings

MAX_REDIRECTS = 3
ALLOWED_SCHEMES = {"http", "https"}


class UnsafeURLError(ValueError):
    pass


def _is_blocked_ip(ip: ipaddress._BaseAddress) -> bool:
    # Unwrap IPv4-mapped IPv6 (::ffff:127.0.0.1) so it can't bypass the v4 checks
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    return (
        ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
        or ip.is_reserved or ip.is_unspecified
        or (ip.version == 4 and ip in ipaddress.ip_network("100.64.0.0/10"))  # CGNAT
    )


async def validate_outbound_url(url: str) -> None:
    """Raise UnsafeURLError unless the URL is http(s) and every resolved address is public."""
    parsed = urlparse(url or "")
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise UnsafeURLError(f"URL scheme '{parsed.scheme or ''}' is not allowed (http/https only)")
    host = parsed.hostname
    if not host:
        raise UnsafeURLError("URL has no host")
    if settings.ALLOW_PRIVATE_URLS:
        return

    try:
        literal: Optional[ipaddress._BaseAddress] = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if _is_blocked_ip(literal):
            raise UnsafeURLError("URL points to a private or reserved address")
        return

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        infos = await asyncio.to_thread(socket.getaddrinfo, host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise UnsafeURLError(f"Could not resolve host '{host}'")
    for info in infos:
        if _is_blocked_ip(ipaddress.ip_address(info[4][0])):
            raise UnsafeURLError("URL resolves to a private or reserved address")


async def safe_request(method: str, url: str, *, timeout: float = 30, **kwargs: Any) -> httpx.Response:
    """httpx request that validates the URL and every redirect hop before connecting."""
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        for _ in range(MAX_REDIRECTS + 1):
            await validate_outbound_url(url)
            response = await client.request(method, url, **kwargs)
            if response.is_redirect and response.headers.get("location"):
                url = urljoin(url, response.headers["location"])
                if response.status_code in (301, 302, 303):
                    method, kwargs = "GET", {k: v for k, v in kwargs.items() if k in ("headers",)}
                continue
            return response
        raise UnsafeURLError("Too many redirects")
