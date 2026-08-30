"""U-MSG-HTTP: HTTP sim request specification."""

from __future__ import annotations

from colosseum_messaging.http.client import HttpClientWrapper


def test_sim_get_returns_status_and_body() -> None:
    client = HttpClientWrapper({"base_url": "http://127.0.0.1:8080", "driver": "sim"})
    result = client.request("GET", "/health")
    assert result["status_code"] == 200
    assert "GET /health" in result["body"]


def test_sim_post_includes_json_payload() -> None:
    client = HttpClientWrapper({"base_url": "http://127.0.0.1:8080", "driver": "sim"})
    result = client.request("POST", "/api", json_body={"a": 1})
    assert result["status_code"] == 200
    assert "POST /api" in result["body"]
    assert '"a": 1' in result["body"] or '"a":1' in result["body"]
