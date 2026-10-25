from __future__ import annotations

import re
from typing import TYPE_CHECKING, cast

from colosseum.context import get_context
from colosseum.decorators import (
    VerificationResult,
    command,
    measurement,
    missing_measurement_result,
    verification,
)

from colosseum_messaging._listen import drain_writes, make_handler, verify_recorded
from colosseum_messaging.connections import get_mqtt_client

if TYPE_CHECKING:
    from collections.abc import Callable

_LISTEN_COMMAND = "mqtt.listen"


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
    row = get_context().db.get_measurement(
        "messaging", "mqtt.receive", key, row_index=0,
    )
    if row is not None and row.value is not None:
        return cast("object", row.value)
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


@command
def listen(
    *,
    mqtt_id: int,
    key: str,
    topic: str | None = None,
    fail_pattern: str = "",
    on_message: Callable[[dict[str, str]], None] | None = None,
) -> None:
    r"""Record each MQTT message until ``stop_listen``.

    Every message is a ``messaging`` / ``mqtt.listen`` measurement. ``value``
    is ``{"topic", "payload"}``. ``fail_pattern`` marks a matching payload
    ``FAIL``. ``on_message``, when set, runs after that insert.

    Example::

        col.messaging.mqtt.listen(
            mqtt_id=1,
            key="status",
            topic="device/#",
            fail_pattern=r"\b(ERR|FAULT|offline)\b",
        )
        col.messaging.mqtt.stop_listen(mqtt_id=1, key="status")
        col.messaging.mqtt.verify_listen(
            key="status", max_silence_s=0.5, min_received=1,
        )

    :param mqtt_id: Configured ``messaging.mqtt`` id from bench TOML.
    :param key: Measurement key shared with ``stop_listen`` and ``verify_listen``.
    :param topic: Optional subscribe filter. Defaults to the configured topic.
    :param fail_pattern: Regex applied to ``payload``. Empty matches nothing.
    :param on_message: Optional hook called with ``{"topic", "payload"}``.
    """
    get_mqtt_client(mqtt_id).start_listen(
        make_handler(
            command=_LISTEN_COMMAND,
            key=key,
            fail_pattern=fail_pattern,
            on_message=on_message,
        ),
        topic=topic,
    )


@command
def stop_listen(*, mqtt_id: int, key: str = "") -> None:
    """Stop an MQTT listen thread and drain measurement writes.

    Example::

        col.messaging.mqtt.stop_listen(mqtt_id=1, key="status")

    :param mqtt_id: Configured ``messaging.mqtt`` id passed to ``listen``.
    :param key: Evidence key for this command. Use the ``listen`` key.
    """
    _ = key
    get_mqtt_client(mqtt_id).stop_listen()
    drain_writes()


@verification
def verify_listen(
    *,
    key: str,
    max_matched: int = 0,
    max_silence_s: float | None = None,
    min_received: int = 0,
    optional: bool = False,
) -> VerificationResult:
    """Judge stored ``mqtt.listen`` rows for failures, errors, and silence.

    ``max_silence_s`` is the longest allowed gap between stored timestamps
    after the first message. Startup delay before the first row is not a gap.

    Example::

        col.messaging.mqtt.verify_listen(
            key="status", max_silence_s=0.5, min_received=1,
        )
    """
    return verify_recorded(
        command=_LISTEN_COMMAND,
        key=key,
        max_matched=max_matched,
        max_silence_s=max_silence_s,
        min_received=min_received,
        optional=optional,
    )


@command
def start_sender(*, mqtt_id: int, key: str = "") -> None:
    """Start a thread that publishes queued MQTT payloads.

    Direct ``publish`` stays available while a listen thread is running.
    It raises once ``start_sender`` owns publishing.

    Example::

        col.messaging.mqtt.start_sender(mqtt_id=1)
        col.messaging.mqtt.enqueue(mqtt_id=1, topic="device/cmd", payload="arm")
        col.messaging.mqtt.stop_sender(mqtt_id=1)

    :param mqtt_id: Configured ``messaging.mqtt`` id from bench TOML.
    :param key: Optional evidence key for the command row.
    """
    _ = key
    get_mqtt_client(mqtt_id).start_sender()


@command
def enqueue(*, mqtt_id: int, topic: str, payload: str, key: str = "") -> None:
    """Queue one MQTT publish. ``start_sender`` must already be running.

    Example::

        col.messaging.mqtt.enqueue(mqtt_id=1, topic="device/cmd", payload="arm")

    :param mqtt_id: Configured ``messaging.mqtt`` id from bench TOML.
    :param topic: MQTT topic.
    :param payload: Message payload.
    :param key: Optional evidence key for the command row.
    """
    _ = key
    get_mqtt_client(mqtt_id).enqueue(topic, payload)


@command
def stop_sender(*, mqtt_id: int, key: str = "") -> None:
    """Stop an MQTT send thread after it delivers queued payloads.

    Example::

        col.messaging.mqtt.stop_sender(mqtt_id=1)

    :param mqtt_id: Configured ``messaging.mqtt`` id passed to ``start_sender``.
    :param key: Optional evidence key for the command row.
    """
    _ = key
    get_mqtt_client(mqtt_id).stop_sender()
