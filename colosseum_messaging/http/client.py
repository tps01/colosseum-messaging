from __future__ import annotations

import json
import ssl
from email.message import Message
from http.client import HTTPConnection, HTTPException, HTTPSConnection
from http.cookiejar import CookieJar, DefaultCookiePolicy
from typing import TYPE_CHECKING, cast
from urllib.parse import SplitResult, urljoin, urlsplit
from urllib.request import Request

from colosseum.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Mapping
    from http.client import HTTPResponse

_logger = get_logger("colosseum.messaging.http")
_ALLOWED_DRIVERS = frozenset({"sim", "http"})
_ALLOWED_SCHEMES = frozenset({"http", "https"})
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_MAX_REDIRECTS = 5
_SENSITIVE_HEADERS = frozenset({"authorization", "cookie"})
_BODY_HEADERS = frozenset({"content-length", "transfer-encoding"})


class _CookieHeaderResponse:
    """Minimal response facade for ``CookieJar.extract_cookies``."""

    def __init__(self, header_pairs: list[tuple[str, str]]) -> None:
        message = Message()
        for name, value in header_pairs:
            message.add_header(name, value)
        self._message = message

    def info(self) -> Message:
        return self._message


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
        self._cookies = CookieJar(policy=DefaultCookiePolicy(rfc2965=False))
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
        method_u, url, body, req_headers, req_timeout = self._prepare_request(
            method, path, json_body=json_body, data=data, headers=headers, timeout=timeout,
        )
        _logger.debug("HTTP %s %s timeout=%ss", method_u, url, req_timeout)
        if self._sim:
            return self._sim_request(method_u, path, body=body)
        status_code, text, header_pairs = self._follow_redirects(
            method_u, url, body, req_headers, req_timeout,
        )
        return _finalize_response(status_code, text, header_pairs)

    def _prepare_request(
        self,
        method: str,
        path: str,
        *,
        json_body: object,
        data: bytes | str | None,
        headers: Mapping[str, str] | None,
        timeout: float | None,
    ) -> tuple[str, str, bytes | None, dict[str, str], float]:
        method_u = method.upper()
        url = urljoin(self._base_url, path.lstrip("/"))
        req_timeout = self._timeout if timeout is None else float(timeout)
        req_headers = dict(headers or {})
        body: bytes | None = None
        if json_body is not None and data is not None:
            raise ValueError("http request cannot set both json and data")
        if json_body is not None:
            body = json.dumps(json_body).encode("utf-8")
            req_headers.setdefault("Content-Type", "application/json")
        elif data is not None:
            body = data.encode("utf-8") if isinstance(data, str) else data
        return method_u, url, body, req_headers, req_timeout

    def _follow_redirects(
        self,
        method: str,
        url: str,
        body: bytes | None,
        headers: dict[str, str],
        timeout: float,
    ) -> tuple[int, str, list[tuple[str, str]]]:
        redirects = 0
        method_u = method
        req_headers = self._with_cookies(url, headers)
        try:
            while True:
                status_code, text, location, header_pairs = self._exchange(
                    method_u, url, body, req_headers, timeout,
                )
                self._store_cookies(url, header_pairs)
                if not (
                    status_code in _REDIRECT_STATUSES
                    and location
                    and redirects < _MAX_REDIRECTS
                ):
                    return status_code, text, header_pairs
                redirects += 1
                next_url = urljoin(url, location)
                method_u, body, req_headers = _rewrite_redirect(
                    status_code, method_u, url, next_url, body, req_headers,
                )
                url = next_url
                req_headers = self._with_cookies(url, req_headers)
        except (HTTPException, TimeoutError, OSError, ValueError) as exc:
            raise RuntimeError(f"HTTP {method_u} {url} failed: {exc}") from exc

    def _exchange(
        self,
        method: str,
        url: str,
        body: bytes | None,
        headers: Mapping[str, str],
        timeout: float,
    ) -> tuple[int, str, str | None, list[tuple[str, str]]]:
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
            header_pairs = [(str(name), str(value)) for name, value in response.getheaders()]
        finally:
            connection.close()
        return status, raw.decode("utf-8", errors="replace"), location, header_pairs

    def _with_cookies(self, url: str, headers: Mapping[str, str]) -> dict[str, str]:
        request = Request(url)
        self._cookies.add_cookie_header(request)
        merged: dict[str, str] = {}
        jar_cookie = request.get_header("Cookie") or ""
        for part in jar_cookie.split(";"):
            if "=" not in part:
                continue
            name, value = part.split("=", 1)
            token = name.strip()
            if token:
                merged[token] = value.strip()
        for name, value in headers.items():
            if name.lower() != "cookie":
                continue
            for part in value.split(";"):
                if "=" not in part:
                    continue
                cookie_name, cookie_value = part.split("=", 1)
                token = cookie_name.strip()
                if token:
                    merged[token] = cookie_value.strip()
        out = {name: value for name, value in headers.items() if name.lower() != "cookie"}
        if merged:
            out["Cookie"] = "; ".join(f"{name}={value}" for name, value in merged.items())
        return out

    def _store_cookies(self, url: str, header_pairs: list[tuple[str, str]]) -> None:
        request = Request(url)
        # CookieJar only needs ``info()`` with Set-Cookie; not a live socket response.
        response = cast("HTTPResponse", _CookieHeaderResponse(header_pairs))
        self._cookies.extract_cookies(response, request)

    def _sim_request(self, method: str, path: str, *, body: bytes | None) -> dict[str, object]:
        payload = "" if body is None else body.decode("utf-8", errors="replace")
        body_text = f"{method} {path}"
        if payload:
            body_text = f"{body_text} {payload}"
        return {"status_code": 200, "body": body_text, "headers": {}}

    def close(self) -> None:
        return


