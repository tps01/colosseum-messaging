from __future__ import annotations

import re
from typing import cast

from colosseum.context import require_context
from colosseum.decorators import (
    VerificationResult,
    command,
    measurement,
    missing_measurement_result,
    verification,
)

from colosseum_messaging.connections import get_mqtt_client


@command
def publish(*, mqtt_id: int, topic: str, payload: str, key: str = "") -> None:
    """Publish an MQTT message.

    :param mqtt_id: Configured ``messaging.mqtt`` id from bench TOML.
    :param topic: MQTT topic.
    :param payload: Message payload.
    :param key: Optional evidence key for the command row.
    """
    _ = key
    get_mqtt_client(mqtt_id).publish(topic, payload)


@measurement
def receive(
    *,
    mqtt_id: int,
    key: str,
    topic: str | None = None,
    timeout: float = 1.0,
) -> dict[str, str]:
    """Receive one MQTT message.

    :param mqtt_id: Configured ``messaging.mqtt`` id from bench TOML.
    :param key: Unique measurement key within domain ``messaging``.
    :param topic: Optional subscribe/filter topic (defaults to configured ``topic``).
    :param timeout: Wait timeout in seconds.

    :returns: ``{"topic": str, "payload": str}``.
    """
    _ = key
    return get_mqtt_client(mqtt_id).receive(timeout=timeout, topic=topic)


def _lookup_payload(key: str) -> object | None:
    row = require_context().db.get_measurement(
        "messaging", "mqtt.receive", key, row_index=0
    )
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
    """Verify a prior MQTT ``receive`` payload matches a regex."""
    value = _lookup_payload(key)
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
