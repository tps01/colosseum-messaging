from __future__ import annotations

import re
from typing import TYPE_CHECKING

from colosseum.context import get_context
from colosseum.decorators import (
    VerificationResult,
    command,
    measurement,
    missing_measurement_result,
    verification,
)

from colosseum_messaging._listen import drain_writes, make_handler, verify_recorded
from colosseum_messaging.connections import get_redis_client

if TYPE_CHECKING:
    from collections.abc import Callable

_LISTEN_COMMAND = "redis.listen"


@command
def set(*, redis_id: int, name: str, value: str, key: str = "") -> None:  # noqa: A001
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


@verification
def verify_value_match(
    *,
    key: str,
    pattern: str,
    optional: bool = False,
) -> VerificationResult:
    """Verify a prior Redis ``get`` measurement matches a regex."""
    row = get_context().db.get_measurement("messaging", "redis.get", key, row_index=0)
    actual = None if row is None or row.value is None else str(row.value)
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


@command
def listen(
    *,
    redis_id: int,
    channel: str,
    key: str,
    fail_pattern: str = "",
    on_message: Callable[[dict[str, str]], None] | None = None,
) -> None:
    r"""Record each Redis pub/sub message until ``stop_listen``.

    Every message is a ``messaging`` / ``redis.listen`` measurement.
    ``value`` is ``{"topic", "payload"}``. ``fail_pattern`` marks a matching
    payload ``FAIL``. ``on_message``, when set, runs after that insert.
    Direct ``publish`` stays available while the listen thread is running.

    Example::

        col.messaging.redis.listen(
            redis_id=1,
            channel="events",
            key="status",
            fail_pattern=r"\b(ERR|FAULT|offline)\b",
        )
        col.messaging.redis.stop_listen(redis_id=1, key="status")
        col.messaging.redis.verify_listen(key="status", min_received=1)

    :param redis_id: Configured ``messaging.redis`` id from bench TOML.
    :param channel: Pub/sub channel to subscribe to.
    :param key: Measurement key shared with ``stop_listen`` and ``verify_listen``.
    :param fail_pattern: Regex applied to ``payload``. Empty matches nothing.
    :param on_message: Optional hook called with ``{"topic", "payload"}``.
    """
    get_redis_client(redis_id).start_listen(
        channel,
        make_handler(
            command=_LISTEN_COMMAND,
            key=key,
            fail_pattern=fail_pattern,
            on_message=on_message,
        ),
    )


@command
def stop_listen(*, redis_id: int, key: str = "") -> None:
    """Stop a Redis listen thread and drain measurement writes.

    Example::

        col.messaging.redis.stop_listen(redis_id=1, key="status")

    :param redis_id: Configured ``messaging.redis`` id passed to ``listen``.
    :param key: Evidence key for this command. Use the ``listen`` key.
    """
    _ = key
    get_redis_client(redis_id).stop_listen()
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
    """Judge stored ``redis.listen`` rows for failures, errors, and silence.

    ``max_silence_s`` is the longest allowed gap between stored timestamps
    after the first message. Startup delay before the first row is not a gap.

    Example::

        col.messaging.redis.verify_listen(key="status", min_received=1)
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
def start_sender(*, redis_id: int, key: str = "") -> None:
    """Start a thread that publishes queued Redis messages.

    Example::

        col.messaging.redis.start_sender(redis_id=1)
        col.messaging.redis.enqueue(redis_id=1, channel="events", message="arm")
        col.messaging.redis.stop_sender(redis_id=1)

    :param redis_id: Configured ``messaging.redis`` id from bench TOML.
    :param key: Optional evidence key for the command row.
    """
    _ = key
    get_redis_client(redis_id).start_sender()


@command
def enqueue(
    *, redis_id: int, channel: str, message: str, key: str = "",
) -> None:
    """Queue one Redis publish. ``start_sender`` must already be running.

    Example::

        col.messaging.redis.enqueue(redis_id=1, channel="events", message="arm")

    :param redis_id: Configured ``messaging.redis`` id from bench TOML.
    :param channel: Pub/sub channel name.
    :param message: Message payload.
    :param key: Optional evidence key for the command row.
    """
    _ = key
    get_redis_client(redis_id).enqueue(channel, message)


@command
def stop_sender(*, redis_id: int, key: str = "") -> None:
    """Stop a Redis send thread after it delivers queued messages.

    Example::

        col.messaging.redis.stop_sender(redis_id=1)

    :param redis_id: Configured ``messaging.redis`` id passed to ``start_sender``.
    :param key: Optional evidence key for the command row.
    """
    _ = key
    get_redis_client(redis_id).stop_sender()
