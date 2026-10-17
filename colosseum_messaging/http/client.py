from __future__ import annotations

import json
import ssl
from http.client import HTTPConnection, HTTPException, HTTPSConnection
from typing import TYPE_CHECKING
from urllib.parse import SplitResult, urljoin, urlsplit

from colosseum.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Mapping

_logger = get_logger("colosseum.messaging.http")
_ALLOWED_DRIVERS = frozenset({"sim", "http"})
_ALLOWED_SCHEMES = frozenset({"http", "https"})
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_MAX_REDIRECTS = 5


class HttpClientWrapper:
    def __init__(self, config: Mapping[str, object]) -> None:
        self._base_url = str(config["base_url"]).rstrip("/") + "/"
        self._timeout = float(str(config.get("timeout", 10.0)))
        self._verify_tls = bool(config.get("verify_tls", True))
        _require_http_url(self._base_url)
        driver = str(config.get("driver", "http")).lower()
        if driver not in _ALLOWED_DRIVERS:
            raise ValueError(
                f"messaging.http driver must be one of {sorted(_ALLOWED_DRIVERS)}, got {driver!r}",
            )
        self._sim = driver == "sim"
        if self._sim:
            _logger.debug("HTTP client sim mode enabled base_url=%s", self._base_url)

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: object = None,
        data: bytes | str | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> dict[str, object]:
        method_u = method.upper()
        url = urljoin(self._base_url, path.lstrip("/"))
        req_timeout = self._timeout if timeout is None else float(timeout)
        req_headers = dict(headers or {})
        body: bytes | None = None
        if json_body is not None:
            body = json.dumps(json_body).encode("utf-8")
            req_headers.setdefault("Content-Type", "application/json")
        elif data is not None:
            body = data.encode("utf-8") if isinstance(data, str) else data

        _logger.debug("HTTP %s %s timeout=%ss", method_u, url, req_timeout)
        if self._sim:
            return self._sim_request(method_u, path, body=body)

        redirects = 0
        try:
            while True:
                status_code, text, location = self._exchange(
                    method_u, url, body, req_headers, req_timeout,
                )
                if (
                    status_code in _REDIRECT_STATUSES
                    and location
                    and redirects < _MAX_REDIRECTS
                ):
                    redirects += 1
                    url = urljoin(url, location)
                    if status_code in {301, 302, 303} and method_u not in {"GET", "HEAD"}:
                        method_u = "GET"
                        body = None
                    continue
                break
        except (HTTPException, TimeoutError, OSError, ValueError) as exc:
            raise RuntimeError(f"HTTP {method_u} {url} failed: {exc}") from exc

        preview = text[:200] + ("..." if len(text) > 200 else "")
        _logger.debug("HTTP status=%s body=%r", status_code, preview)
        return {"status_code": status_code, "body": text}

    def _exchange(
        self,
        method: str,
        url: str,
        body: bytes | None,
        headers: Mapping[str, str],
        timeout: float,
    ) -> tuple[int, str, str | None]:
        parsed = _require_http_url(url)
        hostname = parsed.hostname or ""
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        target = parsed.path or "/"
        if parsed.query:
            target = f"{target}?{parsed.query}"
        if parsed.scheme == "https":
            context = ssl.create_default_context()
            if not self._verify_tls:
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
            connection: HTTPConnection = HTTPSConnection(
                hostname, port, timeout=timeout, context=context,
            )
        else:
            connection = HTTPConnection(hostname, port, timeout=timeout)
        try:
            connection.request(method, target, body=body, headers=dict(headers))
            response = connection.getresponse()
            raw = response.read()
            status = int(response.status)
            location = response.getheader("Location")
        finally:
            connection.close()
        return status, raw.decode("utf-8", errors="replace"), location

    def _sim_request(self, method: str, path: str, *, body: bytes | None) -> dict[str, object]:
        payload = "" if body is None else body.decode("utf-8", errors="replace")
        body_text = f"{method} {path}"
        if payload:
            body_text = f"{body_text} {payload}"
        return {"status_code": 200, "body": body_text}

    def close(self) -> None:
        return


def _require_http_url(url: str) -> SplitResult:
    parsed = urlsplit(url)
    if parsed.scheme not in _ALLOWED_SCHEMES or not parsed.hostname:
        raise ValueError(f"messaging.http URL must be http(s), got {url!r}")
    return parsed
