"""Record each listened message, then check those rows."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from colosseum.context import get_context
from colosseum.database import MeasurementRow
from colosseum.decorators import VerificationResult, missing_measurement_result
from colosseum.logging import get_logger

_logger = get_logger("colosseum.messaging.listen")

if TYPE_CHECKING:
    from collections.abc import Callable

_DOMAIN = "messaging"
_DEVICE_STATUSES = frozenset({"PASS", "FAIL"})


def make_handler(
    *,
    command: str,
    key: str,
    fail_pattern: str,
    on_message: Callable[[dict[str, str]], None] | None,
) -> Callable[[dict[str, str]], None]:
    """Save every message, then call ``on_message``.

    An empty ``fail_pattern`` leaves every device row ``PASS``. A hook error
    is its own ``ERROR`` row and does not replace the device row.
    """
    pattern = re.compile(fail_pattern) if fail_pattern else None
    index = 0

    def handler(message: dict[str, str]) -> None:
        nonlocal index
        topic = str(message.get("topic", ""))
        payload = str(message.get("payload", ""))
        status = "FAIL" if pattern is not None and pattern.search(payload) else "PASS"
        row_index = index
        index += 1
        _enqueue(
            command=command,
            key=key,
            row_index=row_index,
            value={"topic": topic, "payload": payload},
            status=status,
        )
        if on_message is None:
            return
        try:
            on_message(message)
        except Exception as exc:
            _logger.exception("Listen hook failed for %s key=%s", command, key)
            err_index = index
            index += 1
            _enqueue(
                command=command,
                key=key,
                row_index=err_index,
                value={"topic": topic, "payload": payload, "error": str(exc)},
                status="ERROR",
            )

    return handler


def drain_writes() -> None:
    """Wait until listener rows are committed."""
    try:
        ctx = get_context()
    except RuntimeError:
        return
    if ctx.db.is_initialized():
        ctx.db.drain()


def verify_recorded(
    *,
    command: str,
    key: str,
    max_matched: int,
    max_silence_s: float | None,
    min_received: int,
    optional: bool,
) -> VerificationResult:
    """Read stored listen rows and judge the stream they record."""
    drain_writes()
    try:
        ctx = get_context()
    except RuntimeError:
        return missing_measurement_result(key=key, optional=optional)
    if not ctx.db.is_initialized():
        return missing_measurement_result(key=key, optional=optional)
    rows = ctx.db.list_measurements(_DOMAIN, command, key)
    device = [row for row in rows if row.status in _DEVICE_STATUSES]
    if not device and min_received > 0:
        return missing_measurement_result(key=key, optional=optional)
    received = len(device)
    matched = sum(1 for row in device if row.status == "FAIL")
    errors = sum(1 for row in rows if row.status == "ERROR")
    max_gap_s = _max_gap_s(device)
    latest = _latest_payload(device)
    actual = {
        "received": received,
        "matched": matched,
        "errors": errors,
        "max_gap_s": max_gap_s,
        "latest": latest,
    }
    reasons: list[str] = []
    if matched > max_matched:
        reasons.append(f"matched {matched} > {max_matched}")
    if errors:
        reasons.append(f"errors {errors}")
    if received < min_received:
        reasons.append(f"received {received} < {min_received}")
    if max_silence_s is not None and max_gap_s > max_silence_s:
        reasons.append(f"max_gap_s {max_gap_s:.3f} > {max_silence_s}")
    if reasons:
        return VerificationResult(
            status="FAIL",
            message="; ".join(reasons),
            optional=optional,
            actual=actual,
        )
    return VerificationResult(status="PASS", message="", optional=optional, actual=actual)


def _enqueue(
    *,
    command: str,
    key: str,
    row_index: int,
    value: dict[str, str],
    status: str,
) -> None:
    try:
        ctx = get_context()
    except RuntimeError:
        return
    if not ctx.db.is_initialized():
        return
    ctx.db.enqueue_measurement(
        MeasurementRow(
            domain=_DOMAIN,
            command=command,
            key=key,
            row_index=row_index,
            value=value,
            status=status,
            timestamp=datetime.now(timezone.utc).isoformat(),
        ),
    )


def _max_gap_s(rows: list[MeasurementRow]) -> float:
    stamps: list[datetime] = []
    for row in rows:
        if not row.timestamp:
            continue
        stamps.append(datetime.fromisoformat(row.timestamp))
    stamps.sort()
    if len(stamps) < 2:
        return 0.0
    max_gap = 0.0
    for index in range(1, len(stamps)):
        gap = (stamps[index] - stamps[index - 1]).total_seconds()
        if gap > max_gap:
            max_gap = gap
    return max_gap


def _latest_payload(rows: list[MeasurementRow]) -> str:
    if not rows:
        return ""
    row = max(rows, key=lambda item: item.row_index)
    value = row.value
    if isinstance(value, dict) and "payload" in value:
        return str(value["payload"])
    return "" if value is None else str(value)
