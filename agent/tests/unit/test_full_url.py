"""Tests for _full_url URL reconstruction (critical for Twilio sig validation behind proxy)."""
from __future__ import annotations

from unittest.mock import MagicMock

from app.server import _full_url


def _mock_request(scheme: str, host: str, path: str, query: str = "") -> MagicMock:
    req = MagicMock()
    req.url.scheme = scheme
    req.url.path = path
    req.url.query = query
    req.headers = {"host": host}
    return req


def test_https_path_only() -> None:
    req = _mock_request(scheme="https", host="agent.example.com", path="/twilio/inbound")
    assert _full_url(req) == "https://agent.example.com/twilio/inbound"


def test_http_path_only() -> None:
    """When --proxy-headers is NOT set, scheme is http behind a TLS proxy. Documents the gotcha."""
    req = _mock_request(scheme="http", host="agent.example.com", path="/twilio/inbound")
    assert _full_url(req) == "http://agent.example.com/twilio/inbound"


def test_https_with_query() -> None:
    req = _mock_request(
        scheme="https",
        host="agent.example.com",
        path="/twilio/dial-owner",
        query="to=%2B15551112222",
    )
    assert _full_url(req) == "https://agent.example.com/twilio/dial-owner?to=%2B15551112222"


def test_empty_query_string_not_appended() -> None:
    req = _mock_request(scheme="https", host="agent.example.com", path="/x", query="")
    assert _full_url(req) == "https://agent.example.com/x"


def test_missing_host_header_yields_empty_host() -> None:
    req = MagicMock()
    req.url.scheme = "https"
    req.url.path = "/x"
    req.url.query = ""
    req.headers = {}
    assert _full_url(req) == "https:///x"
