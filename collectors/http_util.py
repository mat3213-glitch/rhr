"""Shared HTTP client with SSRF protection and retry logic."""
from __future__ import annotations

import ipaddress
import time
from functools import wraps
from typing import Callable, TypeVar

import httpx

_BLOCKED_NETS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]

_RETRY_STATUS = {429, 500, 502, 503, 504}


def _is_blocked_host(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host)
        return any(ip in net for net in _BLOCKED_NETS)
    except ValueError:
        if host in ("localhost", "0.0.0.0", "metadata.google.internal"):
            return True
        return False


class SafeRedirectTransport(httpx.BaseTransport):
    def __init__(self, inner: httpx.BaseTransport):
        self._inner = inner

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host or ""
        if _is_blocked_host(host):
            raise httpx.ConnectError(f"Blocked SSRF: {host}")
        return self._inner.handle_request(request)


def client(
    *,
    timeout: float = 20.0,
    connect_timeout: float = 5.0,
    follow_redirects: bool = True,
    max_redirects: int = 10,
) -> httpx.Client:
    transport = SafeRedirectTransport(httpx.HTTPTransport())
    return httpx.Client(
        transport=transport,
        timeout=httpx.Timeout(timeout, connect=connect_timeout),
        follow_redirects=follow_redirects,
        max_redirects=max_redirects,
    )


T = TypeVar("T")


def retry(
    max_attempts: int = 3,
    initial_wait: float = 1.0,
    max_wait: float = 10.0,
) -> Callable:
    def decorator(fn: Callable[..., T]) -> Callable[..., T]:
        @wraps(fn)
        def wrapper(*args, **kwargs) -> T:
            last_exc = None
            for attempt in range(max_attempts):
                try:
                    return fn(*args, **kwargs)
                except httpx.HTTPStatusError as e:
                    if e.response.status_code not in _RETRY_STATUS:
                        raise
                    last_exc = e
                except (httpx.TimeoutException, httpx.ConnectError) as e:
                    last_exc = e
                if attempt < max_attempts - 1:
                    wait = min(initial_wait * (2 ** attempt), max_wait)
                    time.sleep(wait)
            raise last_exc
        return wrapper
    return decorator
