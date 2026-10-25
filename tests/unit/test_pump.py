"""MessagePump stop, callback errors, and the send outbox."""

from __future__ import annotations

import queue
import threading
import time

import pytest
from colosseum_messaging._pump import MessagePump


def test_stop_joins_a_poll_loop() -> None:
    def poll(_timeout: float) -> dict[str, str] | None:
        return None

    pump = MessagePump(poll=poll, name="poll-stop")
    pump.start()
    assert pump.running
    pump.stop()
    assert not pump.running


def test_callback_exception_does_not_stop_the_loop() -> None:
    delivered: list[str] = []
    saw_both = threading.Event()

    def poll(_timeout: float) -> dict[str, str] | None:
        if len(delivered) >= 2:
            time.sleep(0.01)
            return None
        return {"topic": "t", "payload": str(len(delivered))}

    def on_message(message: dict[str, str]) -> None:
        delivered.append(message["payload"])
        if message["payload"] == "0":
            raise RuntimeError("boom")
        if len(delivered) >= 2:
            saw_both.set()

    pump = MessagePump(poll=poll, on_message=on_message, name="poll-error")
    pump.start()
    assert saw_both.wait(1.0)
    pump.stop()
    assert delivered == ["0", "1"]
    assert pump.errors == 1
    assert pump.last_error == "boom"


def test_submit_fills_the_outbox_and_raises_when_full() -> None:
    started = threading.Event()
    release = threading.Event()
    sent: list[object] = []

    def offer(item: object) -> None:
        sent.append(item)
        started.set()
        release.wait(1.0)

    pump = MessagePump(offer=offer, name="send-full", outbox_size=1)
    pump.start()
    pump.submit(("cmd", "a"))
    assert started.wait(1.0)
    pump.submit(("cmd", "b"))
    with pytest.raises(queue.Full):
        pump.submit(("cmd", "c"))
    release.set()
    pump.stop()
    assert ("cmd", "a") in sent
    assert ("cmd", "b") in sent
