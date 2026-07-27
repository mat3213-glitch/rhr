"""Shared HTTP client with SSRF protection and retry logic.

SSRF policy
-----------
Before any request (including redirects), the destination host is checked:

1. Literal IPs are validated against blocked ranges.
2. Hostnames are DNS-resolved; **every** address must be public. If any
   resolved address is loopback/private/link-local/unspecified/multicast/
   reserved, the request is blocked.
3. Well-known metadata hostnames are blocked by name.

This closes the gap where ``evil.example`` resolves to ``127.0.0.1`` and would
bypass a hostname-only allow path.
"""
from __future__ import annotations

import ipaddress
import socket
import time
from functools import wraps
from typing import Callable, Sequence, TypeVar

import httpx

# Explicit nets as documentation + belt-and-suspenders alongside ipaddress flags.
_BLOCKED_NETS = [
    # IPv4
    ipaddress.ip_network("0.0.0.0/8"),          # unspecified / "this" network
    ipaddress.ip_network("127.0.0.0/8"),        # loopback
    ipaddress.ip_network("10.0.0.0/8"),         # private
    ipaddress.ip_network("172.16.0.0/12"),      # private
    ipaddress.ip_network("192.168.0.0/16"),     # private
    ipaddress.ip_network("169.254.0.0/16"),     # link-local (incl. cloud metadata)
    ipaddress.ip_network("100.64.0.0/10"),      # shared/CGNAT (RFC 6598)
    ipaddress.ip_network("192.0.0.0/24"),       # IETF protocol assignments
    ipaddress.ip_network("192.0.2.0/24"),       # TEST-NET-1
    ipaddress.ip_network("198.51.100.0/24"),    # TEST-NET-2
    ipaddress.ip_network("203.0.113.0/24"),     # TEST-NET-3
    ipaddress.ip_network("224.0.0.0/4"),        # multicast
    ipaddress.ip_network("240.0.0.0/4"),        # reserved
    # IPv6
    ipaddress.ip_network("::/128"),             # unspecified
    ipaddress.ip_network("::1/128"),            # loopback
    ipaddress.ip_network("fc00::/7"),           # unique local
    ipaddress.ip_network("fe80::/10"),          # link-local
    ipaddress.ip_network("ff00::/8"),           # multicast
    ipaddress.ip_network("2001:db8::/32"),      # documentation
]

_BLOCKED_HOSTNAMES = frozenset({
    "localhost",
    "metadata.google.internal",
    "metadata.goog",
    "metadata",
    "kubernetes.default",
    "kubernetes.default.svc",
})

_RETRY_STATUS = {429, 500, 502, 503, 504}

# Overridable in tests — signature compatible with a thin wrapper around getaddrinfo.
ResolveFn = Callable[[str], Sequence[str]]


def _default_resolve(host: str) -> list[str]:
    """Resolve hostname to a list of literal IP strings (A + AAAA)."""
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return []
    addrs: list[str] = []
    seen: set[str] = set()
    for info in infos:
        addr = info[4][0]
        if addr not in seen:
            seen.add(addr)
            addrs.append(addr)
    return addrs


# Module-level hook so tests can monkeypatch without touching socket globally.
_resolve_ips: ResolveFn = _default_resolve


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True if IP must not be contacted (SSRF)."""
    # Mapped IPv4-in-IPv6 → check the embedded v4 address too.
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        if _is_blocked_ip(ip.ipv4_mapped):
            return True

    if (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_unspecified
        or ip.is_reserved
    ):
        return True

    for net in _BLOCKED_NETS:
        try:
            if ip in net:
                return True
        except TypeError:
            # v4 vs v6 mismatch
            continue
    return False


def _normalize_host(host: str) -> str:
    h = (host or "").strip().lower()
    # httpx may give bracketed IPv6: [::1]
    if h.startswith("[") and h.endswith("]"):
        h = h[1:-1]
    # strip zone id if present (fe80::1%eth0)
    if "%" in h:
        h = h.split("%", 1)[0]
    return h


def _is_blocked_host(host: str, *, resolver: ResolveFn | None = None) -> bool:
    """DNS-aware host block check.

    - Literal IP → range check.
    - Hostname → resolve all addresses; block if **any** is non-public, or if
      the bare hostname is on the deny list.
    - Resolution failure → not blocked here (connection will fail naturally);
      we only actively refuse destinations we can prove are unsafe.
    """
    host = _normalize_host(host)
    if not host:
        return True
    if host in _BLOCKED_HOSTNAMES:
        return True

    try:
        ip = ipaddress.ip_address(host)
        return _is_blocked_ip(ip)
    except ValueError:
        pass

    resolve = resolver or _resolve_ips
    addrs = list(resolve(host))
    if not addrs:
        return False
    for addr in addrs:
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if _is_blocked_ip(ip):
            return True
    return False


class SafeRedirectTransport(httpx.BaseTransport):
    """Wrap an inner transport; re-check host (DNS-aware) on every hop."""

    def __init__(self, inner: httpx.BaseTransport, *, resolver: ResolveFn | None = None):
        self._inner = inner
        self._resolver = resolver

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host or ""
        if _is_blocked_host(host, resolver=self._resolver):
            raise httpx.ConnectError(f"Blocked SSRF: {host}")
        return self._inner.handle_request(request)


def client(
    *,
    timeout: float = 20.0,
    connect_timeout: float = 5.0,
    follow_redirects: bool = True,
    max_redirects: int = 10,
    resolver: ResolveFn | None = None,
) -> httpx.Client:
    transport = SafeRedirectTransport(httpx.HTTPTransport(), resolver=resolver)
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
