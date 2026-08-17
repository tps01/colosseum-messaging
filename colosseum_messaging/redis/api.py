from __future__ import annotations

import re
from collections.abc import Sequence

from colosseum.context import require_context
from colosseum.decorators import (
    MeasurementSource,
    VerificationResult,
    command,
    measurement,
    missing_measurement_result,
    verification,
)

from colosseum_messaging.connections import get_redis_client


@command
def set(*, redis_id: int, name: str, value: str, key: str = "") -> None:
    """Set a Redis string key.

    :param redis_id: Configured ``messaging.redis`` id from bench TOML.
    :param name: Redis key name.
    :param value: String value to store.
    :param key: Optional evidence key for the command row.
    """
    _ = key
    get_redis_client(redis_id).set(name, value)


@command
def publish(*, redis_id: int, channel: str, message: str, key: str = "") -> None:
    """Publish a message to a Redis channel.

    :param redis_id: Configured ``messaging.redis`` id from bench TOML.
    :param channel: Pub/sub channel name.
    :param message: Message payload.
    :param key: Optional evidence key for the command row.
    """
    _ = key
    get_redis_client(redis_id).publish(channel, message)


@measurement
def get(*, redis_id: int, name: str, key: str) -> str | None:
    """Get a Redis string key and record the value.

    :param redis_id: Configured ``messaging.redis`` id from bench TOML.
    :param name: Redis key name.
    :param key: Unique measurement key within domain ``messaging``.

    :returns: Decoded string value, or ``None`` when missing.
    """
    _ = key
    return get_redis_client(redis_id).get(name)


@measurement
def receive(*, redis_id: int, channel: str, key: str, timeout: float = 1.0) -> dict[str, str]:
    """Receive one Redis pub/sub message.

    :param redis_id: Configured ``messaging.redis`` id from bench TOML.
    :param channel: Channel to subscribe to / wait on.
    :param key: Unique measurement key within domain ``messaging``.
    :param timeout: Wait timeout in seconds.

    :returns: ``{"topic": channel, "payload": str}``.
    """
    _ = key
    return get_redis_client(redis_id).receive(channel, timeout=timeout)


@verification(sources=[MeasurementSource(domain="messaging", command="redis.get")])
def verify_value_match(
    *,
    key: str,
    pattern: str,
    optional: bool = False,
    sources: Sequence[MeasurementSource] | None = None,
) -> VerificationResult:
    """Verify a prior Redis ``get`` measurement matches a regex."""
    source_list = list(sources or [MeasurementSource("messaging", "redis.get")])
    actual = None
    for source in source_list:
        row = require_context().db.get_measurement(
            source.domain, source.command, key, row_index=0
        )
        if row is not None and row.value is not None:
            actual = str(row.value)
            break
    if actual is None:
        return missing_measurement_result(key=key, optional=optional)
    if re.search(pattern, actual):
        return VerificationResult(status="PASS", message="", optional=optional, actual=actual)
    return VerificationResult(
        status="FAIL",
        message=f"pattern {pattern!r} not found in {actual!r}",
        optional=optional,
        actual=actual,
    )
