"""One thread that polls a socket, offers queued sends, or both."""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from typing import Optional

from colosseum.logging import get_logger

_logger = get_logger("colosseum.messaging.pump")

# Short enough that stop() joins promptly, long enough to avoid a busy loop.
_POLL_TIMEOUT_S = 0.2
_STOP_TIMEOUT_S = 2.0
_OUTBOX_SIZE = 256

Poll = Callable[[float], Optional[dict[str, str]]]
Offer = Callable[[object], None]
Hook = Callable[[dict[str, str]], None]


def topic_payload(item: object) -> tuple[str, str]:
    if isinstance(item, tuple) and len(item) == 2:
        return str(item[0]), str(item[1])
    raise TypeError("send item must be (topic, payload)")


class MessagePump:
    """Daemon thread. ``poll`` and ``on_message`` run on that thread.

    ``submit`` queues work for ``offer``. A full outbox raises ``queue.Full``.
    ``TimeoutError`` from ``poll`` means no message. Any other ``poll`` or
    ``on_message`` error is counted and the loop keeps going.
    """

    def __init__(
        self,
        *,
        poll: Poll | None = None,
        offer: Offer | None = None,
        on_message: Hook | None = None,
        name: str,
        outbox_size: int = _OUTBOX_SIZE,
    ) -> None:
        if poll is None and offer is None:
            raise ValueError("MessagePump requires poll or offer")
        self._poll = poll
        self._offer = offer
        self._on_message = on_message
        self.name = name
        self._stop = threading.Event()
        self._outbox: queue.Queue[object] = queue.Queue(maxsize=outbox_size)
        self._thread = threading.Thread(target=self._run, name=name, daemon=True)
        self.errors = 0
        self.last_error = ""

    @property
    def running(self) -> bool:
        return self._thread.is_alive()

    def start(self) -> None:
        if self._thread.is_alive():
            raise RuntimeError("message pump is already running")
        self._stop.clear()
        self.errors = 0
        self.last_error = ""
        self._thread = threading.Thread(target=self._run, name=self.name, daemon=True)
        self._thread.start()

    def submit(self, item: object) -> None:
        if self._offer is None or not self._thread.is_alive():
            raise RuntimeError("send pump is not running")
        self._outbox.put_nowait(item)

    def stop(self, timeout: float = _STOP_TIMEOUT_S) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def _run(self) -> None:
        while not self._stop.is_set():
            self._drain_outbox(wait=_POLL_TIMEOUT_S if self._poll is None else 0.0)
            message = self._poll_one()
            if message is not None:
                self._deliver(message)
        self._drain_outbox(wait=0.0)

    def _poll_one(self) -> dict[str, str] | None:
        if self._poll is None:
            return None
        try:
            return self._poll(_POLL_TIMEOUT_S)
        except TimeoutError:
            return None
        except Exception as exc:
            _logger.exception("Message pump %s poll error", self.name)
            self._note_error(exc)
            return None

    def _deliver(self, message: dict[str, str]) -> None:
        if self._on_message is None:
            return
        try:
            self._on_message(message)
        except Exception as exc:
            _logger.exception("Message pump %s callback error", self.name)
            self._note_error(exc)

    def _drain_outbox(self, *, wait: float) -> None:
        if self._offer is None:
            return
        sent = False
        while True:
            try:
                item = self._outbox.get_nowait()
            except queue.Empty:
                break
            self._offer_one(item)
            sent = True
        if sent or wait <= 0.0:
            return
        try:
            item = self._outbox.get(timeout=wait)
        except queue.Empty:
            return
        self._offer_one(item)

    def _offer_one(self, item: object) -> None:
        if self._offer is None:
            return
        try:
            self._offer(item)
        except Exception as exc:
            _logger.exception("Message pump %s send error", self.name)
            self._note_error(exc)

    def _note_error(self, exc: Exception) -> None:
        self.errors += 1
        self.last_error = str(exc)


class PumpHandle:
    """Holds the one pump a client may have for listen or for send."""

    def __init__(self) -> None:
        self._pump: MessagePump | None = None

    def running(self) -> bool:
        pump = self._pump
        return pump is not None and pump.running

    def start(
        self,
        *,
        poll: Poll | None = None,
        offer: Offer | None = None,
        on_message: Hook | None = None,
        name: str,
    ) -> None:
        if self.running():
            raise RuntimeError("message pump is already running")
        pump = MessagePump(poll=poll, offer=offer, on_message=on_message, name=name)
        pump.start()
        self._pump = pump

    def stop(self) -> None:
        pump = self._pump
        if pump is None:
            return
        pump.stop()
        if pump.running:
            raise RuntimeError(f"message pump {pump.name} did not stop")
        self._pump = None

    def submit(self, item: object) -> None:
        pump = self._pump
        if pump is None or not pump.running:
            raise RuntimeError("send pump is not running")
        pump.submit(item)
