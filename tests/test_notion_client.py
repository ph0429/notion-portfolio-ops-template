import unittest
from unittest.mock import patch

import requests

from portfolio_sync.notion import NotionClient


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self) -> dict:
        return self._payload


class _FakeSession:
    def __init__(self, events: list[object]) -> None:
        self.events = list(events)
        self.headers: dict[str, str] = {}

    def request(self, method: str, url: str, json: dict | None = None, timeout: int = 60) -> _FakeResponse:
        event = self.events.pop(0)
        if isinstance(event, Exception):
            raise event
        return event


class NotionClientRequestTest(unittest.TestCase):
    @patch("portfolio_sync.notion.time.sleep", return_value=None)
    def test_request_retries_connection_error(self, _sleep: object) -> None:
        client = NotionClient("token", "2022-06-28")
        client.session = _FakeSession(
            [
                requests.ConnectionError("boom"),
                _FakeResponse(200, {"ok": True}),
            ]
        )

        response = client._request("GET", "/pages/demo")

        self.assertEqual(response, {"ok": True})

    @patch("portfolio_sync.notion.time.sleep", return_value=None)
    def test_request_retries_transient_status(self, _sleep: object) -> None:
        client = NotionClient("token", "2022-06-28")
        client.session = _FakeSession(
            [
                _FakeResponse(503, text="service unavailable"),
                _FakeResponse(200, {"ok": True}),
            ]
        )

        response = client._request("GET", "/pages/demo")

        self.assertEqual(response, {"ok": True})


if __name__ == "__main__":
    unittest.main()
