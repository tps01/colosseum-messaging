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
from colosseum_messaging.connections import get_zmq_client

if TYPE_CHECKING:
    from collections.abc import Callable

_LISTEN_COMMAND = "zmq.listen"


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
            return cast("object", row.value)
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


@command
def listen(
    *,
    zmq_id: int,
    key: str,
    fail_pattern: str = "",
    on_message: Callable[[dict[str, str]], None] | None = None,
) -> None:
    r"""Record each ZMQ SUB message until ``stop_listen``.

    Every message is a ``messaging`` / ``zmq.listen`` measurement. ``value``
    is ``{"topic", "payload"}``. ``fail_pattern`` marks a matching payload
    ``FAIL``. ``on_message``, when set, runs after that insert.

    Example::

        col.messaging.zmq.listen(
            zmq_id=2, key="status", fail_pattern=r"\b(ERR|FAULT|offline)\b",
        )
        col.messaging.zmq.stop_listen(zmq_id=2, key="status")
        col.messaging.zmq.verify_listen(
            key="status", max_silence_s=0.5, min_received=1,
        )

    :param zmq_id: Configured ``messaging.zmq`` id with ``socket = "sub"``.
    :param key: Measurement key shared with ``stop_listen`` and ``verify_listen``.
    :param fail_pattern: Regex applied to ``payload``. Empty matches nothing.
    :param on_message: Optional hook called with ``{"topic", "payload"}``.
    """
    get_zmq_client(zmq_id).start_listen(
        make_handler(
            command=_LISTEN_COMMAND,
            key=key,
            fail_pattern=fail_pattern,
            on_message=on_message,
        ),
    )


@command
def stop_listen(*, zmq_id: int, key: str = "") -> None:
    """Stop a ZMQ listen thread and drain measurement writes.

    Example::

        col.messaging.zmq.stop_listen(zmq_id=2, key="status")

    :param zmq_id: Configured ``messaging.zmq`` id passed to ``listen``.
    :param key: Evidence key for this command. Use the ``listen`` key.
    """
    _ = key
    get_zmq_client(zmq_id).stop_listen()
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
    """Judge stored ``zmq.listen`` rows for failures, errors, and silence.

    ``max_silence_s`` is the longest allowed gap between stored timestamps
    after the first message. Startup delay before the first row is not a gap.

    Example::

        col.messaging.zmq.verify_listen(
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
def start_sender(*, zmq_id: int, key: str = "") -> None:
    """Start a thread that owns the ZMQ PUB socket and sends queued payloads.

    Example::

        col.messaging.zmq.start_sender(zmq_id=1)
        col.messaging.zmq.enqueue(zmq_id=1, payload="arm", topic="cmd")
        col.messaging.zmq.stop_sender(zmq_id=1)

    :param zmq_id: Configured ``messaging.zmq`` id with ``socket = "pub"``.
    :param key: Optional evidence key for the command row.
    """
    _ = key
    get_zmq_client(zmq_id).start_sender()


@command
def enqueue(*, zmq_id: int, payload: str, topic: str = "", key: str = "") -> None:
    """Queue one ZMQ PUB payload. ``start_sender`` must already be running.

    Example::

        col.messaging.zmq.enqueue(zmq_id=1, payload="arm", topic="cmd")

    :param zmq_id: Configured ``messaging.zmq`` id with ``socket = "pub"``.
    :param payload: Message payload.
    :param topic: Optional topic prefix. Empty uses the configured topic.
    :param key: Optional evidence key for the command row.
    """
    _ = key
    get_zmq_client(zmq_id).enqueue(payload, topic)


@command
def stop_sender(*, zmq_id: int, key: str = "") -> None:
    """Stop a ZMQ send thread after it delivers queued payloads.

    Example::

        col.messaging.zmq.stop_sender(zmq_id=1)

    :param zmq_id: Configured ``messaging.zmq`` id passed to ``start_sender``.
    :param key: Optional evidence key for the command row.
    """
    _ = key
    get_zmq_client(zmq_id).stop_sender()
