"""Live HTTP redirect policy."""

from __future__ import annotations

import pytest
from colosseum_messaging.http.client import HttpClientWrapper


def _client() -> HttpClientWrapper:
    return HttpClientWrapper(
        {"base_url": "https://bench.invalid", "driver": "http", "verify_tls": False},
    )


def _script(monkeypatch: pytest.MonkeyPatch, responses: list[tuple[int, str, str | None]]):
    calls: list[dict[str, object]] = []

    def _exchange(
        _self: HttpClientWrapper,
        method: str,
        url: str,
        body: bytes | None,
        headers: dict[str, str],
        _timeout: float,
    ) -> tuple[int, str, str | None]:
        calls.append(
            {"method": method, "url": url, "body": body, "headers": dict(headers)},
        )
        status, text, location = responses[len(calls) - 1]
        return status, text, location

    monkeypatch.setattr(HttpClientWrapper, "_exchange", _exchange)
    return calls


def test_same_origin_307_keeps_body_and_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _script(
        monkeypatch,
        [(307, "", "https://bench.invalid/next"), (200, "ok", None)],
    )
    result = _client().request(
        "POST",
        "/start",
        data=b"secret-body",
        headers={"Authorization": "Bearer bench-token", "Cookie": "sid=1", "X-Run": "keep"},
    )
    assert result == {"status_code": 200, "body": "ok"}
    forwarded = calls[1]
    assert forwarded["method"] == "POST"
    assert forwarded["url"] == "https://bench.invalid/next"
    assert forwarded["body"] == b"secret-body"
    headers = forwarded["headers"]
    assert isinstance(headers, dict)
    assert headers["Authorization"] == "Bearer bench-token"
    assert headers["Cookie"] == "sid=1"


def test_same_origin_302_becomes_get_without_body(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _script(
        monkeypatch,
        [(302, "", "https://bench.invalid/next"), (200, "ok", None)],
    )
    _client().request(
        "POST",
        "/start",
        data=b"secret-body",
        headers={"Authorization": "Bearer bench-token"},
    )
    forwarded = calls[1]
    assert forwarded["method"] == "GET"
    assert forwarded["body"] is None
    headers = forwarded["headers"]
    assert isinstance(headers, dict)
    assert headers["Authorization"] == "Bearer bench-token"


def test_cross_origin_307_strips_secrets_and_drops_body(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _script(
        monkeypatch,
        [(307, "", "https://other.invalid/receive"), (200, "ok", None)],
    )
    _client().request(
        "POST",
        "/start",
        data=b"secret-body",
        headers={
            "Authorization": "Bearer bench-token",
            "Cookie": "sid=1",
            "X-Run": "keep",
            "Content-Length": "11",
        },
    )
    forwarded = calls[1]
    assert forwarded["method"] == "POST"
    assert forwarded["url"] == "https://other.invalid/receive"
    assert forwarded["body"] is None
    headers = forwarded["headers"]
    assert isinstance(headers, dict)
    assert "Authorization" not in headers
    assert "Cookie" not in headers
    assert "Content-Length" not in headers
    assert headers["X-Run"] == "keep"


def test_https_to_http_redirect_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _script(
        monkeypatch,
        [(307, "", "http://other.invalid/receive"), (200, "should-not-run", None)],
    )
    with pytest.raises(RuntimeError, match="HTTPS to HTTP"):
        _client().request(
            "POST",
            "/start",
            data=b"secret-body",
            headers={"Authorization": "Bearer bench-token", "Cookie": "sid=1"},
        )
    assert len(calls) == 1
