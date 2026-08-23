from __future__ import annotations

import re
from typing import cast

from colosseum.context import get_context
from colosseum.decorators import (
    VerificationResult,
    command,
    measurement,
    missing_measurement_result,
    verification,
)

from colosseum_messaging.connections import get_zmq_client


@command
def send(*, zmq_id: int, payload: str, topic: str = "", key: str = "") -> None:
    """Send a ZMQ PUB message.

    :param zmq_id: Configured ``messaging.zmq`` id with ``socket = "pub"``.
    :param payload: Message payload.
    :param topic: Optional topic prefix (multipart when non-empty).
    :param key: Optional evidence key for the command row.
    """
    _ = key
    get_zmq_client(zmq_id).send(payload, topic=topic)


@measurement
def receive(*, zmq_id: int, key: str, timeout: float = 1.0) -> dict[str, str]:
    """Receive one ZMQ SUB message.

    :param zmq_id: Configured ``messaging.zmq`` id with ``socket = "sub"``.
    :param key: Unique measurement key within domain ``messaging``.
    :param timeout: Wait timeout in seconds.

    :returns: ``{"topic": str, "payload": str}``.
    """
    _ = key
    return get_zmq_client(zmq_id).receive(timeout=timeout)


def _lookup_payload(key: str, commands: tuple[str, ...]) -> object | None:
    ctx = get_context()
    for command_name in commands:
        row = ctx.db.get_measurement("messaging", command_name, key, row_index=0)
        if row is not None and row.value is not None:
            return cast(object, row.value)
    return None


@verification
def verify_payload_match(
    *,
    key: str,
    pattern: str,
    optional: bool = False,
) -> VerificationResult:
    """Verify a prior ZMQ ``receive`` payload matches a regex."""
    value = _lookup_payload(key, ("zmq.receive",))
    if value is None:
        return missing_measurement_result(key=key, optional=optional)
    if isinstance(value, dict) and "payload" in value:
        payload = str(value["payload"])
    else:
        payload = str(value)
    if re.search(pattern, payload):
        return VerificationResult(status="PASS", message="", optional=optional, actual=payload)
    return VerificationResult(
        status="FAIL",
        message=f"pattern {pattern!r} not found in {payload!r}",
        optional=optional,
        actual=payload,
    )