def _rewrite_redirect(
    status_code: int,
    method: str,
    current_url: str,
    next_url: str,
    body: bytes | None,
    headers: dict[str, str],
) -> tuple[str, bytes | None, dict[str, str]]:
    _require_http_url(next_url)
    current_origin = _origin(current_url)
    next_origin = _origin(next_url)
    if current_origin[0] == "https" and next_origin[0] == "http":
        raise ValueError(
            f"Refusing HTTPS to HTTP redirect from {current_url} to {next_url}",
        )
    # 301/302/303 already become GET with no body, including same-origin.
    # 307/308 keep the method and body only while the origin stays the same.
    method_u = method
    req_headers = headers
    req_body = body
    if status_code in {301, 302, 303} and method_u not in {"GET", "HEAD"}:
        method_u = "GET"
        req_body = None
        req_headers = _headers_without(req_headers, _BODY_HEADERS)
    if current_origin != next_origin:
        req_headers = _headers_without(req_headers, _SENSITIVE_HEADERS)
        if req_body is not None:
            req_body = None
            req_headers = _headers_without(req_headers, _BODY_HEADERS)
    return method_u, req_body, req_headers


def _finalize_response(
    status_code: int,
    text: str,
    header_pairs: list[tuple[str, str]],
) -> dict[str, object]:
    preview = text[:200] + ("..." if len(text) > 200 else "")
    _logger.debug("HTTP status=%s body=%r", status_code, preview)
    return {
        "status_code": status_code,
        "body": text,
        "headers": _header_map(header_pairs),
    }


def _origin(url: str) -> tuple[str, str, int]:
    parsed = urlsplit(url)
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower()
    if parsed.port is not None:
        port = parsed.port
    elif scheme == "https":
        port = 443
    else:
        port = 80
    return scheme, host, port


def _headers_without(headers: Mapping[str, str], names: frozenset[str]) -> dict[str, str]:
    return {name: value for name, value in headers.items() if name.lower() not in names}


def _header_map(pairs: list[tuple[str, str]]) -> dict[str, str]:
    return dict(pairs)


def _require_http_url(url: str) -> SplitResult:
    parsed = urlsplit(url)
    if parsed.scheme not in _ALLOWED_SCHEMES or not parsed.hostname:
        raise ValueError(f"messaging.http URL must be http(s), got {url!r}")
    return parsed
