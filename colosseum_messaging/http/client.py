from __future__ import annotations

import json
import logging
import ssl
import urllib.error
import urllib.request
from collections.abc import Mapping
from urllib.parse import urljoin

_logger = logging.getLogger("colosseum.messaging.http")


class HttpClientWrapper:
    def __init__(self, config: Mapping[str, object]) -> None:
        self._config = dict(config)
        self._base_url = str(config["base_url"]).rstrip("/") + "/"
        self._timeout = float(str(config.get("timeout", 10.0)))
        self._verify_tls = bool(config.get("verify_tls", True))
        self._sim = str(config.get("driver", "http")).lower() == "sim"
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

        request = urllib.request.Request(url, data=body, method=method_u, headers=req_headers)
        context: ssl.SSLContext | None = None
        if url.lower().startswith("https") and not self._verify_tls:
            context = ssl._create_unverified_context()  # nosec B323  # bench opt-out

        try:
            with urllib.request.urlopen(  # nosec B310  # bench HTTP to configured base_url
                request, timeout=req_timeout, context=context
            ) as response:
                raw = response.read()
                status_code = int(response.status)
                text = raw.decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            status_code = int(exc.code)
            text = raw.decode("utf-8", errors="replace")
        except Exception as exc:
            raise RuntimeError(f"HTTP {method_u} {url} failed: {exc}") from exc

        preview = text[:200] + ("..." if len(text) > 200 else "")
        _logger.debug("HTTP status=%s body=%r", status_code, preview)
        return {"status_code": status_code, "body": text}

    def _sim_request(self, method: str, path: str, *, body: bytes | None) -> dict[str, object]:
        payload = "" if body is None else body.decode("utf-8", errors="replace")
        body_text = f"{method} {path}"
        if payload:
            body_text = f"{body_text} {payload}"
        return {"status_code": 200, "body": body_text}

    def close(self) -> None:
        return
