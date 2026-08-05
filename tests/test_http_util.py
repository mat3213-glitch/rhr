"""Tests for collectors/http_util.py — SSRF protection, retry, safe client."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from collectors.http_util import (
    _is_blocked_host,
    _is_blocked_ip,
    client,
    PinnedNetworkBackend,
    retry,
    SafeRedirectTransport,
)
import ipaddress


class TestIsBlockedHost:
    def test_localhost(self):
        assert _is_blocked_host("localhost") is True

    def test_loopback_127(self):
        assert _is_blocked_host("127.0.0.1") is True
        assert _is_blocked_host("127.0.0.255") is True

    def test_private_10(self):
        assert _is_blocked_host("10.0.0.1") is True
        assert _is_blocked_host("10.255.255.255") is True

    def test_private_172(self):
        assert _is_blocked_host("172.16.0.1") is True
        assert _is_blocked_host("172.31.255.255") is True

    def test_private_192(self):
        assert _is_blocked_host("192.168.1.1") is True

    def test_link_local(self):
        assert _is_blocked_host("169.254.169.254") is True

    def test_ipv6_loopback(self):
        assert _is_blocked_host("::1") is True

    def test_ipv6_ula(self):
        assert _is_blocked_host("fd12:3456:789a::1") is True

    def test_unspecified(self):
        assert _is_blocked_host("0.0.0.0") is True
        assert _is_blocked_host("::") is True

    def test_multicast(self):
        assert _is_blocked_host("224.0.0.1") is True

    def test_metadata_google(self):
        assert _is_blocked_host("metadata.google.internal") is True

    def test_public_literal_ip(self):
        assert _is_blocked_host("1.1.1.1") is False
        assert _is_blocked_host("8.8.8.8") is False

    def test_public_host_with_public_dns(self):
        # Mock resolver so we don't depend on live DNS in CI.
        assert _is_blocked_host(
            "api.github.com",
            resolver=lambda h: ["140.82.112.3"],
        ) is False
        assert _is_blocked_host(
            "example.com",
            resolver=lambda h: ["93.184.216.34"],
        ) is False

    def test_private_out_of_range(self):
        assert _is_blocked_host("11.0.0.1") is False
        assert _is_blocked_host("172.32.0.1") is False

    def test_hostname_resolves_to_private_ip(self):
        """SSRF via DNS: public-looking name → private address must be blocked."""
        assert _is_blocked_host(
            "evil.internal",
            resolver=lambda h: ["127.0.0.1"],
        ) is True
        assert _is_blocked_host(
            "corp.local",
            resolver=lambda h: ["10.0.0.5"],
        ) is True
        assert _is_blocked_host(
            "meta.example",
            resolver=lambda h: ["169.254.169.254"],
        ) is True

    def test_hostname_resolves_to_mixed_ips_blocks_if_any_private(self):
        assert _is_blocked_host(
            "dual.example",
            resolver=lambda h: ["1.1.1.1", "192.168.0.1"],
        ) is True

    def test_hostname_unresolvable_not_preemptively_blocked(self):
        # Let the connection fail naturally; we only refuse proven-unsafe targets.
        assert _is_blocked_host("no-such-host.invalid", resolver=lambda h: []) is False

    def test_bracketed_ipv6_loopback(self):
        assert _is_blocked_host("[::1]") is True


class TestIsBlockedIp:
    def test_flags_cover_cgnat(self):
        assert _is_blocked_ip(ipaddress.ip_address("100.64.0.1")) is True

    def test_ipv4_mapped_loopback(self):
        assert _is_blocked_ip(ipaddress.ip_address("::ffff:127.0.0.1")) is True


class TestSafeRedirectTransport:
    def test_blocks_private_ip(self):
        inner = MagicMock()
        transport = SafeRedirectTransport(inner)
        req = httpx.Request("GET", "http://127.0.0.1/secret")
        with pytest.raises(httpx.ConnectError, match="Blocked SSRF"):
            transport.handle_request(req)
        inner.handle_request.assert_not_called()

    def test_blocks_hostname_resolving_private(self):
        inner = MagicMock()
        transport = SafeRedirectTransport(
            inner, resolver=lambda h: ["10.1.2.3"]
        )
        req = httpx.Request("GET", "https://looks-public.example/x")
        with pytest.raises(httpx.ConnectError, match="Blocked SSRF"):
            transport.handle_request(req)
        inner.handle_request.assert_not_called()

    def test_allows_public_host(self):
        inner = MagicMock()
        inner.handle_response.return_value = httpx.Response(200)
        transport = SafeRedirectTransport(
            inner, resolver=lambda h: ["140.82.112.3"]
        )
        req = httpx.Request("GET", "https://api.github.com/data")
        transport.handle_request(req)
        inner.handle_request.assert_called_once()

    def test_redirect_hop_rechecked(self):
        """Each hop goes through handle_request — private redirect target blocked."""
        inner = MagicMock()
        transport = SafeRedirectTransport(
            inner,
            resolver=lambda h: (
                ["1.1.1.1"] if h == "public.example" else ["127.0.0.1"]
            ),
        )
        # First hop OK
        transport.handle_request(httpx.Request("GET", "https://public.example/a"))
        # Redirect hop to internal — blocked
        with pytest.raises(httpx.ConnectError, match="Blocked SSRF"):
            transport.handle_request(
                httpx.Request("GET", "https://internal.example/b")
            )


class TestPinnedNetworkBackend:
    def test_connects_to_validated_ip_not_hostname(self, monkeypatch):
        """The TCP socket must use the checked IP, closing DNS rebinding."""
        stream = MagicMock()
        connect_tcp = MagicMock(return_value=stream)
        monkeypatch.setattr("httpcore.SyncBackend.connect_tcp", connect_tcp)

        backend = PinnedNetworkBackend(resolver=lambda h: ["93.184.216.34"])
        assert backend.connect_tcp("rebind.example", 443) is stream
        assert connect_tcp.call_args.args[:2] == ("93.184.216.34", 443)

    def test_never_connects_when_dns_changes_to_private_ip(self, monkeypatch):
        connect_tcp = MagicMock()
        monkeypatch.setattr("httpcore.SyncBackend.connect_tcp", connect_tcp)

        backend = PinnedNetworkBackend(resolver=lambda h: ["127.0.0.1"])
        with pytest.raises(Exception, match="Blocked SSRF"):
            backend.connect_tcp("rebind.example", 443)
        connect_tcp.assert_not_called()


class TestClient:
    def test_returns_httpx_client(self):
        with client(timeout=10, resolver=lambda h: ["1.1.1.1"]) as cl:
            assert isinstance(cl, httpx.Client)

    def test_timeout_applied(self):
        with client(timeout=15, connect_timeout=3, resolver=lambda h: ["1.1.1.1"]) as cl:
            assert cl.timeout.connect == 3.0
            assert cl.timeout.read == 15.0


class TestRetry:
    def test_success_first_try(self):
        call_count = 0

        @retry(max_attempts=3, initial_wait=0.01)
        def ok():
            nonlocal call_count
            call_count += 1
            return "ok"

        assert ok() == "ok"
        assert call_count == 1

    def test_retries_on_429(self):
        call_count = 0

        @retry(max_attempts=3, initial_wait=0.01)
        def fail_twice():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise httpx.HTTPStatusError(
                    "429", request=httpx.Request("GET", "http://x"), response=httpx.Response(429)
                )
            return "ok"

        assert fail_twice() == "ok"
        assert call_count == 3

    def test_gives_up_after_max_attempts(self):
        @retry(max_attempts=2, initial_wait=0.01)
        def always_fail():
            raise httpx.HTTPStatusError(
                "500", request=httpx.Request("GET", "http://x"), response=httpx.Response(500)
            )

        with pytest.raises(httpx.HTTPStatusError):
            always_fail()

    def test_does_not_retry_on_400(self):
        @retry(max_attempts=3, initial_wait=0.01)
        def client_error():
            raise httpx.HTTPStatusError(
                "400", request=httpx.Request("GET", "http://x"), response=httpx.Response(400)
            )

        with pytest.raises(httpx.HTTPStatusError):
            client_error()

    def test_retries_on_timeout(self):
        call_count = 0

        @retry(max_attempts=2, initial_wait=0.01)
        def timeout_once():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise httpx.TimeoutException("timeout")
            return "ok"

        assert timeout_once() == "ok"
        assert call_count == 2
