"""Cookie jar on the live HTTP client."""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING

from colosseum_messaging.http.client import HttpClientWrapper

if TYPE_CHECKING:
    import pytest


def _client() -> HttpClientWrapper:
    return HttpClientWrapper(
        {"base_url": "https://bench.invalid", "driver": "http", "verify_tls": False},
    )


def test_same_origin_redirect_sends_set_cookie(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []
    responses = [
        (302, "", "https://bench.invalid/next", [("Set-Cookie", "sid=secret; Path=/")]),
        (200, "ok", None, []),
    ]

    def _exchange(
        _self: HttpClientWrapper,
        method: str,
        url: str,
        body: bytes | None,
        headers: dict[str, str],
        _timeout: float,
    ) -> tuple[int, str, str | None, list[tuple[str, str]]]:
        _ = method, body
        calls.append({"url": url, "headers": dict(headers)})
        status, text, location, pairs = responses[len(calls) - 1]
        return status, text, location, pairs

    monkeypatch.setattr(HttpClientWrapper, "_exchange", _exchange)
    result = _client().request("GET", "/start")
    assert result["status_code"] == 200
    assert result["headers"] == {}
    forwarded = calls[1]["headers"]
    assert isinstance(forwarded, dict)
    assert forwarded["Cookie"] == "sid=secret"


def test_cross_origin_redirect_drops_stored_cookies(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []
    responses = [
        (307, "", "https://other.invalid/receive", [("Set-Cookie", "sid=secret")]),
        (200, "ok", None, []),
    ]

    def _exchange(
        _self: HttpClientWrapper,
        method: str,
        url: str,
        body: bytes | None,
        headers: dict[str, str],
        _timeout: float,
    ) -> tuple[int, str, str | None, list[tuple[str, str]]]:
        _ = method, body
        calls.append({"url": url, "headers": dict(headers)})
        status, text, location, pairs = responses[len(calls) - 1]
        return status, text, location, pairs

    monkeypatch.setattr(HttpClientWrapper, "_exchange", _exchange)
    _client().request("GET", "/start", headers={"Cookie": "sid=old"})
    forwarded = calls[1]["headers"]
    assert isinstance(forwarded, dict)
    assert "Cookie" not in forwarded
    assert "cookie" not in {name.lower() for name in forwarded}


def test_localhost_cookie_is_resent_on_the_next_request() -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/login":
                self.send_response(200)
                self.send_header("Set-Cookie", "lab_session=ok; Path=/")
                self.send_header("X-Trace", "login")
                self.end_headers()
                self.wfile.write(b"in")
                return
            seen = "lab_session=ok" in (self.headers.get("Cookie") or "")
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"seen" if seen else b"missing")

        def log_message(self, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        client = HttpClientWrapper(
            {"base_url": f"http://{host}:{port}", "driver": "http"},
        )
        login = client.request("GET", "/login")
        headers = login["headers"]
        assert isinstance(headers, dict)
        assert headers["Set-Cookie"] == "lab_session=ok; Path=/"
        assert headers["X-Trace"] == "login"
        again = client.request("GET", "/radio")
        assert again["body"] == "seen"
    finally:
        server.shutdown()
        server.server_close()
