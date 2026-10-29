from __future__ import annotations

import re
from typing import TYPE_CHECKING, cast

from colosseum.context import get_context
from colosseum.decorators import (
    VerificationResult,
    measurement,
    missing_measurement_result,
    verification,
)

from colosseum_messaging.connections import get_http_client

if TYPE_CHECKING:
    from collections.abc import Mapping

_HTTP_COMMANDS = (
    "http.get",
    "http.post",
    "http.put",
    "http.delete",
    "http.request",
)


def _request(
    *,
    http_id: int,
    method: str,
    path: str,
    key: str,
    json_body: object = None,
    data: bytes | str | None = None,
    headers: Mapping[str, str] | None = None,
    timeout: float | None = None,
) -> dict[str, object]:
    _ = key
    return get_http_client(http_id).request(
        method,
        path,
        json_body=json_body,
        data=data,
        headers=headers,
        timeout=timeout,
    )


@measurement
def request(
    *,
    http_id: int,
    method: str,
    path: str,
    key: str,
    json: object = None,
    data: bytes | str | None = None,
    headers: Mapping[str, str] | None = None,
    timeout: float | None = None,
) -> dict[str, object]:
    """Send an HTTP request and record status code plus body.

    :param http_id: Configured ``messaging.http`` id from bench TOML.
    :param method: HTTP method (GET, POST, PUT, DELETE, ...).
    :param path: Path relative to configured ``base_url``.
    :param key: Unique measurement key within domain ``messaging``.
    :param json: Optional JSON-serializable body.
    :param data: Optional raw body (bytes or str).
    :param headers: Optional request headers.
    :param timeout: Optional per-request timeout override in seconds.

    :returns: ``{"status_code": int, "body": str, "headers": dict}``.
    """
    return _request(
        http_id=http_id,
        method=method,
        path=path,
        key=key,
        json_body=json,
        data=data,
        headers=headers,
        timeout=timeout,
    )


@measurement
def get(
    *,
    http_id: int,
    path: str,
    key: str,
    headers: Mapping[str, str] | None = None,
    timeout: float | None = None,
) -> dict[str, object]:
    """HTTP GET; see :func:`request`.

    :param http_id: Integer ID from the configured messaging.http row. Select an existing ID in
        that section.
    :param path: Request path relative to the configured base_url, including any query string.
    :param key: Evidence key for this operation. Keep distinct keys for separate facts; see the
        evidence lookup rules in the core guide.
    :param headers: Per-request HTTP header mapping; None uses no additional headers.
    :param timeout: Per-request network timeout in seconds; None uses the configured timeout.
        This does not wait for a business operation to finish.

    :returns: Response dictionary with integer status_code and decoded text body; error HTTP
        statuses are still recorded responses.
    """
    return _request(
        http_id=http_id,
        method="GET",
        path=path,
        key=key,
        headers=headers,
        timeout=timeout,
    )


@measurement
def post(
    *,
    http_id: int,
    path: str,
    key: str,
    json: object = None,
    data: bytes | str | None = None,
    headers: Mapping[str, str] | None = None,
    timeout: float | None = None,
) -> dict[str, object]:
    """HTTP POST; see :func:`request`.

    :param http_id: Integer ID from the configured messaging.http row. Select an existing ID in
        that section.
    :param path: Request path relative to the configured base_url, including any query string.
    :param key: Evidence key for this operation. Keep distinct keys for separate facts; see the
        evidence lookup rules in the core guide.
    :param json: JSON-serializable request body; mutually exclusive with data. None omits this
        body.
    :param data: Raw request body as bytes or text; mutually exclusive with json. None omits
        this body.
    :param headers: Per-request HTTP header mapping; None uses no additional headers.
    :param timeout: Per-request network timeout in seconds; None uses the configured timeout.
        This does not wait for a business operation to finish.

    :returns: Response dictionary with integer status_code and decoded text body; error HTTP
        statuses are still recorded responses.
    """
    return _request(
        http_id=http_id,
        method="POST",
        path=path,
        key=key,
        json_body=json,
        data=data,
        headers=headers,
        timeout=timeout,
    )


