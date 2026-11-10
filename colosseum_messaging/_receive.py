"""Shared deadline receive helpers for MQTT/Redis/ZMQ clients."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, TypeVar

from colosseum_messaging.sim import SIM_MAILBOX

if TYPE_CHECKING:
    from collections.abc import Callable

T = TypeVar("T")


def sim_receive_matching(
    token: int,
    timeout: float,
    *,
    matches: Callable[[str, str], bool],
    timeout_message: str,
) -> dict[str, str]:
    """Poll the sim mailbox until a matching topic/payload arrives or timeout."""
    deadline = time.monotonic() + timeout
    while True:
        remaining = max(0.0, deadline - time.monotonic())
        item = SIM_MAILBOX.receive(token, remaining)
        if item is None:
            raise TimeoutError(timeout_message)
        topic, payload = item
        if matches(topic, payload):
            return {"topic": topic, "payload": payload}
        if remaining <= 0:
            raise TimeoutError(timeout_message)


def deadline_poll(
    timeout: float,
    *,
    poll: Callable[[float], T | None],
    accept: Callable[[T], bool],
    timeout_message: str,
) -> T:
    """Poll until ``accept`` matches an item or the deadline elapses.

    ``poll`` receives the remaining seconds. Return ``None`` to keep waiting;
    raise ``TimeoutError`` yourself when the underlying source is exhausted.
    """
    deadline = time.monotonic() + timeout
    while True:
        remaining = max(0.0, deadline - time.monotonic())
        if remaining <= 0:
            raise TimeoutError(timeout_message)
        item = poll(remaining)
        if item is not None and accept(item):
            return item
        if time.monotonic() >= deadline:
            raise TimeoutError(timeout_message)
