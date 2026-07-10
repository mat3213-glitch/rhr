"""Tests for collectors/http_util.py — SSRF protection, retry, safe client."""
from __future__ import annotations

import math
from unittest.mock import MagicMock, patch

import httpx
import pytest

from collectors.http_util import (
    _is_blocked_host,
    client,
    retry,
    SafeRedirectTransport,
)


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

    def test_metadata_google(self):
        assert _is_blocked_host("metadata.google.internal") is True

    def test_public_host(self):
        assert _is_blocked_host("api.github.com") is False
        assert _is_blocked_host("example.com") is False
        assert _is_blocked_host("1.1.1.1") is False

    def test_private_out_of_range(self):
        assert _is_blocked_host("11.0.0.1") is False
        assert _is_blocked_host("172.32.0.1") is False


class TestSafeRedirectTransport:
    def test_blocks_private_ip(self):
        inner = MagicMock()
        transport = SafeRedirectTransport(inner)
        req = httpx.Request("GET", "http://127.0.0.1/secret")
        with pytest.raises(httpx.ConnectError, match="Blocked SSRF"):
            transport.handle_request(req)
        inner.handle_request.assert_not_called()

    def test_allows_public_host(self):
        inner = MagicMock()
        inner.handle_response.return_value = httpx.Response(200)
        transport = SafeRedirectTransport(inner)
        req = httpx.Request("GET", "https://api.github.com/data")
        transport.handle_request(req)
        inner.handle_request.assert_called_once()


class TestClient:
    def test_returns_httpx_client(self):
        with client(timeout=10) as cl:
            assert isinstance(cl, httpx.Client)

    def test_timeout_applied(self):
        with client(timeout=15, connect_timeout=3) as cl:
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