@measurement
def put(
    *,
    http_id: int,
    path: str,
    key: str,
    json: object = None,
    data: bytes | str | None = None,
    headers: Mapping[str, str] | None = None,
    timeout: float | None = None,
) -> dict[str, object]:
    """HTTP PUT; see :func:`request`.

    :param http_id: Integer ID from the configured messaging.http row. Select an existing ID in
        that section.
    :param path: Request path relative to the configured base_url, including any query string.
    :param key: Evidence key for this operation. Keep distinct keys for separate facts; see the
        evidence lookup rules in the core guide.
    :param json: JSON-serializable request body; mutually exclusive with data. None omits this
        body.
    :param data: Raw request body as bytes or text; mutually exclusive with json. None omits
        this body.
    :param headers: Per-request HTTP header mapping; None uses no additional headers.
    :param timeout: Per-request network timeout in seconds; None uses the configured timeout.
        This does not wait for a business operation to finish.

    :returns: Response dictionary with integer status_code and decoded text body; error HTTP
        statuses are still recorded responses.
    """
    return _request(
        http_id=http_id,
        method="PUT",
        path=path,
        key=key,
        json_body=json,
        data=data,
        headers=headers,
        timeout=timeout,
    )


@measurement
def delete(
    *,
    http_id: int,
    path: str,
    key: str,
    headers: Mapping[str, str] | None = None,
    timeout: float | None = None,
) -> dict[str, object]:
    """HTTP DELETE; see :func:`request`.

    :param http_id: Integer ID from the configured messaging.http row. Select an existing ID in
        that section.
    :param path: Request path relative to the configured base_url, including any query string.
    :param key: Evidence key for this operation. Keep distinct keys for separate facts; see the
        evidence lookup rules in the core guide.
    :param headers: Per-request HTTP header mapping; None uses no additional headers.
    :param timeout: Per-request network timeout in seconds; None uses the configured timeout.
        This does not wait for a business operation to finish.

    :returns: Response dictionary with integer status_code and decoded text body; error HTTP
        statuses are still recorded responses.
    """
    return _request(
        http_id=http_id,
        method="DELETE",
        path=path,
        key=key,
        headers=headers,
        timeout=timeout,
    )


def _lookup_http_measurement(key: str) -> object | None:
    ctx = get_context()
    for command in _HTTP_COMMANDS:
        row = ctx.db.get_measurement("messaging", command, key, row_index=0)
        if row is not None and row.value is not None:
            return cast("object", row.value)
    return None


@verification
def verify_status(
    *,
    key: str,
    expected: int,
    optional: bool = False,
) -> VerificationResult:
    """Verify a prior HTTP measurement has the expected status code.

    :param key: Evidence key for this operation. Keep distinct keys for separate facts; see the
        evidence lookup rules in the core guide.
    :param expected: Expected HTTP status code (for example 200).
    :param optional: When true, retain an unsuccessful outcome without failing the aggregate
        result. Commands and measurements also suppress their operation exception; a failed
        measurement returns None. Defaults to false.

    :returns: Recorded verification outcome (PASS, FAIL, ERROR, or BLOCKED), including the
        actual value when available.
    """
    value = _lookup_http_measurement(key)
    if value is None:
        return missing_measurement_result(key=key, optional=optional)
    if not isinstance(value, dict) or "status_code" not in value:
        return VerificationResult(
            status="ERROR",
            message=f"HTTP measurement {key!r} is not a status/body dict",
            optional=optional,
            actual=value,
        )
    actual = int(value["status_code"])
    if actual == int(expected):
        return VerificationResult(status="PASS", message="", optional=optional, actual=actual)
    return VerificationResult(
        status="FAIL",
        message=f"expected status {expected}, got {actual}",
        optional=optional,
        actual=actual,
    )


@verification
def verify_body_match(
    *,
    key: str,
    pattern: str,
    optional: bool = False,
) -> VerificationResult:
    """Verify a prior HTTP measurement body matches a regex.

    :param key: Evidence key for this operation. Keep distinct keys for separate facts; see the
        evidence lookup rules in the core guide.
    :param pattern: Regular expression searched in the recorded text; invalid expressions
        produce an error.
    :param optional: When true, retain an unsuccessful outcome without failing the aggregate
        result. Commands and measurements also suppress their operation exception; a failed
        measurement returns None. Defaults to false.

    :returns: Recorded verification outcome (PASS, FAIL, ERROR, or BLOCKED), including the
        actual value when available.
    """
    value = _lookup_http_measurement(key)
    if value is None:
        return missing_measurement_result(key=key, optional=optional)
    if not isinstance(value, dict) or "body" not in value:
        return VerificationResult(
            status="ERROR",
            message=f"HTTP measurement {key!r} is not a status/body dict",
            optional=optional,
            actual=value,
        )
    body = str(value["body"])
    if re.search(pattern, body):
        return VerificationResult(status="PASS", message="", optional=optional, actual=body)
    return VerificationResult(
        status="FAIL",
        message=f"pattern {pattern!r} not found in {body!r}",
        optional=optional,
        actual=body,
    )
