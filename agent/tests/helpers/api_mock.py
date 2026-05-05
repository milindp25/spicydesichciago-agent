from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx


class FakeApi:
    """Records requests and returns canned responses for ApiClient tests."""

    def __init__(self, responder: Callable[[httpx.Request], httpx.Response]) -> None:
        self.requests: list[httpx.Request] = []
        self._responder = responder

    def transport(self) -> httpx.MockTransport:
        def handler(req: httpx.Request) -> httpx.Response:
            self.requests.append(req)
            return self._responder(req)

        return httpx.MockTransport(handler)


def json_responder(
    payload: dict[str, Any], status_code: int = 200
) -> Callable[[httpx.Request], httpx.Response]:
    def respond(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=payload)

    return respond
